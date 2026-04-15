from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import time


class RequestState(str, Enum):
    WAITING = "WAITING"
    PREFILL = "PREFILL"
    DECODE = "DECODE"
    FINISHED = "FINISHED"


@dataclass
class GenerationRequest:
    request_id: str
    prompt: str
    max_new_tokens: int
    generated_tokens: list[str] = field(default_factory=list)
    state: RequestState = RequestState.WAITING

    prompt_tokens: int = 0

    # token reservation for admission budget (prompt + max_new_to_generate, estimated)
    reserved_tokens: int = 0

    arrival_time: float = field(default_factory=time.time)
    admitted_time: Optional[float] = None
    prefill_start_time: Optional[float] = None
    prefill_end_time: Optional[float] = None
    first_decode_time: Optional[float] = None
    finished_time: Optional[float] = None
    prefill_done: bool = False
    queue_wait_ms: float | None = None
    prefill_wait_ms: float | None = None
    prefill_duration_ms: float | None = None
    time_to_first_token_ms: float | None = None
    decode_tail_ms: float | None = None
    total_latency_ms: float | None = None
    service_time_ms: Optional[float] = None