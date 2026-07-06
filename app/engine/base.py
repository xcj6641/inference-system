from abc import ABC, abstractmethod
from typing import Sequence

from app.models import GenerationRequest


class ModelEngine(ABC):

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

    @abstractmethod
    async def prefill(
        self,
        request: GenerationRequest,
    ) -> None:
        """
        Execute the prefill phase.

        Side effect:
            Build the request's KV cache.
        """
        raise NotImplementedError

    @abstractmethod
    async def decode_step(
        self,
        requests: Sequence[GenerationRequest],
    ) -> list[tuple[str, str]]:
        """
        Decode exactly one token for each request.
        """
        raise NotImplementedError