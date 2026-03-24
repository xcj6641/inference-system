import asyncio
from collections import deque
from typing import Dict, Deque

from app.models import GenerationRequest


class RequestStore:
    def __init__(self) -> None:
        self.waiting_queue: Deque[GenerationRequest] = deque()
        self.active_requests: Dict[str, GenerationRequest] = {}
        self.finished_requests: Dict[str, GenerationRequest] = {}
        self.all_requests: Dict[str, GenerationRequest] = {}
        self.lock = asyncio.Lock()

    async def add_waiting_request(self, req: GenerationRequest) -> None:
        async with self.lock:
            self.waiting_queue.append(req)
            self.all_requests[req.request_id] = req

    async def get_request(self, request_id: str) -> GenerationRequest | None:
        async with self.lock:
            return self.all_requests.get(request_id)