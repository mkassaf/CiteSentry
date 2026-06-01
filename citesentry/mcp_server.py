from __future__ import annotations

import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("citesentry")


def _build_sources():
    from citesentry.sources.crossref import CrossrefAdapter
    from citesentry.sources.openalex import OpenAlexAdapter
    from citesentry.sources.semantic_scholar import SemanticScholarAdapter
    from citesentry.sources.arxiv import ArXivAdapter

    return [CrossrefAdapter(), OpenAlexAdapter(), SemanticScholarAdapter(), ArXivAdapter()]


def _make_llm_client():
    """Try DeepSeek if DEEPSEEK_API_KEY is set; otherwise None (relevance skipped)."""
    from citesentry.llm.deepseek import make_deepseek_client

    return make_deepseek_client()


def _make_opts(check_url: bool, check_relevance: bool):
    from citesentry.core.cascade import VerifyOptions

    llm_client = _make_llm_client() if check_relevance else None

    return VerifyOptions(
        check_url=check_url,
        check_relevance=check_relevance and llm_client is not None,
        sources=_build_sources(),
        llm_client=llm_client,
        use_cache=True,
        domain_mode="auto",  # auto-enables DBLP, PubMed, Google Books per reference type
    )


def _log_startup_config() -> None:
    """Write a one-time config summary to stderr so users know what's active."""
    from citesentry.config import get_settings
    s = get_settings()
    active = []
    if s.semantic_scholar_api_key:
        active.append("Semantic Scholar (keyed)")
    else:
        active.append("Semantic Scholar (anonymous — set SEMANTIC_SCHOLAR_API_KEY for higher limits)")
    if s.google_books_api_key:
        active.append("Google Books (keyed)")
    if s.grobid_api_url:
        active.append(f"GROBID at {s.grobid_api_url}")
    sys.stderr.write("citesentry active sources: " + ", ".join(active) + "\n")


@mcp.tool()
async def verify_reference(
    reference: str,
    check_url: bool = True,
    check_relevance: bool = True,
) -> dict:
    """
    Verify a single bibliographic reference.

    Checks: (1) existence in scholarly databases, (2) URL liveness, (3) content relevance.

    Databases queried: OpenAlex, Crossref, Semantic Scholar, arXiv, DBLP (CS papers),
    PubMed (biomedical), Google Books (textbooks). Set SEMANTIC_SCHOLAR_API_KEY and
    GOOGLE_BOOKS_API_KEY in the MCP server env for higher rate limits.

    Returns a VerificationReport dict. overall_verdict values:
    - VERIFIED: paper found in a scholarly database with matching metadata
    - METADATA_MISMATCH: paper found but a field disagrees (year, authors, DOI)
    - DEAD_URL: paper may exist but a cited URL is not reachable
    - CONTENT_DRIFT: URL is live but content no longer matches the citation
    - NOT_FOUND: could not verify — needs manual review; NOT proof of fabrication
    - UNRESOLVABLE: reference could not be parsed (missing title, DOI, authors)

    Content relevance uses MCP sampling (no extra key needed in MCP mode).
    """
    from citesentry.parse.plaintext import extract_fields, Style
    from citesentry.core.engine import verify_one

    ref = extract_fields(reference, Style.UNKNOWN)
    opts = _make_opts(check_url, check_relevance)
    report = await verify_one(ref, opts)
    return report.model_dump(mode="json")


@mcp.tool()
async def verify_reference_list(
    references: list[str] | str,
    format: str = "auto",
    check_url: bool = True,
    check_relevance: bool = True,
) -> dict:
    """
    Verify multiple references at once.

    `references` can be:
    - A list of raw reference strings
    - A single text blob in any supported format (BibTeX, RIS, CSL JSON, NBIB, plain list)

    `format` overrides auto-detection: bibtex, ris, csl_json, nbib, doi_list, plaintext, auto.

    Returns {"reports": [...], "summary": {"total": N, "verified": N, "issues": N, "skipped": N}}.
    NOT_FOUND means "could not verify — needs manual review," not "proven fake."
    Content relevance requires DEEPSEEK_API_KEY; otherwise that check is skipped.
    """
    from citesentry.parse.detect import auto_parse
    from citesentry.parse.plaintext import extract_fields, Style
    from citesentry.core.engine import verify_many
    from citesentry.models import Verdict

    if isinstance(references, list):
        refs = [extract_fields(r, Style.UNKNOWN) for r in references]
    else:
        fmt_hint = None if format == "auto" else format
        refs = auto_parse(references, format_hint=fmt_hint)

    if not refs:
        return {"reports": [], "summary": {"total": 0, "verified": 0, "issues": 0, "skipped": 0}}

    opts = _make_opts(check_url, check_relevance)
    reports = await verify_many(refs, opts)

    summary = {
        "total": len(reports),
        "verified": sum(1 for r in reports if r.overall_verdict == Verdict.VERIFIED),
        "issues": sum(
            1 for r in reports
            if r.overall_verdict in {
                Verdict.NOT_FOUND, Verdict.DEAD_URL,
                Verdict.METADATA_MISMATCH, Verdict.CONTENT_DRIFT
            }
        ),
        "skipped": sum(1 for r in reports if r.overall_verdict == Verdict.UNRESOLVABLE),
    }

    return {
        "reports": [r.model_dump(mode="json") for r in reports],
        "summary": summary,
    }


@mcp.tool()
async def check_url_alive(url: str) -> dict:
    """
    Check whether a URL is reachable (2xx response).

    Returns {"url": str, "status": "PASS|FAIL|WARN|SKIPPED", "details": {...}}.
    SKIPPED means the URL is behind bot protection (Cloudflare, LinkedIn, etc.) — not necessarily dead.
    """
    from citesentry.checks.url_liveness import check_url_liveness

    result = await check_url_liveness([url], use_cache=False)
    url_results = result.evidence.get("url_results", [{}])
    details = url_results[0].get("evidence", {}) if url_results else {}
    return {
        "url": url,
        "status": result.status.value,
        "details": details,
    }


def main() -> None:
    sys.stderr.write("citesentry MCP server starting (stdio transport)\n")
    _log_startup_config()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
