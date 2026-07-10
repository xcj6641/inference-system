import asyncio
import time
from dataclasses import dataclass
from typing import List

from app.models import RequestState, GenerationRequest, END_OF_STREAM
from app.store import RequestStore
from app.engine import ModelEngine

from app.logger_config import setup_logger


@dataclass(frozen=True)
class SchedulerConfig:
    max_active_sequences: int
    max_batch_tokens: int
    max_kv_capacity: int
    kv_block_size: int = 16

    max_tokens_in_flight: int = 20
    max_prefill_per_tick: int = 4
    tick_interval_s: float = 0.1
    log_empty_ticks: bool = False

    def __post_init__(self) -> None:
        if self.max_tokens_in_flight < 1:
            raise ValueError("max_tokens_in_flight must be >= 1")
        if self.max_prefill_per_tick < 0:
            raise ValueError("max_prefill_per_tick must be >= 0")
        if self.tick_interval_s <= 0:
            raise ValueError("tick_interval_s must be > 0")


@dataclass
class SchedulerStats:
    current_tokens: int = 0
    admission_blocked_ticks: int = 0
    blocked_by_active_sequences: int = 0
    blocked_by_token_budget: int = 0
    blocked_by_kv_capacity: int = 0
    admitted_requests: int = 0
    completed_requests: int = 0

    @property
    def active_sequences(self):
        return len(self.store.active_requests)


class KVMemoryManager:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.used = 0
        self.decode_reserved = 0

    @property
    def available(self) -> int:
        return self.capacity - self.used

    @property
    def allocatable(self) -> int:
        allocatable = self.capacity - self.used - self.decode_reserved
        return max(0, allocatable)

    def allocate_admission(self, prompt_tokens: int) -> None:
        self.used += prompt_tokens

    def allocate_decode_growth(self, decode_tokens: int) -> None:
        self.used += decode_tokens

    def free_request(self, cached_tokens: int) -> None:
        self.used -= cached_tokens

    def reset_used(self) -> None:
        self.used = 0

    def reserve_decode(self, num_sequences: int) -> None:
        self.decode_reserved = min(num_sequences, self.available)

    def build_decode_batch(self, active_requests: List[GenerationRequest]) -> List[GenerationRequest]:
        return active_requests[:self.decode_reserved]

    # def reserve_and_build_decode_batch(self, active_requests: List[GenerationRequest]) -> List[GenerationRequest]:
    #     self.decode_reserved = min(len(active_requests), self.available)
    #     return active_requests[:self.decode_reserved]

    def release_decode_reserved(self) -> None:
        self.decode_reserved = 0

    def fmt_kv_usage(self) -> str:
        return f"{self.used}/{self.capacity}"

    @property
    def utilization(self) -> float:
        return 0.0 if self.capacity == 0 else self.used / self.capacity

    def display_info(self) -> str:
        return f"capacity:{self.capacity}, used:{self.used}, decode_reserved:{self.decode_reserved}"
class Scheduler:
    def __init__(
        self,
        store: RequestStore,
        engine: ModelEngine,
        config: SchedulerConfig | None = None,
    ) -> None:
        self.store = store
        self.engine = engine

        if config is None:
            raise ValueError("SchedulerConfig must be provided")
        self.config = config

        self.stats = SchedulerStats()
        self.kv_manager = KVMemoryManager(config.max_kv_capacity)

        self.tick = 0
        self.logger = setup_logger()

    async def run_forever(self) -> None:
        while True:
            self.tick += 1
            await self._run_one_tick()
            await asyncio.sleep(self.config.tick_interval_s)

    @staticmethod
    def _estimate_needed_tokens(req: GenerationRequest) -> int:
        """Estimated total tokens for this request (prefill + decode budget)."""
        if req.reserved_tokens > 0:
            return req.reserved_tokens
        return max(0, req.prompt_tokens) + req.max_new_tokens

    def _fmt_tokens_in_flight(self) -> str:
        return f"{self.stats.current_tokens}/{self.config.max_tokens_in_flight}"

    def get_admission_block_reason(self, req: GenerationRequest) -> str | None:
        needed = self._estimate_needed_tokens(req)

        if len(self.store.active_requests) >= self.config.max_active_sequences:
            return "active_sequences"

        if self.stats.current_tokens + needed > self.config.max_tokens_in_flight:
            return "token_budget"

        if req.prompt_tokens > self.kv_manager.allocatable:
            return "kv_capacity"

        return None

    async def _run_one_tick(self) -> None:
        admitted_ids = []
        prefill_ids = []
        decode_results = []
        finished_ids = []

        # Invariant:
        # All requests in active_requests have completed prefill.
        # Therefore active_sequences == decode_candidates.
        async with self.store.lock:
            decode_snapshot = list(self.store.active_requests.values())

        self.kv_manager.reserve_decode(len(decode_snapshot))
        decode_targets = self.kv_manager.build_decode_batch(decode_snapshot)
        # decode_targets = self.kv_manager.reserve_and_build_decode_batch(active_snapshot)

        # Step 1: admit from waiting queue while token budget allows
        async with self.store.lock:
            while self.store.waiting_queue:

                self.logger.info(
                            "[tick start] kv: %s",
                            self.kv_manager.display_info(),)
                # fairness issue: head-of-line blocking if the head request is too large to admit, it will block all other requests behind it. In practice, this may not be a big issue since we expect most requests to be small (e.g., < 100 tokens), but it's something to keep in mind. 
                # Possible solution: look beyond the head of the queue for requests that fit in the token budget, but this adds complexity and may cause starvation of large requests.
                peek = self.store.waiting_queue[0]
                needed = self._estimate_needed_tokens(peek)

                block_reason = self.get_admission_block_reason(peek)
                if block_reason is not None:
                    self.stats.admission_blocked_ticks += 1
                    if block_reason == "active_sequences":
                        self.stats.blocked_by_active_sequences += 1
                    elif block_reason == "token_budget":
                        self.stats.blocked_by_token_budget += 1
                    elif block_reason == "kv_capacity":
                        self.stats.blocked_by_kv_capacity += 1

                    self.logger.info(
                        "[admission_blocked] reason=%s head_request_id=%s prompt_tokens=%d "
                        "req_reserved_tokens=%d needed_tokens=%d "
                        "tokens_in_flight=%s kv_usage=%s active_sequences=%d/%d",
                        block_reason,
                        peek.request_id,
                        peek.prompt_tokens,
                        peek.reserved_tokens,
                        needed,
                        self._fmt_tokens_in_flight(),
                        self.kv_manager.fmt_kv_usage(),
                        len(self.store.active_requests),
                        self.config.max_active_sequences,
                    )
                    break

                req = self.store.waiting_queue.popleft()
                if req.reserved_tokens <= 0:
                    req.reserved_tokens = needed
                self.stats.current_tokens += needed

                req.update_kv_usage(self.config.kv_block_size)
                self.kv_manager.allocate_admission(req.cached_tokens)

                req.state = RequestState.PREFILL
                req.admitted_time = time.time()
                # req.queue_wait_ms = (req.admitted_time - req.arrival_time) * 1000
                self.store.active_requests[req.request_id] = req
                self.stats.admitted_requests += 1
                # self.stats.active_sequences += 1
                admitted_ids.append(req.request_id)
                self.logger.info(
                    "[admit] request_id=%s prompt_tokens=%d req_reserved_tokens=%d "
                    "tokens_in_flight=%s kv_usage=%s kv_blocks_used=%d",
                    req.request_id,
                    req.prompt_tokens,
                    req.reserved_tokens,
                    self._fmt_tokens_in_flight(),
                    self.kv_manager.fmt_kv_usage(),
                    req.kv_blocks_used,
                )

        # This active_requests contains prefill status request (newly admission requests)
        async with self.store.lock:
            active_snapshot = list(self.store.active_requests.values())

        # Step 2: snapshot decode-phase requests (before prefill moves PREFILL -> DECODE)
        # decode_candidates: List[GenerationRequest] = [
        #     req for req in active_snapshot
        #     if req.state == RequestState.DECODE
        # ]
        #decode_budget = min(len(decode_candidates), available_growth)
        # decode_targets = decode_candidates[:self.kv_manager.decode_reserved]
        # decode_targets = self.kv_manager.select_decode_batch(decode_candidates)
        # self.kv_manager.decode_reserved = len(decode_targets)

        # Step 3: prefill active requests still in PREFILL (at most max_prefill_per_tick per tick)
        prefill_targets: List[GenerationRequest] = [
            req for req in active_snapshot
            if req.state == RequestState.PREFILL and not req.prefill_done
        ][: self.config.max_prefill_per_tick]

        for req in prefill_targets:
            req.prefill_start_time = time.time()
            await self.engine.prefill(req)
            req.prefill_end_time = time.time()
            req.prefill_done = True
            req.state = RequestState.DECODE
            prefill_ids.append(req.request_id)

        # Step 4: Decode: one shared decode step only for the decode snapshot (not this tick's new DECODE)
        active_before_finish = [req.request_id for req in decode_targets]

        if decode_targets:
            try:
                decode_results = await self.engine.decode_step(decode_targets)
                async with self.store.lock:
                    # for req in decode_targets:
                    for req_id, token, finished in decode_results:
                        req = self.store.active_requests.get(req_id)
                        if req is None:
                            continue

                        #public token to stream
                        req.generated_tokens.append(token)
                        await req.token_stream.put(token)

                        req.update_kv_usage(self.config.kv_block_size)

                        if finished:
                            req.state = RequestState.FINISHED
                            
                    self.kv_manager.allocate_decode_growth(len(decode_results))
            finally:
                self.kv_manager.release_decode_reserved()

        # Step 5: finish requests that hit max_new_tokens
        async with self.store.lock:
            to_finish = []
            for req in self.store.active_requests.values():
                if len(req.generated_tokens) >= req.max_new_tokens or req.state == RequestState.FINISHED:
                    req.state = RequestState.FINISHED
                    req.finished_time = time.time()
                    await req.token_stream.put(END_OF_STREAM)

                    self.stats.current_tokens -= req.reserved_tokens
                    if self.stats.current_tokens < 0:
                        self.stats.current_tokens = 0

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
                # self.kv_manager.used -= req.cached_tokens
                self.kv_manager.free_request(req.cached_tokens)
                self.stats.completed_requests += 1
                # self.stats.active_sequences -= 1
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
                f"prompt_tokens={req.prompt_tokens} req_reserved_tokens={req.reserved_tokens} "
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
        decode_results: list[tuple[str, str, bool]],
        finished_ids: list[str],
        active_before_finish: list[str],
        active_after_finish: list[str],
    ) -> None:
        has_event = bool(admitted_ids or prefill_ids or decode_results or finished_ids)

        if not has_event and not self.config.log_empty_ticks:
            return

        decode_str = " ".join([f"{rid}->{tok}" for rid, tok, _ in decode_results]) or "none"
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
            f"kv_usage={self.kv_manager.fmt_kv_usage()} "
            f"admit={admit_str} "
            f"active_before_finish={active_before_finish_str} "
            f"prefill_batch_size={prefill_batch_size} "
            f"prefill_done={prefill_str} "
            f"decode_batch_size={decode_batch_size} "
            f"decode={decode_str} "
            f"finish={finish_str} "
            f"active_after_finish={active_after_finish_str}"
        )
