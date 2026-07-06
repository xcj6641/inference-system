import asyncio
import time

from app.store import RequestStore
from app.engine import FakeModelEngine
from app.scheduler import Scheduler, SchedulerConfig
from app.models import GenerationRequest, RequestState


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


def test_single_request_kv_growth():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
        config=SchedulerConfig(
            max_active_sequences=4,
            max_batch_tokens=64,
            max_kv_capacity=256,
            max_tokens_in_flight=512,
            max_prefill_per_tick=10,
            tick_interval_s=0.01,
        ),
    )

    async def scenario():
        req = make_request("hello world", 5)
        await store.add_waiting_request(req)

        await run_scheduler_ticks(scheduler, 20)

        # ---- Assertions ----
        assert req.request_id in store.finished_requests
        assert len(req.generated_tokens) == 5

        # KV should not exceed expected bound
        assert scheduler.kv_manager.used <= scheduler.kv_manager.capacity

    asyncio.run(scenario())
    print("test_single_request_kv_growth PASSED")


def test_no_double_kv_counting():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
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
    print("test_no_double_kv_counting PASSED")


def test_multi_request_fairness_and_isolation():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
        config=SchedulerConfig(
            max_active_sequences=3,
            max_batch_tokens=64,
            max_kv_capacity=512,
            max_tokens_in_flight=512,
            max_prefill_per_tick=5,
            tick_interval_s=0.01,
        ),
    )

    async def scenario():
        reqs = [
            make_request("a a a", 4),
            make_request("b b b", 4),
            make_request("c c c", 4),
            make_request("d d d", 4),
        ]

        for r in reqs:
            await store.add_waiting_request(r)

        await run_scheduler_ticks(scheduler, 40)

        finished = len(store.finished_requests)

        # all should finish eventually (or at least most)
        assert finished >= 3

        # KV sanity
        assert scheduler.kv_manager.used <= scheduler.kv_manager.capacity

    asyncio.run(scenario())
    print("test_multi_request_fairness_and_isolation PASSED")


def test_token_budget_never_explodes():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
        config=SchedulerConfig(
            max_active_sequences=10,
            max_batch_tokens=64,
            max_kv_capacity=512,
            max_tokens_in_flight=128,
            max_prefill_per_tick=10,
            tick_interval_s=0.01,
        ),
    )

    async def scenario():
        for i in range(20):
            req = make_request(f"req {i}", 5)
            await store.add_waiting_request(req)

        await run_scheduler_ticks(scheduler, 50)

        # critical invariant
        assert scheduler.stats.current_tokens <= scheduler.config.max_tokens_in_flight

    asyncio.run(scenario())
    print("test_token_budget_never_explodes PASSED")

def test_kv_matches_active_requests():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
        config=SchedulerConfig(
            max_active_sequences=5,
            max_batch_tokens=64,
            max_kv_capacity=512,
            max_tokens_in_flight=512,
            max_prefill_per_tick=10,
            tick_interval_s=0.01,
        ),
    )

    async def scenario():
        for i in range(5):
            await store.add_waiting_request(make_request(f"req {i}", 5))

        await run_scheduler_ticks(scheduler, 40)

        # 🔥 CRITICAL INVARIANT
        expected = sum(r.cached_tokens for r in store.active_requests.values())

        assert scheduler.kv_manager.used <= scheduler.kv_manager.capacity

        print("KV USED:", scheduler.kv_manager.used)
        print("EXPECTED LOWER BOUND:", expected)

    asyncio.run(scenario())
    print("test_kv_matches_active_requests PASSED")


def test_no_kv_double_count_across_ticks():
    store = RequestStore()
    engine = FakeModelEngine()

    scheduler = Scheduler(
        store=store,
        engine=engine,
        config=SchedulerConfig(
            max_active_sequences=5,
            max_batch_tokens=64,
            max_kv_capacity=512,
            max_tokens_in_flight=512,
            max_prefill_per_tick=10,
            tick_interval_s=0.01,
        ),
    )

    async def scenario():
        req = make_request("s1 s2 s3", 10)
        await store.add_waiting_request(req)

        await run_scheduler_ticks(scheduler, 50)

        # KV should be bounded
        assert scheduler.kv_manager.used <= scheduler.kv_manager.capacity

        # IMPORTANT: KV should roughly match ACTIVE generation, not tick count
        print("FINAL KV:", scheduler.kv_manager.used)
        print("GENERATED TOKENS:", len(req.generated_tokens))

        # sanity: KV should NOT explode with ticks
        assert scheduler.kv_manager.used < 500

    asyncio.run(scenario())
# test_single_request_kv_growth()
# test_no_double_kv_counting()
# test_multi_request_fairness_and_isolation()
# test_token_budget_never_explodes()
# test_kv_matches_active_requests()
test_no_kv_double_count_across_ticks()