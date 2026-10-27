"""Small manual smoke-test helpers. Requires MODE=C server on port 8002."""
import asyncio
import uuid
import httpx

URL = "http://127.0.0.1:8002/api/mutated/epoch_x92"


async def main():
    async with httpx.AsyncClient() as client:
        nonce = str(uuid.uuid4())
        payload = {"x_829": 1, "q_01": 1}
        first = await client.post(URL, json=payload, headers={"X-Epoch-Nonce": nonce})
        replay = await client.post(URL, json=payload, headers={"X-Epoch-Nonce": nonce})
        malformed = await client.post(URL, content=b"{", headers={"X-Epoch-Nonce": str(uuid.uuid4())})
        oversized = await client.post(URL, content=b"x" * (1024 * 1024 + 1))

        print("first request:", first.status_code, first.text)
        print("replayed nonce:", replay.status_code, replay.text)
        print("malformed JSON:", malformed.status_code, malformed.text)
        print("oversized payload:", oversized.status_code, oversized.text)


if __name__ == "__main__":
    asyncio.run(main())
