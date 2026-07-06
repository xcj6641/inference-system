import asyncio
import time

from app.store import RequestStore
from app.engine import DummyEngine
from app.scheduler import Scheduler, SchedulerConfig
from app.models import GenerationRequest, RequestState
from app.engine import factory

def make_request(prompt: str, max_new_tokens: int):
    req = GenerationRequest(
        request_id=prompt,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
    )
    req.prompt_tokens = max(1, len(prompt.split()))
    req.reserved_tokens = req.prompt_tokens + max_new_tokens
    return req

async def run_scheduler_ticks(scheduler: Scheduler, ticks: int = 20):
    """Run scheduler manually instead of FastAPI loop."""
    for _ in range(ticks):
        await scheduler._run_one_tick()
        await asyncio.sleep(0.01)

def test_dummy_engine():
    store = RequestStore()
    engine = factory.create_engine("dummy")

    print("=" * 40)
    print("LLM Inference Gateway")
    print("=" * 40)
    print(f"Backend: {engine.backend_name}")
    print("=" * 40)

    scheduler = Scheduler(
        store,
        engine,
        config=SchedulerConfig(
                max_active_sequences=4,
                max_batch_tokens=64,
                max_kv_capacity=512,
                max_tokens_in_flight=512,
                max_prefill_per_tick=10,
                tick_interval_s=0.01,
            ),
    )

    async def scenario():
        req = make_request("s1 s2 s3", 8)
        await store.add_waiting_request(req)

        await run_scheduler_ticks(scheduler, 30)

        # KV sanity check
        assert scheduler.kv_manager.used <= scheduler.kv_manager.capacity

        # critical debug: KV must be monotonic increasing then stable
        print("KV USED:", scheduler.kv_manager.used)

    asyncio.run(scenario())
    print("test_dummy_engine")


test_dummy_engine()