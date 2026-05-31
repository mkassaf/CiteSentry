from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    METADATA_MISMATCH = "METADATA_MISMATCH"
    DEAD_URL = "DEAD_URL"
    CONTENT_DRIFT = "CONTENT_DRIFT"
    NOT_FOUND = "NOT_FOUND"
    UNRESOLVABLE = "UNRESOLVABLE"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class RelevanceLabel(str, Enum):
    RELEVANT = "RELEVANT"
    PARTIAL = "PARTIAL"
    UNRELATED = "UNRELATED"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class Reference(BaseModel):
    raw: str = ""
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    urls: list[str] = Field(default_factory=list)
    pmid: str | None = None


class Candidate(BaseModel):
    raw: str = ""
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    urls: list[str] = Field(default_factory=list)
    source: str = ""
    match_score: float = 0.0


class CheckCost(BaseModel):
    tokens_used: int = 0
    api_calls: int = 0
    elapsed_ms: float = 0.0


class CheckResult(BaseModel):
    name: Literal["existence", "url_liveness", "relevance"]
    status: CheckStatus
    confidence: float = 0.0
    evidence: dict[str, Any] = Field(default_factory=dict)
    cost: CheckCost = Field(default_factory=CheckCost)


class VerificationReport(BaseModel):
    reference: Reference
    checks: list[CheckResult] = Field(default_factory=list)
    overall_verdict: Verdict = Verdict.UNRESOLVABLE
    notes: list[str] = Field(default_factory=list)

    def verdict_display(self) -> str:
        if self.overall_verdict == Verdict.NOT_FOUND:
            return "could not verify — likely fabricated, needs manual review"
        return self.overall_verdict.value
