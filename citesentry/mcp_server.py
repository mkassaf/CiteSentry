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


def _resolve_llm_client(
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_url: str | None = None,
):
    """
    Build an LLM client from explicit tool parameters, falling back to env-var auto-detection.

    llm_provider: "auto" | "deepseek" | "ollama" | "none"
    llm_model:    override model name (e.g. "llama3.2", "deepseek-chat")
    llm_url:      override base URL (e.g. "http://remote-host:11434/v1")
    """
    provider = (llm_provider or "auto").lower()

    if provider == "none":
        return None

    if provider in ("deepseek", "auto"):
        try:
            from citesentry.llm.deepseek import DeepSeekClient, make_deepseek_client
            from citesentry.config import get_settings
            s = get_settings()
            if llm_model and provider == "deepseek" and s.deepseek_api_key:
                return DeepSeekClient(s.deepseek_api_key, llm_url or s.deepseek_base_url, llm_model)
            client = make_deepseek_client()
            if client:
                return client
        except ImportError:
            pass

    if provider in ("ollama", "auto"):
        try:
            from citesentry.llm.ollama import OllamaClient
            from citesentry.config import get_settings
            s = get_settings()
            model = llm_model or s.ollama_model
            if model:
                return OllamaClient(base_url=llm_url or s.ollama_base_url, model=model)
        except ImportError:
            pass

    return None


def _make_opts(
    check_url: bool,
    check_relevance: bool,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_url: str | None = None,
):
    from citesentry.core.cascade import VerifyOptions

    llm_client = None
    if check_relevance:
        llm_client = _resolve_llm_client(llm_provider, llm_model, llm_url)

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
    llm_provider: str = "auto",
    llm_model: str = "",
    llm_url: str = "",
) -> dict:
    """
    Verify a single bibliographic reference.

    Args:
        reference: Raw reference string in any format (APA, IEEE, LNCS, BibTeX, etc.)
        check_url: Whether to check URL liveness (default True)
        check_relevance: Whether to check content relevance via LLM (default True)
        llm_provider: LLM backend — "auto" (default), "deepseek", "ollama", or "none"
        llm_model: Override model name, e.g. "llama3.2" or "deepseek-chat" (empty = use env/default)
        llm_url: Override LLM base URL, e.g. "http://localhost:11434/v1" (empty = use env/default)

    Returns a VerificationReport dict. overall_verdict values:
    - VERIFIED: paper exists, metadata consistent
    - METADATA_MISMATCH: paper found but a field disagrees (possible LLM hallucination)
    - DEAD_URL: paper may exist but a cited URL is not reachable
    - CONTENT_DRIFT: URL is live but content no longer matches the citation
    - NOT_FOUND: could not verify — needs manual review, do NOT label as fake
    - UNRESOLVABLE: reference could not be parsed well enough to check
    """
    from citesentry.parse.plaintext import extract_fields, Style
    from citesentry.core.engine import verify_one

    ref = extract_fields(reference, Style.UNKNOWN)
    opts = _make_opts(
        check_url, check_relevance,
        llm_provider or None, llm_model or None, llm_url or None,
    )
    report = await verify_one(ref, opts)
    return report.model_dump(mode="json")


@mcp.tool()
async def verify_reference_list(
    references: list[str] | str,
    format: str = "auto",
    check_url: bool = True,
    check_relevance: bool = True,
    llm_provider: str = "auto",
    llm_model: str = "",
    llm_url: str = "",
) -> dict:
    """
    Verify multiple references at once.

    Args:
        references: A list of raw reference strings, or a single text blob in any
                    supported format (BibTeX, RIS, CSL JSON, NBIB, plaintext list).
        format: Format hint — bibtex, ris, csl_json, nbib, doi_list, plaintext, auto.
        check_url: Whether to check URL liveness (default True)
        check_relevance: Whether to check content relevance via LLM (default True)
        llm_provider: LLM backend — "auto" (default), "deepseek", "ollama", or "none"
        llm_model: Override model name, e.g. "llama3.2" or "deepseek-chat"
        llm_url: Override LLM base URL, e.g. "http://localhost:11434/v1"

    Returns {"reports": [...], "summary": {"total": N, "verified": N, "issues": N, "skipped": N}}.
    NOT_FOUND means "could not verify — needs manual review," not "proven fake."
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

    opts = _make_opts(
        check_url, check_relevance,
        llm_provider or None, llm_model or None, llm_url or None,
    )
    reports = await verify_many(refs, opts)

    summary = {
        "total": len(reports),
        "verified": sum(1 for r in reports if r.overall_verdict == Verdict.VERIFIED),
        "issues": sum(
            1 for r in reports
            if r.overall_verdict in {
                Verdict.NOT_FOUND, Verdict.DEAD_URL,
                Verdict.METADATA_MISMATCH, Verdict.CONTENT_DRIFT,
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
    SKIPPED means the URL is behind bot protection — not necessarily dead.
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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
