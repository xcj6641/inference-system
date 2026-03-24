import asyncio

from app.models import GenerationRequest


class FakeModelEngine:
    async def prefill(self, req: GenerationRequest) -> None:
        # Simulate prompt processing cost
        await asyncio.sleep(0.05)
        req.prefill_done = True

    async def decode_step(self, active_reqs: list[GenerationRequest]) -> list[tuple[str, str]]:
        # Simulate one shared decode iteration
        await asyncio.sleep(0.05)

        decoded = []
        for req in active_reqs:
            next_token = f"tok{len(req.generated_tokens) + 1}"
            req.generated_tokens.append(next_token)
            decoded.append((req.request_id, next_token))
        return decoded