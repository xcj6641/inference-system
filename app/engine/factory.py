from .fake_engine import FakeEngine
from .dummy_engine import DummyEngine
from .spy_engine import SpyEngine


from app.logger_config import setup_logger

def create_engine(
    backend: str = "fake",
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

    raise ValueError(
        f"Unknown backend: {backend}"
    )