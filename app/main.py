import asyncio
import uuid
import os
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models import GenerationRequest, END_OF_STREAM
from app.store import RequestStore
from app.engine import FakeEngine
from app.scheduler import Scheduler, SchedulerConfig, SchedulerStats
from app.logger_config import setup_logger


app = FastAPI()

store = RequestStore()
engine = FakeEngine()
scheduler = Scheduler(
    store=store,
    engine=engine,
    config=SchedulerConfig(
        max_active_sequences=16,
        max_batch_tokens=64,
        # max_kv_capacity=128,
        max_kv_capacity=int(os.getenv("MAX_KV_CAPACITY", 128)),

        max_tokens_in_flight=512,
        max_prefill_per_tick=16,
        tick_interval_s=0.1,
    ),
)
logger = setup_logger()


class GenerateRequest(BaseModel):
    prompt: str
    # Default value: 5
    # Minimum allowed: 1 (ge = greater than or equal)
    # Maximum allowed: 300 (le = less than or equal) # type: ignore
    # FastAPI uses this to validate incoming requests and document the constraint in OpenAPI/Swagger. Invalid values automatically receive a 422 response.
    max_new_tokens: int = Field(default=5, ge=1, le=300) # type: ignore


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(scheduler.run_forever())

def estimate_prompt_tokens(prompt: str) -> int:
    # 简单 mock：按空格切
    # 如果你想更稳定一点，也可以 max(1, len(prompt.split()))
    return max(1, len(prompt.split()))


async def stream(req: GenerateRequest):
    while True:
        token = await req.token_stream.get()

        if token is END_OF_STREAM:
            break

        yield json.dumps({
            "request_id": req.request_id,
            "token": token,
        }) + "\n"

@app.post("/generate")
async def generate(req: GenerateRequest):
    request_id = str(uuid.uuid4())[:8]
    gen_req = GenerationRequest(
        request_id=request_id,
        prompt=req.prompt,
        max_new_tokens=req.max_new_tokens,
    )

    gen_req.prompt_tokens = estimate_prompt_tokens(req.prompt)
    gen_req.reserved_tokens = gen_req.prompt_tokens + req.max_new_tokens

    if gen_req.reserved_tokens > scheduler.config.max_tokens_in_flight:
        logger.warning(
            f"[reject] request_id={request_id} prompt={req.prompt!r} "
            f"reserved_tokens={gen_req.reserved_tokens} "
            f"max_tokens_in_flight={scheduler.config.max_tokens_in_flight} "
            f"reason=request_too_large"
        )
        raise HTTPException(
            status_code=413,
            detail={
                "error": "request_too_large",
                "message": (
                    f"request requires {gen_req.reserved_tokens} reserved tokens, "
                    f"but scheduler capacity is {scheduler.config.max_tokens_in_flight}"
                ),
            },
        )

    await store.add_waiting_request(gen_req)

    logger.info(
        f"[submit] request_id={request_id} "
        f"prompt_tokens={gen_req.prompt_tokens} reserved_tokens={gen_req.reserved_tokens} "
        f"max_new_tokens={req.max_new_tokens} state={gen_req.state} prompt={req.prompt!r}"
    )

    # return {
    #     "request_id": request_id,
    #     "state": gen_req.state,
    # }
    return StreamingResponse(
        stream(gen_req),
        media_type="application/x-ndjson",
    )

@app.get("/requests/{request_id}")
async def get_request_status(request_id: str):
    req = await store.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="request not found")

    return {
        "request_id": req.request_id,
        "prompt": req.prompt,
        "state": req.state,
        "generated_tokens": req.generated_tokens,
        "max_new_tokens": req.max_new_tokens,
        "arrival_time": req.arrival_time,
        "admitted_time": req.admitted_time,
        "prefill_start_time": req.prefill_start_time,
        "prefill_end_time": req.prefill_end_time,
        "first_decode_time": req.first_decode_time,
        "finished_time": req.finished_time,
        "queue_wait_ms": req.queue_wait_ms,
        "prefill_wait_ms": req.prefill_wait_ms,
        "prefill_duration_ms": req.prefill_duration_ms,
        "time_to_first_token_ms": req.time_to_first_token_ms,
        "decode_tail_ms": req.decode_tail_ms,
        "total_latency_ms": req.total_latency_ms,
        "service_time_ms": req.service_time_ms,
    }


@app.get("/scheduler/debug")
async def scheduler_debug():
    async with store.lock:
        return {
            "tick": scheduler.tick,
            "max_tokens_in_flight": scheduler.config.max_tokens_in_flight,
            "current_tokens_in_flight": scheduler.stats.current_tokens,
            "max_prefill_per_tick": scheduler.config.max_prefill_per_tick,
            "waiting_queue_size": len(store.waiting_queue),
            "active_request_ids": list(store.active_requests.keys()),
            "finished_request_ids": list(store.finished_requests.keys()),
            "all_request_ids": list(store.all_requests.keys()),
            "kv": {
                "capacity": scheduler.kv_manager.capacity,
                "used":  scheduler.kv_manager.used,
                "available": scheduler.kv_manager.available,
                "reserved_for_decode": scheduler.kv_manager.decode_reserved,
                "utilization": scheduler.kv_manager.utilization
            },
            "token_utilization": scheduler.stats.current_tokens // scheduler.config.max_tokens_in_flight,
            "kv_block_size": scheduler.config.kv_block_size,
            "max_active_sequences": scheduler.config.max_active_sequences,
            "active_sequences": scheduler.stats.active_sequences,
            "stats": {
                "admitted_requests": scheduler.stats.admitted_requests,
                "completed_requests": scheduler.stats.completed_requests,
                "admission_blocked_ticks": scheduler.stats.admission_blocked_ticks,
                "blocked_by_kv_capacity": scheduler.stats.blocked_by_kv_capacity,
                "blocked_by_token_budget": scheduler.stats.blocked_by_token_budget,
                "blocked_by_active_sequences": scheduler.stats.blocked_by_active_sequences,
            },
        }
