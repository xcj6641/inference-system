import asyncio
import httpx
import random
import string

URL = "http://localhost:8000/generate"

def short_prompt(case_no: int):
    return f"hi-{case_no}"

def long_prompt(case_no: int):
    return f"hello-{case_no} " * 200  # large prompt_tokens

def random_prompt(case_no: int, length=20):
    random_suffix = "".join(random.choices(string.ascii_lowercase, k=length))
    return f"rand-{case_no}-{random_suffix}"


async def send_request(client, prompt, max_new_tokens):
    payload = {
        "prompt": prompt,
        "max_new_tokens": max_new_tokens,
    }
    resp = await client.post(URL, json=payload)
    return resp.json()


# ----------------------------
# TEST CASES
# ----------------------------

async def test_short_prompts(n=20):
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            send_request(client, short_prompt(i + 1), 10)
            for i in range(n)
        ]
        return await asyncio.gather(*tasks)


async def test_long_prompts(n=20):
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            send_request(client, long_prompt(i + 1), 10)
            for i in range(n)
        ]
        return await asyncio.gather(*tasks)


async def test_long_generation(n=20):
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            send_request(client, short_prompt(i + 1), 200)
            for i in range(n)
        ]
        return await asyncio.gather(*tasks)


async def test_mixed(n=30):
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []

        for i in range(n):
            r = random.random()
            case_no = i + 1

            if r < 0.33:
                # short
                tasks.append(send_request(client, short_prompt(case_no), 10))
            elif r < 0.66:
                # long prompt
                tasks.append(send_request(client, long_prompt(case_no), 10))
            else:
                # long generation
                tasks.append(send_request(client, short_prompt(case_no), 200))

        return await asyncio.gather(*tasks)


# ----------------------------
# MAIN
# ----------------------------

async def main():
    # print("Running test_short_prompts test...")
    # results = await test_short_prompts(30)
    # print("Running test_long_prompts test...")
    # results = await test_long_prompts(30)
    print("Running test_long_generation test...")
    results = await test_long_generation(30)
    # print("Running mixed test...")
    # results = await test_mixed(30)
    print(f"Submitted {len(results)} requests")


if __name__ == "__main__":
    asyncio.run(main())