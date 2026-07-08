I think Day 9 is one of the biggest milestones in your project. Before Day 9, your system behaved like a traditional HTTP backend (request → wait → response). After Day 9, it behaves much more like a modern LLM serving system (request → incremental token streaming). That's a significant architectural step.

---

# Day 9 — Streaming Token Pipeline

## Goal

Transform the inference runtime from a traditional request/response model into a token streaming pipeline, similar to ChatGPT, vLLM, and TGI.

Before Day 9:

```text
Client
    │
POST /generate
    │
    ▼
Scheduler
    │
    ▼
FakeEngine
    │
(generate all tokens)
    │
    ▼
Return full response
```

After Day 9:

```text
Client
    │
POST /generate
    │
    ▼
Scheduler
    │
decode one token
    │
    ▼
Token Stream Queue
    │
    ▼
StreamingResponse
    │
    ▼
Client receives tokens immediately
```

---

# What We Implemented

## 1. Request-local Token Stream

Added a dedicated asynchronous queue to every request.

```python
END_OF_STREAM = object()

@dataclass
class GenerationRequest:
    ...
    token_stream: asyncio.Queue = field(
        default_factory=asyncio.Queue
    )
```

Each request now owns its own token stream.

---

## 2. Scheduler Becomes a Token Publisher

Previously:

```python
req.generated_tokens.append(token)
```

Now:

```python
req.generated_tokens.append(token)

await req.token_stream.put(token)
```

The scheduler now publishes tokens instead of waiting for the entire generation to complete.

When generation finishes:

```python
await req.token_stream.put(END_OF_STREAM)
```

---

## 3. HTTP Streaming

Replaced the traditional JSON response with FastAPI's `StreamingResponse`.

```python
async def stream(gen_req):

    while True:

        token = await gen_req.token_stream.get()

        if token is END_OF_STREAM:
            break

        yield json.dumps({
            "request_id": gen_req.request_id,
            "token": token,
        }) + "\n"
```

API layer:

```python
return StreamingResponse(
    stream(gen_req),
    media_type="application/x-ndjson",
)
```

The HTTP layer now consumes tokens independently from the scheduler.

---

## 4. Producer–Consumer Architecture

The runtime is now cleanly decoupled.

```text
Scheduler
    │
    │ publish
    ▼
asyncio.Queue
    ▲
    │ consume
StreamingResponse
```

Scheduler knows nothing about HTTP.

FastAPI knows nothing about the inference engine.

---

# Testing

## Functional Test

Verified streaming with `curl`.

```bash
curl -N -X POST ...
```

Output:

```text
{"request_id":"...","token":"tok1"}
{"request_id":"...","token":"tok2"}
...
```

---

## Concurrent Streaming

Started two simultaneous clients.

Observed scheduler logs:

```text
tick2695

decode:

RequestA -> tok7
RequestB -> tok1
```

This demonstrates:

* continuous batching remained intact
* requests streamed independently
* new requests joined active decoding without interrupting existing requests

---

## Unit Test

Added:

```text
tests/test_streaming.py
```

Verified:

* queue ordering
* end-of-stream sentinel
* asynchronous queue behavior

Result:

```text
1 passed
```

---

## Integration Test

Added:

```text
tests/test_streaming_api.py
```

Verified the complete pipeline:

```text
HTTP Request
    ↓
FastAPI
    ↓
Scheduler
    ↓
FakeEngine
    ↓
Token Queue
    ↓
StreamingResponse
    ↓
HTTP Client
```

Result:

```text
1 passed
```

---

# Asyncio Concepts Learned

Day 9 also became a deep dive into asynchronous programming.

Covered concepts:

### `async def`

Declares a coroutine that is allowed to suspend.

---

### `await`

Actually suspends the coroutine and yields execution back to the event loop.

Example:

```python
decode_results = await self.engine.decode_step(...)
```

---

### Coroutine

A coroutine is a pauseable function.

Unlike a normal function, it remembers:

* local variables
* execution state
* next instruction

allowing the event loop to resume it later.

---

### `async with`

Used with `asyncio.Lock`.

Equivalent to:

```python
await lock.acquire()

try:
    ...
finally:
    lock.release()
```

without blocking the thread.

---

### `asyncio.Queue`

Implemented a producer-consumer model.

Producer:

```python
await queue.put(token)
```

Consumer:

```python
await queue.get()
```

Neither side blocks the event loop.

---

# Understanding the Event Loop

Learned that:

* asynchronous coroutines generally execute within a **single thread**
* `await` pauses only the current coroutine
* the event loop schedules other ready coroutines
* this enables one thread to efficiently serve many concurrent requests

---

# Multi-worker Discussion

Discussed why:

```bash
uvicorn --workers 4
```

creates four **processes**, not four threads.

Each process owns:

* scheduler
* request queue
* KV manager
* event loop

They do not share memory.

For LLM serving, this often leads to:

* duplicated model loading
* duplicated GPU memory usage
* fragmented batching

which is why many production inference systems prefer:

```text
One Scheduler
One Engine
One GPU
Many Async Requests
```

rather than multiple independent worker processes.

---

# Final Architecture

```text
                    HTTP Client
                         │
                         ▼
               FastAPI StreamingResponse
                         │
                         ▼
              Request.token_stream Queue
                         ▲
                         │
                 publish(token)
                         │
                 Continuous Scheduler
                         │
                         ▼
                    Model Engine
                  (FakeEngine today)
```

---

# Interview Takeaways

After Day 9, you can confidently discuss:

* **Streaming inference:** Incremental token delivery instead of waiting for the full completion.
* **Producer–consumer design:** Decoupling token generation from HTTP transport using `asyncio.Queue`.
* **Asynchronous runtime:** Using coroutines, `await`, `asyncio.Lock`, and the event loop to support many concurrent requests within a single process.
* **Continuous batching compatibility:** Streaming did not require changes to the scheduler's batching logic.
* **Separation of concerns:** The scheduler publishes tokens, the HTTP layer streams them, and the engine remains unaware of networking.

---

# Project Progress

| Day       | Feature                                      |
| --------- | -------------------------------------------- |
| Day 4     | Scheduler / Engine separation                |
| Day 5     | Continuous batching                          |
| Day 6     | Prefill / Decode separation + Token budget   |
| Day 7     | KV Cache abstraction + Admission by memory   |
| Day 8     | Backend abstraction (`ModelEngine`)          |
| **Day 9** | **Streaming token pipeline + Async runtime** |

This is a strong foundation for **Day 10**, where you can replace `FakeEngine` with a real backend (such as vLLM) while leaving the scheduler and streaming layer unchanged. That's a hallmark of a well-designed inference serving architecture.
