import asyncio
import time

from app.models import GenerationRequest
from .base import ModelEngine

PREFILL_COST_PER_TOKEN = 0.002   # 2ms / token
MIN_PREFILL_COST = 0.005         # optional

DECODE_COST_PER_SEQ = 0.2   # 3ms / active seq / decode round
MIN_DECODE_COST = 0.002

class FakeEngine(ModelEngine):

    @property
    def backend_name(self):
        return "fake"

    async def prefill(self, req: GenerationRequest) -> None:
        prefill_cost = max(MIN_PREFILL_COST, req.prompt_tokens * PREFILL_COST_PER_TOKEN)
        await asyncio.sleep(prefill_cost)

    async def decode_step(
        self, decode_targets: list[GenerationRequest]
    ) -> list[tuple[str, str, bool]]:
        if not decode_targets:
            return []

        decode_cost = max(MIN_DECODE_COST, len(decode_targets) * DECODE_COST_PER_SEQ)
        await asyncio.sleep(decode_cost)

        decode_results: list[tuple[str, str, bool]] = []
        decode_done_time = time.time()
        for req in decode_targets:
            next_token = f"tok{len(req.generated_tokens) + 1}"
            # req.generated_tokens.append(next_token)
            # await req.token_stream.put(token)

            if req.first_decode_time is None:
                req.first_decode_time = decode_done_time

            finished = len(req.generated_tokens) + 1 >= req.max_new_tokens
            decode_results.append((req.request_id, next_token, finished))
        return decode_results
