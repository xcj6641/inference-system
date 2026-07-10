# an http endpoint to simulate the vllm response

from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict):
    return {
        "id": "mock-chatcmpl-001",
        "object": "chat.completion",
        "model": payload.get("model", "mock-model"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "hello from mock vllm server",
                },
                "finish_reason": "stop",
            }
        ],
    }