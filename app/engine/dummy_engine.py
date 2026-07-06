
from .base import ModelEngine

class DummyEngine(ModelEngine):

    @property
    def backend_name(self):
        return "Dummy"

    async def prefill(self, req):
        req.prefill_done = True

    async def decode_step(self, reqs):
        return []
