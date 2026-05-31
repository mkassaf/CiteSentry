from __future__ import annotations

import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("refsift")


def _build_sources():
    from refsift.sources.crossref import CrossrefAdapter
    from refsift.sources.openalex import OpenAlexAdapter
    from refsift.sources.semantic_scholar import SemanticScholarAdapter
    from refsift.sources.arxiv import ArXivAdapter

    return [CrossrefAdapter(), OpenAlexAdapter(), SemanticScholarAdapter(), ArXivAdapter()]


def _make_llm_client():
    """Try DeepSeek if DEEPSEEK_API_KEY is set; otherwise None (relevance skipped)."""
    from refsift.llm.deepseek import make_deepseek_client

    return make_deepseek_client()


def _make_opts(check_url: bool, check_relevance: bool):
    from refsift.core.cascade import VerifyOptions

    llm_client = _make_llm_client() if check_relevance else None

    return VerifyOptions(
        check_url=check_url,
        check_relevance=check_relevance and llm_client is not None,
        sources=_build_sources(),
        llm_client=llm_client,
        use_cache=True,
        domain_mode="auto",
    )


@mcp.tool()
async def verify_reference(
    reference: str,
    check_url: bool = True,
    check_relevance: bool = True,
) -> dict:
    """
    Verify a single bibliographic reference.

    Checks: (1) existence in scholarly databases, (2) URL liveness, (3) content relevance.

    Returns a VerificationReport dict. overall_verdict values:
    - VERIFIED: paper exists, metadata consistent, URLs live, content relevant
    - METADATA_MISMATCH: paper exists but at least one field disagrees (possible LLM hallucination)
    - DEAD_URL: paper may exist but a cited URL is not reachable
    - CONTENT_DRIFT: URL is live but content no longer matches the citation
    - NOT_FOUND: could not verify in any database — needs manual review, do NOT label as fake
    - UNRESOLVABLE: reference could not be parsed well enough to check

    Content relevance check requires DEEPSEEK_API_KEY env var; otherwise skipped.
    """
    from refsift.parse.plaintext import extract_fields, Style
    from refsift.core.engine import verify_one

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
    from refsift.parse.detect import auto_parse
    from refsift.parse.plaintext import extract_fields, Style
    from refsift.core.engine import verify_many
    from refsift.models import Verdict

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
    from refsift.checks.url_liveness import check_url_liveness

    result = await check_url_liveness([url], use_cache=False)
    url_results = result.evidence.get("url_results", [{}])
    details = url_results[0].get("evidence", {}) if url_results else {}
    return {
        "url": url,
        "status": result.status.value,
        "details": details,
    }


def main() -> None:
    import sys

    sys.stderr.write("refsift MCP server starting (stdio transport)\n")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
