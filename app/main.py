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
    max_active_requests=3,
    tick_interval_s=0.1,
)
logger = setup_logger()


class GenerateRequest(BaseModel):
    prompt: str
    max_new_tokens: int = Field(default=5, ge=1, le=50)


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(scheduler.run_forever())


@app.post("/generate")
async def generate(req: GenerateRequest):
    request_id = str(uuid.uuid4())[:8]
    gen_req = GenerationRequest(
        request_id=request_id,
        prompt=req.prompt,
        max_new_tokens=req.max_new_tokens,
    )
    await store.add_waiting_request(gen_req)

    logger.info(
        f"[submit] request_id={request_id} prompt={req.prompt!r} "
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
        "finished_time": req.finished_time,
        "queue_wait_ms": req.queue_wait_ms,
        "total_latency_ms": req.total_latency_ms,
        "service_time_ms": req.service_time_ms,
    }


@app.get("/scheduler/debug")
async def scheduler_debug():
    async with store.lock:
        return {
            "tick": scheduler.tick,
            "waiting_queue_size": len(store.waiting_queue),
            "active_request_ids": list(store.active_requests.keys()),
            "finished_request_ids": list(store.finished_requests.keys()),
            "all_request_ids": list(store.all_requests.keys()),
        }