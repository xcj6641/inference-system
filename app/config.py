from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    engine_backend: str = os.getenv("ENGINE_BACKEND", "fake")
    vllm_base_url: str = os.getenv("VLLM_BASE_URL", "http://localhost:8001")
    vllm_model: str = os.getenv(
        "VLLM_MODEL",
        "Qwen/Qwen2.5-0.5B-Instruct",
    )
    vllm_timeout: float = float(os.getenv("VLLM_TIMEOUT", "60"))


settings = Settings()