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
        max_tokens_in_flight: int = 20,
        max_prefill_per_tick: int = 4,
        tick_interval_s: float = 0.1,
    ) -> None:
        if max_prefill_per_tick < 0:
            raise ValueError("max_prefill_per_tick must be >= 0")
        self.store = store
        self.engine = engine
        if max_tokens_in_flight < 1:
            raise ValueError("max_tokens_in_flight must be >= 1")
        self.max_tokens_in_flight = max_tokens_in_flight
        self.current_tokens_in_flight = 0

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

    @staticmethod
    def _estimate_needed_tokens(req: GenerationRequest) -> int:
        """Estimated total tokens for this request (prefill + decode budget)."""
        if req.reserved_tokens > 0:
            return req.reserved_tokens
        return max(0, req.prompt_tokens) + req.max_new_tokens

    def _fmt_tokens_in_flight(self) -> str:
        return f"{self.current_tokens_in_flight}/{self.max_tokens_in_flight}"

    async def _run_one_tick(self) -> None:
        admitted_ids = []
        prefill_ids = []
        decode_results = []
        finished_ids = []

        # Step 1: admit from waiting queue while token budget allows
        async with self.store.lock:
            while self.store.waiting_queue:
                # fairness issue: head-of-line blocking if the head request is too large to admit, it will block all other requests behind it. In practice, this may not be a big issue since we expect most requests to be small (e.g., < 100 tokens), but it's something to keep in mind. 
                # Possible solution: look beyond the head of the queue for requests that fit in the token budget, but this adds complexity and may cause starvation of large requests.
                peek = self.store.waiting_queue[0]
                needed = self._estimate_needed_tokens(peek)
                if self.current_tokens_in_flight + needed > self.max_tokens_in_flight:
                    self.logger.info(
                        "[admission_blocked] head_request_id=%s prompt_tokens=%d "
                        "reserved_tokens=%d needed_tokens=%d tokens_in_flight=%s",
                        peek.request_id,
                        peek.prompt_tokens,
                        peek.reserved_tokens,
                        needed,
                        self._fmt_tokens_in_flight(),
                    )
                    break
                req = self.store.waiting_queue.popleft()
                if req.reserved_tokens <= 0:
                    req.reserved_tokens = needed
                self.current_tokens_in_flight += needed
                req.state = RequestState.PREFILL
                req.admitted_time = time.time()
                # req.queue_wait_ms = (req.admitted_time - req.arrival_time) * 1000
                self.store.active_requests[req.request_id] = req
                admitted_ids.append(req.request_id)
                self.logger.info(
                    "[admit] request_id=%s prompt_tokens=%d reserved_tokens=%d "
                    "tokens_in_flight=%s",
                    req.request_id,
                    req.prompt_tokens,
                    req.reserved_tokens,
                    self._fmt_tokens_in_flight(),
                )

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
            await self.engine.prefill(req)
            req.prefill_end_time = time.time()
            req.prefill_done = True
            req.state = RequestState.DECODE
            prefill_ids.append(req.request_id)

        # Step 4: one shared decode step only for the decode snapshot (not this tick's new DECODE)
        active_before_finish = [req.request_id for req in decode_targets]

        if decode_targets:
            decode_results = await self.engine.decode_step(decode_targets)

        # Step 5: finish requests that hit max_new_tokens
        async with self.store.lock:
            to_finish = []
            for req in self.store.active_requests.values():
                if len(req.generated_tokens) >= req.max_new_tokens:
                    req.state = RequestState.FINISHED
                    req.finished_time = time.time()

                    self.current_tokens_in_flight -= req.reserved_tokens
                    if self.current_tokens_in_flight < 0:
                        self.current_tokens_in_flight = 0

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
                f"prompt_tokens={req.prompt_tokens} reserved_tokens={req.reserved_tokens} "
                f"max_new_tokens={req.max_new_tokens} "
                f"generated_tokens={len(req.generated_tokens)} "
                f"queue_wait_ms={self._fmt_ms(req.queue_wait_ms)} "
                f"prefill_wait_ms={self._fmt_ms(req.prefill_wait_ms)} "
                f"prefill_ms={self._fmt_ms(req.prefill_duration_ms)} "
                f"ttft_ms={self._fmt_ms(req.time_to_first_token_ms)} "
                f"decode_tail_ms={self._fmt_ms(req.decode_tail_ms)} "
                f"service_time_ms={self._fmt_ms(req.service_time_ms)} "
                f"total_latency_ms={self._fmt_ms(req.total_latency_ms)} "
                f"tokens_in_flight={self._fmt_tokens_in_flight()}"
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
            f"tokens_in_flight={self._fmt_tokens_in_flight()} "
            f"admit={admit_str} "
            f"active_before_finish={active_before_finish_str} "
            f"prefill_batch_size={prefill_batch_size} "
            f"prefill_done={prefill_str} "
            f"decode_batch_size={decode_batch_size} "
            f"decode={decode_str} "
            f"finish={finish_str} "
            f"active_after_finish={active_after_finish_str}"
        )