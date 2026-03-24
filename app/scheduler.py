import asyncio
import time
from typing import List

from app.models import RequestState, GenerationRequest
from app.store import RequestStore
from app.engine import FakeModelEngine

from app.logger_config import setup_logger


class Scheduler:
    def __init__(
        self,
        store: RequestStore,
        engine: FakeModelEngine,
        max_active_requests: int = 4,
        tick_interval_s: float = 0.1,
    ) -> None:
        self.store = store
        self.engine = engine
        self.max_active_requests = max_active_requests
        self.tick_interval_s = tick_interval_s
        self.tick = 0
        self.logger = setup_logger()
        self.log_empty_ticks = False

    async def run_forever(self) -> None:
        while True:
            self.tick += 1
            await self._run_one_tick()
            await asyncio.sleep(self.tick_interval_s)

    async def _run_one_tick(self) -> None:
        admitted_ids = []
        prefill_ids = []
        decode_results = []
        finished_ids = []

        # Step 1: admit from waiting queue into active set
        async with self.store.lock:
            while (
                len(self.store.active_requests) < self.max_active_requests
                and self.store.waiting_queue
            ):
                req = self.store.waiting_queue.popleft()
                req.state = RequestState.PREFILL
                req.admitted_time = time.time()
                req.queue_wait_ms = (req.admitted_time - req.arrival_time) * 1000
                self.store.active_requests[req.request_id] = req
                admitted_ids.append(req.request_id)

            active_snapshot = list(self.store.active_requests.values())

        # Step 2: prefill all requests not prefetched yet
        prefill_targets: List[GenerationRequest] = [
            req for req in active_snapshot
            if req.state == RequestState.PREFILL and not req.prefill_done
        ]

        for req in prefill_targets:
            await self.engine.prefill(req)
            req.state = RequestState.DECODE
            prefill_ids.append(req.request_id)

        # Step 3: one shared decode step for all decode-ready requests
        async with self.store.lock:
            decode_targets = [
                req for req in self.store.active_requests.values()
                if req.state == RequestState.DECODE
            ]
            active_before_finish = [req.request_id for req in decode_targets]

        if decode_targets:
            decode_results = await self.engine.decode_step(decode_targets)

        # Step 4: finish requests that hit max_new_tokens
        async with self.store.lock:
            to_finish = []
            for req in self.store.active_requests.values():
                if len(req.generated_tokens) >= req.max_new_tokens:
                    req.state = RequestState.FINISHED
                    # Mark finished time and calculate latencies
                    req.finished_time = time.time()
                    req.total_latency_ms = (req.finished_time - req.arrival_time) * 1000
                    if req.queue_wait_ms is not None:
                        req.service_time_ms = req.total_latency_ms - req.queue_wait_ms
                    to_finish.append(req.request_id)

            # for logging after releasing the lock
            completed_requests = []
            for request_id in to_finish:
                req = self.store.active_requests.pop(request_id)
                self.store.finished_requests[request_id] = req
                finished_ids.append(request_id)
                completed_requests.append(req)

            waiting_size = len(self.store.waiting_queue)
            active_after_finish = list(self.store.active_requests.keys())


        self._log_tick(
            waiting_size=waiting_size,
            admitted_ids=admitted_ids,
            prefill_ids=prefill_ids,
            decode_results=decode_results,
            finished_ids=finished_ids,
            active_before_finish=active_before_finish,
            active_after_finish=active_after_finish,
        )

        for req in completed_requests:
            self.logger.info(
                f"[complete] request_id={req.request_id} "
                f"prompt={req.prompt!r} "
                f"max_new_tokens={req.max_new_tokens} "
                f"generated_tokens={len(req.generated_tokens)} "
                f"queue_wait_ms={req.queue_wait_ms:.1f} "
                f"service_time_ms={req.service_time_ms:.1f} "
                f"total_latency_ms={req.total_latency_ms:.1f}"
            )

    def _log_tick(
        self,
        waiting_size: int,
        admitted_ids: list[str],
        prefill_ids: list[str],
        decode_results: list[tuple[str, str]],
        finished_ids: list[str],
        active_before_finish: list[str],
        active_after_finish: list[str],
    ) -> None:
        has_event = bool(admitted_ids or prefill_ids or decode_results or finished_ids)

        if not has_event and not self.log_empty_ticks:
            return

        decode_str = " ".join([f"{rid}->{tok}" for rid, tok in decode_results]) or "none"
        admit_str = ",".join(admitted_ids) or "none"
        prefill_str = ",".join(prefill_ids) or "none"
        finish_str = ",".join(finished_ids) or "none"
        active_before_finish_str = ",".join(active_before_finish) or "none"
        active_after_finish_str = ",".join(active_after_finish) or "none"
        decode_batch_size = len(decode_results)

        self.logger.info(
            f"[tick={self.tick}] "
            f"waiting={waiting_size} "
            f"admit={admit_str} "
            f"active_before_finish={active_before_finish_str} "
            f"prefill_done={prefill_str} "
            f"decode_batch_size={decode_batch_size} "
            f"decode={decode_str} "
            f"finish={finish_str} "
            f"active_after_finish={active_after_finish_str}"
        )