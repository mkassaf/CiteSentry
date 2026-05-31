from __future__ import annotations

import json
import time
from typing import Any

import httpx

from refsift.models import CheckCost, CheckResult, CheckStatus, RelevanceLabel, Reference

_RELEVANCE_PROMPT = """\
You are a citation relevance judge. Given a reference title/topic and fetched content from the cited source, determine if the content matches the citation.

Reference title: {title}
Reference topic context: {context}

Fetched content (first 1500 chars):
{content}

Respond with ONLY valid JSON in this exact format:
{{"label": "<RELEVANT|PARTIAL|UNRELATED|CANNOT_DETERMINE>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}

Labels:
- RELEVANT: content clearly matches the cited title/topic
- PARTIAL: content partially matches or is in the same general area
- UNRELATED: content does not match the citation at all
- CANNOT_DETERMINE: paywalled, JS-only page, no meaningful content to judge
"""


async def _fetch_content(url: str, doi: str | None = None) -> str:
    """Fetch content for relevance check. Returns text snippet."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; refsift/0.1; citation verification bot)"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if 200 <= r.status_code < 300:
                text = r.text[:3000]
                text = " ".join(text.split())
                return text[:1500]
    except httpx.HTTPError:
        pass
    return ""


async def check_relevance(
    ref: Reference,
    llm_client: object,
    abstract: str | None = None,
    use_cache: bool = True,
) -> CheckResult:
    start = time.monotonic()

    if llm_client is None:
        return CheckResult(
            name="relevance",
            status=CheckStatus.SKIPPED,
            confidence=0.0,
            evidence={"reason": "no_llm_client"},
            cost=CheckCost(elapsed_ms=0.0),
        )

    if not ref.title and not ref.doi:
        return CheckResult(
            name="relevance",
            status=CheckStatus.SKIPPED,
            confidence=0.0,
            evidence={"reason": "insufficient_reference_data"},
            cost=CheckCost(elapsed_ms=0.0),
        )

    cache_key = ref.doi or (f"{ref.title}|{','.join(ref.urls[:1])}" if ref.title else None)
    if use_cache and cache_key:
        from refsift.cache import get_cache
        cache = get_cache()
        cached = cache.get("relevance", cache_key)
        if cached is not None:
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult(
                name="relevance",
                status=CheckStatus(cached["status"]),
                confidence=cached["confidence"],
                evidence={**cached["evidence"], "from_cache": True},
                cost=CheckCost(elapsed_ms=elapsed),
            )

    content = abstract or ""
    if not content and ref.urls:
        content = await _fetch_content(ref.urls[0])

    if not content:
        return CheckResult(
            name="relevance",
            status=CheckStatus.WARN,
            confidence=0.3,
            evidence={"reason": "no_content_available", "label": "CANNOT_DETERMINE"},
            cost=CheckCost(elapsed_ms=(time.monotonic() - start) * 1000),
        )

    context = ""
    if ref.venue:
        context += f"Published in: {ref.venue}. "
    if ref.year:
        context += f"Year: {ref.year}."

    prompt = _RELEVANCE_PROMPT.format(
        title=ref.title or "Unknown title",
        context=context,
        content=content,
    )

    tokens_used = 0
    label = RelevanceLabel.CANNOT_DETERMINE
    confidence = 0.3
    rationale = ""
    evidence: dict[str, Any] = {"content_source": "abstract" if abstract else "fetched"}

    try:
        from refsift.llm.base import LLMClient
        response_text = await llm_client.complete(prompt)  # type: ignore[union-attr]
        tokens_used = len(prompt.split()) + len(response_text.split())

        response_text = response_text.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        parsed = json.loads(response_text)
        label = RelevanceLabel(parsed.get("label", "CANNOT_DETERMINE"))
        confidence = float(parsed.get("confidence", 0.3))
        rationale = parsed.get("rationale", "")
        evidence["label"] = label.value
        evidence["rationale"] = rationale

    except (json.JSONDecodeError, ValueError, KeyError):
        label = RelevanceLabel.CANNOT_DETERMINE
        confidence = 0.2
        evidence["parse_error"] = True
    except Exception as e:
        evidence["llm_error"] = str(e)
        label = RelevanceLabel.CANNOT_DETERMINE
        confidence = 0.1

    if label == RelevanceLabel.RELEVANT:
        status = CheckStatus.PASS
    elif label == RelevanceLabel.PARTIAL:
        status = CheckStatus.WARN
    elif label == RelevanceLabel.UNRELATED:
        status = CheckStatus.FAIL
    else:
        status = CheckStatus.WARN

    result = CheckResult(
        name="relevance",
        status=status,
        confidence=confidence,
        evidence=evidence,
        cost=CheckCost(tokens_used=tokens_used, elapsed_ms=(time.monotonic() - start) * 1000),
    )

    if use_cache and cache_key:
        from refsift.cache import get_cache
        cache = get_cache()
        cache.set("relevance", cache_key, {
            "status": result.status.value,
            "confidence": result.confidence,
            "evidence": evidence,
        })

    return result
