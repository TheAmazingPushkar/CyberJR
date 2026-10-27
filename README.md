# Mutation-defense research prototype

This project compares three **local research configurations**:

- A: baseline FastAPI endpoint
- B: bounded body buffering + deterministic schema/route translation
- C: B + atomic Redis nonce replay guard

It is a benchmark scaffold, not production security middleware. The route/schema mapping is intentionally deterministic and client-visible; it is not cryptographic protection. No real payment or database operation is performed.

## Setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start Redis for Configuration C. Docker example:

```powershell
docker run --name mutation-redis -p 6379:6379 -d redis:7-alpine
```

Run each configuration in a separate terminal from the project root:

```powershell
$env:MODE="A";(next line) uvicorn app.main:app --host 127.0.0.1 --port 8000
$env:MODE="B"; uvicorn app.main:app --host 127.0.0.1 --port 8001
$env:MODE="C"; $env:REDIS_URL="redis://localhost:6379/0"; uvicorn app.main:app --host 127.0.0.1 --port 8002
```

If PowerShell's `$env:MODE` assignment is awkward in separate terminals, use one terminal per command. Stop each server with Ctrl+C.

Run benchmark in another terminal:

```powershell
python tests/benchmark_harness.py
```
To Check Servers(optional, if things go wrong)

```
Test-NetConnection 127.0.0.1 -Port 8000
Test-NetConnection 127.0.0.1 -Port 8001
Test-NetConnection 127.0.0.1 -Port 8002
```

Run smoke tests:

```powershell
python tests/test_replay_and_limits.py
```

## What the benchmark means

The script reports latency for every completed HTTP attempt, including non-2xx responses and exceptions. It uses nearest-rank p50/p95/p99 and excludes a small warm-up. Run at least 5 trials per configuration, alternate the order (A/B/C then C/A/B), and report median results across trials. Keep server process count, machine, Python version, Redis location, request payload and concurrency identical.

For a fair p99 comparison, measure A/B/C on the same machine and avoid competing CPU-intensive work. This basic client benchmark is not a load-testing substitute for Locust, k6 or a dedicated generator. The client can become the bottleneck.

## Tests to add before drawing conclusions

1. Repeat the same nonce against C: first request should succeed; replay should return 409.
2. Send malformed JSON, non-object JSON, missing mutated keys and oversized bodies.
3. Test fragmented ASGI bodies and client disconnects using an ASGI-level test client / custom receive callable; an ordinary HTTP client does not reliably simulate every disconnect pattern.
4. Add actual epoch token validation and clock-skew cases before making any epoch-boundary claim. This scaffold does **not** implement cryptographic epochs.
5. Compare against baseline plus ordinary server-side authorization and rate limiting.
6. Test an adaptive HTTP client and persistent browser automation. Do not assume browser startup cost is paid per request.

## Prototype limitations

- `Content-Length` and body size are bounded here, but a per-request cap does not bound aggregate memory under high concurrency. Enforce limits at the reverse proxy/ASGI server too.
- The body-read timeout is a prototype guard; tune it for the server and expected upload behavior.
- The middleware's replay guard applies only to the mutated research route.
- Redis nonce keys expire after 120 seconds. That window and failure policy are experimental choices, not universal recommendations.
- This prototype does not establish that mutation prevents bots, scrapers or authorization failures.
