import asyncio
import httpx
import random
import time

URL = "http://127.0.0.1:8000/generate"

PROMPTS = [
    "hello world",
    "explain kv cache in llm inference",
    "this is a medium length prompt for testing scheduler kv cache behavior",
    " ".join(["longprompt"] * 32),
]

async def send_one(client, i):
    prompt = random.choice(PROMPTS)
    max_new_tokens = random.choice([8, 16, 32])

    start = time.time()
    try:
        r = await client.post(
            URL,
            json={
                "prompt": prompt,
                "max_new_tokens": max_new_tokens,
            },
            timeout=5.0,
        )
        latency_ms = (time.time() - start) * 1000
        return r.status_code, latency_ms, r.json()
    except Exception as e:
        return "error", None, str(e)

async def main():
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(40):
            tasks.append(asyncio.create_task(send_one(client, i)))
            await asyncio.sleep(0.02)

        results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r[0] == 200)
    failed = len(results) - ok

    print("total:", len(results))
    print("ok:", ok)
    print("failed:", failed)

    latencies = [r[1] for r in results if isinstance(r[1], float)]
    if latencies:
        latencies.sort()
        print("avg_submit_latency_ms:", sum(latencies) / len(latencies))
        print("p95_submit_latency_ms:", latencies[int(len(latencies) * 0.95) - 1])

asyncio.run(main())