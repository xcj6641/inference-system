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
    arrival_time: float = field(default_factory=time.time)
    admitted_time: Optional[float] = None
    finished_time: Optional[float] = None
    prefill_done: bool = False
    queue_wait_ms: float | None = None
    total_latency_ms: float | None = None
    service_time_ms: Optional[float] = None