from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_dir


def _default_cache_path() -> Path:
    return Path(user_cache_dir("citesentry")) / "cache.db"


@dataclass
class Settings:
    mailto: str = field(default_factory=lambda: os.getenv("CITESENTRY_MAILTO", "citesentry@example.com"))
    cache_path: Path = field(default_factory=_default_cache_path)
    cache_enabled: bool = True
    request_timeout: float = 15.0
    concurrency: int = 8
    politeness_delay: float = 0.5

    grobid_api_url: str | None = field(
        default_factory=lambda: os.getenv("CITESENTRY_GROBID_URL", "https://kermitt2-grobid.hf.space/api")
    )

    deepseek_api_key: str | None = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY")
    )
    deepseek_base_url: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )
    deepseek_model: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
