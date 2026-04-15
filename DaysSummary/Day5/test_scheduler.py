import asyncio
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"


async def submit_request(client: httpx.AsyncClient, prompt: str, max_new_tokens: int):
    resp = await client.post(
        f"{BASE_URL}/generate",
        json={
            "prompt": prompt,
            "max_new_tokens": max_new_tokens,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"submitted prompt={prompt}, request_id={data['request_id']}, state={data['state']}")
    return data["request_id"]


async def poll_request_until_done(client: httpx.AsyncClient, request_id: str):
    while True:
        resp = await client.get(f"{BASE_URL}/requests/{request_id}")
        resp.raise_for_status()
        data = resp.json()

        print(
            f"request_id={request_id} "
            f"state={data['state']} "
            f"tokens={data['generated_tokens']}"
        )

        if data["state"] == "FINISHED":
            return data

        await asyncio.sleep(0.2)


async def main():
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Submit several requests nearly at the same time
        submit_tasks = [
            submit_request(client, "req-1", 5),
            submit_request(client, "req-2", 4),
            submit_request(client, "req-3", 6),
            submit_request(client, "req-4", 3),
            submit_request(client, "req-5", 5),
        ]

        request_ids = await asyncio.gather(*submit_tasks)

        print("\nall submitted:", request_ids)
        print("\nstart polling...\n")

        start = time.time()

        results = await asyncio.gather(
            *[poll_request_until_done(client, rid) for rid in request_ids]
        )

        elapsed = time.time() - start
        print(f"\nall finished in {elapsed:.2f}s\n")

        for r in results:
            print(
                f"FINAL request_id={r['request_id']} "
                f"state={r['state']} "
                f"tokens={r['generated_tokens']}"
            )


if __name__ == "__main__":
    asyncio.run(main())