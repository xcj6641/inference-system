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
        max_prefill_per_tick: int = 4,
        tick_interval_s: float = 0.1,
    ) -> None:
        if max_prefill_per_tick < 0:
            raise ValueError("max_prefill_per_tick must be >= 0")
        self.store = store
        self.engine = engine
        self.max_active_requests = max_active_requests
        self.max_prefill_per_tick = max_prefill_per_tick
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

        # Step 2: snapshot decode-phase requests (before prefill moves PREFILL -> DECODE)
        decode_targets: List[GenerationRequest] = [
            req for req in active_snapshot
            if req.state == RequestState.DECODE
        ]

        # Step 3: prefill active requests still in PREFILL (at most max_prefill_per_tick per tick)
        prefill_targets: List[GenerationRequest] = [
            req for req in active_snapshot
            if req.state == RequestState.PREFILL and not req.prefill_done
        ][: self.max_prefill_per_tick]

        for req in prefill_targets:
            req.prefill_start_time = time.time()
            if req.admitted_time is not None:
                req.prefill_wait_ms = (req.prefill_start_time - req.admitted_time) * 1000
            await self.engine.prefill(req)
            req.prefill_end_time = time.time()
            req.prefill_duration_ms = (req.prefill_end_time - req.prefill_start_time) * 1000
            req.prefill_done = True
            req.state = RequestState.DECODE
            prefill_ids.append(req.request_id)

        # Step 4: one shared decode step only for the decode snapshot (not this tick's new DECODE)
        active_before_finish = [req.request_id for req in decode_targets]

        if decode_targets:
            decode_results = await self.engine.decode_step(decode_targets)
            decode_done_time = time.time()
            decoded_request_ids = {request_id for request_id, _token in decode_results}
            for req in decode_targets:
                if req.request_id in decoded_request_ids and req.first_decode_time is None:
                    req.first_decode_time = decode_done_time
                    req.time_to_first_token_ms = (req.first_decode_time - req.arrival_time) * 1000

        # Step 5: finish requests that hit max_new_tokens
        async with self.store.lock:
            to_finish = []
            for req in self.store.active_requests.values():
                if len(req.generated_tokens) >= req.max_new_tokens:
                    req.state = RequestState.FINISHED
                    req.finished_time = time.time()
                    req.total_latency_ms = (req.finished_time - req.arrival_time) * 1000

                    if req.admitted_time is not None:
                        req.queue_wait_ms = (req.admitted_time - req.arrival_time) * 1000

                    if req.prefill_start_time is not None and req.admitted_time is not None:
                        req.prefill_wait_ms = (req.prefill_start_time - req.admitted_time) * 1000

                    if req.prefill_end_time is not None and req.prefill_start_time is not None:
                        req.prefill_duration_ms = (
                            req.prefill_end_time - req.prefill_start_time
                        ) * 1000

                    if req.first_decode_time is not None:
                        req.time_to_first_token_ms = (req.first_decode_time - req.arrival_time) * 1000
                        req.decode_tail_ms = (
                            req.finished_time - req.first_decode_time
                        ) * 1000

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
                f"queue_wait_ms={self._fmt_ms(req.queue_wait_ms)} "
                f"prefill_wait_ms={self._fmt_ms(req.prefill_wait_ms)} "
                f"prefill_ms={self._fmt_ms(req.prefill_duration_ms)} "
                f"ttft_ms={self._fmt_ms(req.time_to_first_token_ms)} "
                f"decode_tail_ms={self._fmt_ms(req.decode_tail_ms)} "
                f"service_time_ms={self._fmt_ms(req.service_time_ms)} "
                f"total_latency_ms={self._fmt_ms(req.total_latency_ms)}"
            )

    @staticmethod
    def _fmt_ms(value: float | None) -> str:
        return "none" if value is None else f"{value:.1f}"

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
        prefill_batch_size = len(prefill_ids)
        decode_batch_size = len(decode_results)

        self.logger.info(
            f"[tick={self.tick}] "
            f"waiting={waiting_size} "
            f"admit={admit_str} "
            f"active_before_finish={active_before_finish_str} "
            f"prefill_batch_size={prefill_batch_size} "
            f"prefill_done={prefill_str} "
            f"decode_batch_size={decode_batch_size} "
            f"decode={decode_str} "
            f"finish={finish_str} "
            f"active_after_finish={active_after_finish_str}"
        )