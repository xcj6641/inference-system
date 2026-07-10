import os


from .fake_engine import FakeEngine
from .dummy_engine import DummyEngine
from .spy_engine import SpyEngine
from .vllm_http_engine import VLLMHttpEngine


from app.logger_config import setup_logger

def create_engine(
    backend: str = "fake",
    base_url: str | None = None,
    model: str | None = None
):

    logger = setup_logger()
    logger.info("Backend: %s",{backend})
    print("=" * 40)
    print(f"Backend: {backend}")
    print("=" * 40)

    if backend == "fake":
        return FakeEngine()
    if backend == "dummy":
        return DummyEngine()
    if backend == "spy":
        return SpyEngine()
    if backend == "vllm_http":
        return VLLMHttpEngine(base_url, model)

    raise ValueError(
        f"Unknown backend: {backend}"
    )