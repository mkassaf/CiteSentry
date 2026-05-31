from __future__ import annotations

import asyncio
from typing import Sequence

from citesentry.checks.existence import check_existence
from citesentry.checks.relevance import check_relevance
from citesentry.checks.url_liveness import check_url_liveness
from citesentry.core.cascade import VerifyOptions
from citesentry.core.verdict import compute_verdict
from citesentry.models import CheckStatus, Reference, VerificationReport
from citesentry.sources.domain.dblp import DBLPAdapter, is_cs
from citesentry.sources.domain.pubmed import PubMedAdapter, is_biomedical


def _build_enriched(ref: Reference, existence_evidence: dict) -> Reference | None:
    """Return a Reference with database-sourced fields when the original citation was incomplete."""
    missing = not ref.year or not ref.doi or not ref.venue
    if not missing:
        return None
    year = existence_evidence.get("best_candidate_year")
    doi = existence_evidence.get("best_candidate_doi")
    venue = existence_evidence.get("best_candidate_venue")
    authors = existence_evidence.get("best_candidate_authors")
    title = existence_evidence.get("best_candidate_title")
    if not any([year, doi, venue]):
        return None
    return ref.model_copy(update={
        "year": ref.year or year,
        "doi": ref.doi or doi,
        "venue": ref.venue or venue,
        "authors": ref.authors or (authors or []),
        "title": ref.title or title,
    })


def _build_domain_sources(ref: Reference, opts: VerifyOptions) -> list:
    if opts.domain_sources:
        return opts.domain_sources

    if opts.domain_mode == "none":
        return []

    domain: list = []
    if opts.domain_mode == "all":
        domain = [PubMedAdapter(), DBLPAdapter()]
    elif opts.domain_mode == "pubmed":
        domain = [PubMedAdapter()]
    elif opts.domain_mode == "dblp":
        domain = [DBLPAdapter()]
    elif opts.domain_mode == "auto":
        if is_biomedical(ref):
            domain.append(PubMedAdapter())
        if is_cs(ref):
            domain.append(DBLPAdapter())

    return domain


async def verify_one(ref: Reference, opts: VerifyOptions) -> VerificationReport:
    checks = []
    domain_sources = _build_domain_sources(ref, opts)

    existence = await check_existence(
        ref,
        sources=opts.sources,
        domain_sources=domain_sources,
        use_cache=opts.use_cache,
    )
    checks.append(existence)

    if existence.status == CheckStatus.FAIL and not ref.urls:
        verdict, notes = compute_verdict(ref, checks)
        return VerificationReport(
            reference=ref,
            checks=checks,
            overall_verdict=verdict,
            notes=notes,
        )

    if opts.check_url and ref.urls:
        url_result = await check_url_liveness(ref.urls, use_cache=opts.use_cache)
        checks.append(url_result)

    if opts.check_relevance and opts.llm_client is not None:
        abstract = existence.evidence.get("abstract")
        rel_result = await check_relevance(
            ref,
            llm_client=opts.llm_client,
            abstract=abstract,
            use_cache=opts.use_cache,
        )
        checks.append(rel_result)

    verdict, notes = compute_verdict(ref, checks)
    enriched = _build_enriched(ref, existence.evidence) if existence.evidence else None
    return VerificationReport(
        reference=ref,
        checks=checks,
        overall_verdict=verdict,
        notes=notes,
        enriched=enriched,
    )


async def verify_many(
    refs: Sequence[Reference],
    opts: VerifyOptions,
) -> list[VerificationReport]:
    semaphore = asyncio.Semaphore(opts.concurrency)

    async def _bounded(ref: Reference) -> VerificationReport:
        async with semaphore:
            return await verify_one(ref, opts)

    tasks = [_bounded(ref) for ref in refs]
    return await asyncio.gather(*tasks)
