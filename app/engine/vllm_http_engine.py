# app/engine/vllm_http_engine.py

import httpx


class VLLMHttpEngine:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._outputs: dict[str, list[str]] = {}

    async def prefill(self, req):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": req.prompt}
            ],
            "max_tokens": req.max_new_tokens,
            "temperature": 0.0,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["choices"][0]["message"]["content"]

        # Day 10 简化：按空格切成 token-like chunks
        chunks = text.split()
        if not chunks:
            chunks = [text]

        self._outputs[req.request_id] = chunks

    async def decode_step(self, requests):
        results = []

        for req in requests:
            chunks = self._outputs.get(req.request_id, [])

            if chunks:
                token = chunks.pop(0)
                finished = len(chunks) == 0
                results.append((req.request_id, token, finished))
            else:
                results.append((req.request_id, "", True))

        return results