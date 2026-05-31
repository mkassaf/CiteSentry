from __future__ import annotations

from dataclasses import dataclass, field

from refsift.sources.base import SourceAdapter


@dataclass
class VerifyOptions:
    check_url: bool = True
    check_relevance: bool = True
    use_cache: bool = True
    sources: list[SourceAdapter] = field(default_factory=list)
    domain_sources: list[SourceAdapter] = field(default_factory=list)
    llm_client: object | None = None
    concurrency: int = 8
    domain_mode: str = "auto"
