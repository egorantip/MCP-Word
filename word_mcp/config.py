from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROFILES = {
    "minimal": {"model": "qwen3.5:0.8b", "num_ctx": 4096, "num_predict": 768, "image_edge": 768},
    "light": {"model": "qwen3.5:2b", "num_ctx": 4096, "num_predict": 1024, "image_edge": 1024},
    "balanced": {"model": "qwen3.5:4b", "num_ctx": 8192, "num_predict": 2048, "image_edge": 1280},
    "quality": {"model": "qwen3.5:9b", "num_ctx": 8192, "num_predict": 2048, "image_edge": 1536},
}
VISION_MODEL = "qwen3-vl:4b"


@dataclass(frozen=True)
class Settings:
    root: Path
    ollama_url: str = "http://127.0.0.1:11434"
    profile: str = "light"
    model: str | None = None
    vision_model: str | None = None
    timeout: float = 180
    max_file_bytes: int = 30 * 1024 * 1024
    max_unpacked_bytes: int = 100 * 1024 * 1024

    @property
    def options(self) -> dict:
        return PROFILES[self.profile]

    @property
    def text_model(self) -> str:
        return self.model or str(self.options["model"])

    @property
    def image_model(self) -> str:
        return self.vision_model or VISION_MODEL

    @classmethod
    def from_env(cls) -> "Settings":
        profile = os.environ.get("WORD_MCP_PROFILE", "light")
        if profile not in PROFILES:
            raise ValueError(f"Unknown profile {profile!r}. Choose: {', '.join(PROFILES)}")
        return cls(
            root=Path(os.environ.get("WORD_MCP_ROOT", "documents")).resolve(),
            ollama_url=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            profile=profile,
            model=os.environ.get("WORD_MCP_MODEL") or None,
            vision_model=os.environ.get("WORD_MCP_VISION_MODEL") or None,
        )
