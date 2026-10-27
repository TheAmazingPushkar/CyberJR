"""Async benchmark for A/B/C. Run only against your local lab servers."""
import asyncio
import math
import statistics
import time
import uuid
from dataclasses import dataclass

import httpx

REQUESTS_PER_WORKER = 200
CONCURRENCY = 50
TIMEOUT_SECONDS = 10.0

CONFIGS = [
    ("A baseline", "http://127.0.0.1:8000/api/v1/checkout", False, False),
    ("B mutation only", "http://127.0.0.1:8001/api/mutated/epoch_x92", True, False),
    ("C mutation + Redis replay guard", "http://127.0.0.1:8002/api/mutated/epoch_x92", True, True),
]


def percentile(values, p):
    """Nearest-rank percentile; returns None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return ordered[index]


@dataclass
class Results:
    latencies_ms: list
    statuses: list
    exceptions: list


async def worker(client, url, mutated, replay_guard, results):
    for _ in range(REQUESTS_PER_WORKER):
        nonce = str(uuid.uuid4())
        if mutated:
            payload = {"x_829": 1, "q_01": 1}
        else:
            payload = {"item_id": 1, "qty": 1}
        headers = {"X-Epoch-Nonce": nonce} if replay_guard else {}
        started = time.perf_counter()
        try:
            response = await client.post(url, json=payload, headers=headers)
            elapsed_ms = (time.perf_counter() - started) * 1000
            results.latencies_ms.append(elapsed_ms)
            results.statuses.append(response.status_code)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            results.latencies_ms.append(elapsed_ms)
            results.exceptions.append(f"{type(exc).__name__}: {exc}")


async def run_config(name, url, mutated, replay_guard):
    limits = httpx.Limits(
        max_keepalive_connections=CONCURRENCY,
        max_connections=CONCURRENCY,
    )
    timeout = httpx.Timeout(TIMEOUT_SECONDS)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # Warm-up is excluded from measurements.
        for _ in range(20):
            payload = {"x_829": 1, "q_01": 1} if mutated else {"item_id": 1, "qty": 1}
            headers = {"X-Epoch-Nonce": str(uuid.uuid4())} if replay_guard else {}
            try:
                await client.post(url, json=payload, headers=headers)
            except Exception:
                pass

        results = Results([], [], [])
        start = time.perf_counter()
        await asyncio.gather(*[
            worker(client, url, mutated, replay_guard, results)
            for _ in range(CONCURRENCY)
        ])
        elapsed = time.perf_counter() - start

    total = len(results.latencies_ms)
    success = sum(200 <= status < 300 for status in results.statuses)
    non_2xx = sum(not (200 <= status < 300) for status in results.statuses)
    failed = len(results.exceptions) + non_2xx

    summary = {
        "name": name,
        "requests": total,
        "successful": success,
        "failed_or_non_2xx": failed,
        "error_rate_pct": (failed / total * 100) if total else 0,
        "successful_rps": success / elapsed if elapsed else 0,
        "total_rps": total / elapsed if elapsed else 0,
        "p50_ms": percentile(results.latencies_ms, 0.50),
        "p95_ms": percentile(results.latencies_ms, 0.95),
        "p99_ms": percentile(results.latencies_ms, 0.99),
        "elapsed_s": elapsed,
        "exceptions_sample": results.exceptions[:3],
    }
    print("\n" + "=" * 72)
    for key, value in summary.items():
        print(f"{key:24s}: {value}")
    return summary


async def main():
    all_results = []
    for config in CONFIGS:
        all_results.append(await run_config(*config))
    print("\nNOTE: compare several repeated runs; do not treat one run as a conclusion.")
    return all_results


if __name__ == "__main__":
    asyncio.run(main())
