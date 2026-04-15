import asyncio
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.models import GenerationRequest
from app.store import RequestStore
from app.engine import FakeModelEngine
from app.scheduler import Scheduler
from app.logger_config import setup_logger


app = FastAPI()

store = RequestStore()
engine = FakeModelEngine()
scheduler = Scheduler(
    store=store,
    engine=engine,
    max_tokens_in_flight=64,
    max_prefill_per_tick=3,
    tick_interval_s=0.1,
)
logger = setup_logger()


class GenerateRequest(BaseModel):
    prompt: str
    max_new_tokens: int = Field(default=5, ge=1, le=50)


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(scheduler.run_forever())

def estimate_prompt_tokens(prompt: str) -> int:
    # 简单 mock：按空格切
    # 如果你想更稳定一点，也可以 max(1, len(prompt.split()))
    return max(1, len(prompt.split()))

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

    await store.add_waiting_request(gen_req)

    logger.info(
        f"[submit] request_id={request_id} prompt={req.prompt!r} "
        f"prompt_tokens={gen_req.prompt_tokens} reserved_tokens={gen_req.reserved_tokens} "
        f"max_new_tokens={req.max_new_tokens} state={gen_req.state}"
    )

    return {
        "request_id": request_id,
        "state": gen_req.state,
    }


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
            "max_tokens_in_flight": scheduler.max_tokens_in_flight,
            "current_tokens_in_flight": scheduler.current_tokens_in_flight,
            "max_prefill_per_tick": scheduler.max_prefill_per_tick,
            "waiting_queue_size": len(store.waiting_queue),
            "active_request_ids": list(store.active_requests.keys()),
            "finished_request_ids": list(store.finished_requests.keys()),
            "all_request_ids": list(store.all_requests.keys()),
        }