
from .base import ModelEngine

class SpyEngine(ModelEngine):

    def __init__(self):

        self.prefill_called = 0
        self.decode_called = 0

    @property
    def backend_name(self):
        return "spy"

    async def prefill(self, req):

        self.prefill_called += 1

    async def decode_step(self, reqs):

        self.decode_called += 1

        return []