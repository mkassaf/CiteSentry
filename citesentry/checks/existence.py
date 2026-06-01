from __future__ import annotations

import re
import time
from typing import Any

from rapidfuzz import fuzz

from citesentry.models import Candidate, CheckCost, CheckResult, CheckStatus, Reference, Verdict
from citesentry.sources.base import SourceAdapter

_TITLE_PASS_THRESHOLD = 85.0
_TITLE_WARN_THRESHOLD = 70.0
_DOI_IN_URL = re.compile(r'\b(10\.\d{4,}/[^\s"<>\]{}\\^`|]+)')


def _surname(name: str) -> str:
    """Extract surname from 'Last, First' or 'First Last' format."""
    name = name.strip()
    if "," in name:
        return name.split(",")[0].strip().lower()
    parts = name.split()
    return parts[-1].lower() if parts else ""


def _author_overlap(ref_authors: list[str], cand_authors: list[str]) -> float:
    if not ref_authors or not cand_authors:
        return 0.5
    ref_surnames = {_surname(a) for a in ref_authors}
    cand_surnames = {_surname(a) for a in cand_authors}
    intersection = ref_surnames & cand_surnames
    # Use subset recall when cited list is much shorter than found list
    # (covers et al. truncation and papers with many authors).
    if len(ref_surnames) < len(cand_surnames) * 0.5:
        return len(intersection) / len(ref_surnames) if ref_surnames else 0.0
    union = ref_surnames | cand_surnames
    return len(intersection) / len(union) if union else 0.0


def _year_score(ref_year: int | None, cand_year: int | None) -> float:
    if ref_year is None or cand_year is None:
        return 0.5
    diff = abs(ref_year - cand_year)
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.7
    return 0.0


def _score_candidate(ref: Reference, cand: Candidate) -> tuple[float, dict[str, Any]]:
    evidence: dict[str, Any] = {}

    # Exact identifier match is definitive — no fuzzy comparison needed
    if ref.arxiv_id and cand.arxiv_id and ref.arxiv_id == cand.arxiv_id:
        evidence.update({"title_score": 1.0, "exact_arxiv_match": True, "composite": 1.0})
        return 1.0, evidence
    if ref.doi and cand.doi and ref.doi.lower().rstrip("/") == cand.doi.lower().rstrip("/"):
        evidence.update({"title_score": 1.0, "exact_doi_match": True, "composite": 1.0})
        return 1.0, evidence

    title_score = 0.0
    if ref.title and cand.title:
        title_score = fuzz.token_set_ratio(ref.title.lower(), cand.title.lower()) / 100.0
    evidence["title_score"] = round(title_score, 3)

    author_score = _author_overlap(ref.authors, cand.authors)
    evidence["author_score"] = round(author_score, 3)

    year_score = _year_score(ref.year, cand.year)
    evidence["year_score"] = round(year_score, 3)

    venue_score = 0.5
    if ref.venue and cand.venue:
        venue_score = fuzz.token_set_ratio(ref.venue.lower(), cand.venue.lower()) / 100.0
    evidence["venue_score"] = round(venue_score, 3)

    if title_score == 0.0:
        composite = 0.0
    else:
        composite = (
            title_score * 0.55
            + author_score * 0.25
            + year_score * 0.15
            + venue_score * 0.05
        )
    evidence["composite"] = round(composite, 3)
    return composite, evidence


def _check_metadata_consistency(ref: Reference, best: Candidate) -> list[str]:
    mismatches = []
    if ref.year and best.year and abs(ref.year - best.year) > 2:
        mismatches.append(f"year: cited={ref.year}, found={best.year}")
    if ref.doi and best.doi and ref.doi.lower().strip("/") != best.doi.lower().strip("/"):
        mismatches.append(f"doi: cited={ref.doi}, found={best.doi}")
    if ref.authors and best.authors:
        overlap = _author_overlap(ref.authors, best.authors)
        if overlap < 0.3:
            mismatches.append(
                f"authors: low overlap ({overlap:.2f}), "
                f"cited={ref.authors[:2]}, found={best.authors[:2]}"
            )
    return mismatches


async def check_existence(
    ref: Reference,
    sources: list[SourceAdapter],
    domain_sources: list[SourceAdapter] | None = None,
    use_cache: bool = True,
) -> CheckResult:
    start = time.monotonic()
    api_calls = 0
    candidates: list[tuple[float, dict, Candidate]] = []
    evidence: dict[str, Any] = {}

    if use_cache:
        from citesentry.cache import get_cache
        cache = get_cache()
        cache_key = ref.doi or ref.arxiv_id or (f"{ref.title}|{ref.year}" if ref.title else None)
        if cache_key:
            cached = cache.get("existence", cache_key)
            if cached is not None:
                elapsed = (time.monotonic() - start) * 1000
                return CheckResult(
                    name="existence",
                    status=CheckStatus(cached["status"]),
                    confidence=cached["confidence"],
                    evidence={**cached["evidence"], "from_cache": True},
                    cost=CheckCost(api_calls=0, elapsed_ms=elapsed),
                )

    # Extract DOI from URLs if not already present (e.g. https://journal.org/10.1234/xyz)
    effective_doi = ref.doi
    if not effective_doi and ref.urls:
        for url in ref.urls:
            m = _DOI_IN_URL.search(url)
            if m:
                effective_doi = m.group(1).rstrip(".,;)")
                evidence["doi_extracted_from_url"] = effective_doi
                break

    if effective_doi:
        for src in sources:
            try:
                cand = await src.lookup_doi(effective_doi)
                api_calls += 1
                if cand:
                    score, ev = _score_candidate(ref, cand)
                    candidates.append((score, {**ev, "source": src.name, "via": "doi_lookup"}, cand))
            except Exception as e:
                evidence[f"{src.name}_error"] = str(e)

    if not candidates:
        for src in sources:
            try:
                results = await src.search(ref)
                api_calls += 1
                for cand in results:
                    score, ev = _score_candidate(ref, cand)
                    candidates.append((score, {**ev, "source": src.name, "via": "search"}, cand))
            except Exception as e:
                evidence[f"{src.name}_error"] = str(e)

    if not candidates and domain_sources:
        for src in domain_sources:
            try:
                if effective_doi:
                    cand = await src.lookup_doi(effective_doi)
                    api_calls += 1
                    if cand:
                        score, ev = _score_candidate(ref, cand)
                        candidates.append((score, {**ev, "source": src.name, "via": "doi_lookup"}, cand))
                results = await src.search(ref)
                api_calls += 1
                for cand in results:
                    score, ev = _score_candidate(ref, cand)
                    candidates.append((score, {**ev, "source": src.name, "via": "search"}, cand))
            except Exception as e:
                evidence[f"{src.name}_error"] = str(e)

    # Final fallback: resolve landing-page URLs via sources that support it (e.g. Semantic Scholar)
    if not candidates and ref.urls:
        for src in sources:
            for url in ref.urls:
                try:
                    cand = await src.lookup_url(url)
                    api_calls += 1
                    if cand:
                        score, ev = _score_candidate(ref, cand)
                        candidates.append((score, {**ev, "source": src.name, "via": "url_lookup"}, cand))
                except Exception as e:
                    evidence[f"{src.name}_url_error"] = str(e)
            if candidates:
                break

    elapsed = (time.monotonic() - start) * 1000

    if not candidates:
        result = CheckResult(
            name="existence",
            status=CheckStatus.FAIL,
            confidence=0.9 if (ref.title or ref.doi) else 0.5,
            evidence={**evidence, "verdict": "not_found", "candidates_checked": 0},
            cost=CheckCost(api_calls=api_calls, elapsed_ms=elapsed),
        )
    else:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_ev, best_cand = candidates[0]
        evidence.update(best_ev)
        evidence["best_candidate_title"] = best_cand.title
        evidence["best_candidate_source"] = best_cand.source
        evidence["best_candidate_year"] = best_cand.year
        evidence["best_candidate_doi"] = best_cand.doi
        evidence["best_candidate_venue"] = best_cand.venue
        evidence["best_candidate_authors"] = best_cand.authors
        evidence["total_candidates"] = len(candidates)

        title_score = best_ev.get("title_score", 0.0)

        # High title match always warrants a look, even if other fields diverge
        if title_score >= 0.85 or best_score * 100 >= _TITLE_PASS_THRESHOLD:
            mismatches = _check_metadata_consistency(ref, best_cand)
            if mismatches:
                evidence["mismatches"] = mismatches
                status = CheckStatus.WARN
                confidence = min(max(title_score, best_score), 0.85)
            else:
                status = CheckStatus.PASS
                confidence = max(title_score, best_score)
        elif best_score * 100 >= _TITLE_WARN_THRESHOLD:
            status = CheckStatus.WARN
            confidence = best_score * 0.7
        else:
            status = CheckStatus.FAIL
            confidence = 0.7

        result = CheckResult(
            name="existence",
            status=status,
            confidence=confidence,
            evidence=evidence,
            cost=CheckCost(api_calls=api_calls, elapsed_ms=elapsed),
        )

    if use_cache:
        from citesentry.cache import get_cache
        cache = get_cache()
        cache_key = ref.doi or ref.arxiv_id or (f"{ref.title}|{ref.year}" if ref.title else None)
        if cache_key:
            cache.set("existence", cache_key, {
                "status": result.status.value,
                "confidence": result.confidence,
                "evidence": result.evidence,
            })

    return result
