"""citesentry — citation verification tool."""

from __future__ import annotations

__version__ = "0.4.0"


def _make_llm(
    provider: str | None = None,
    model: str | None = None,
    url: str | None = None,
):
    """Internal: resolve an LLM client from explicit args + env fallback."""
    p = (provider or "auto").lower()
    if p == "none":
        return None

    if p in ("deepseek", "auto"):
        try:
            from citesentry.llm.deepseek import DeepSeekClient, make_deepseek_client
            from citesentry.config import get_settings
            s = get_settings()
            if model and p == "deepseek" and s.deepseek_api_key:
                return DeepSeekClient(s.deepseek_api_key, url or s.deepseek_base_url, model)
            client = make_deepseek_client()
            if client:
                return client
        except ImportError:
            pass

    if p in ("ollama", "auto"):
        try:
            from citesentry.llm.ollama import OllamaClient
            from citesentry.config import get_settings
            s = get_settings()
            m = model or s.ollama_model
            if m:
                return OllamaClient(base_url=url or s.ollama_base_url, model=m)
        except ImportError:
            pass

    return None


async def verify(
    reference: str,
    *,
    check_url: bool = True,
    check_relevance: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_url: str | None = None,
    domain_mode: str = "auto",
    use_cache: bool = True,
) -> dict:
    """
    Verify a single reference string. Async.

    Args:
        reference:      Raw citation text in any format.
        check_url:      Check URL liveness (default True).
        check_relevance: Run LLM relevance check (default True).
        llm_provider:   "auto" | "deepseek" | "ollama" | "none"
        llm_model:      Override model name, e.g. "llama3.2".
        llm_url:        Override LLM base URL, e.g. "http://localhost:11434/v1".
        domain_mode:    "auto" | "dblp" | "pubmed" | "all" | "none"
        use_cache:      Use SQLite result cache (default True).

    Returns a dict (VerificationReport serialised to JSON-compatible dict).

    Example::

        import asyncio, citesentry

        report = asyncio.run(citesentry.verify(
            "Vaswani et al. (2017). Attention is all you need. NeurIPS.",
            llm_provider="ollama",
            llm_model="llama3.2",
        ))
        print(report["overall_verdict"])   # "VERIFIED"
    """
    from citesentry.parse.plaintext import extract_fields, Style
    from citesentry.core.engine import verify_one
    from citesentry.core.cascade import VerifyOptions
    from citesentry.sources.crossref import CrossrefAdapter
    from citesentry.sources.openalex import OpenAlexAdapter
    from citesentry.sources.semantic_scholar import SemanticScholarAdapter
    from citesentry.sources.arxiv import ArXivAdapter

    ref = extract_fields(reference, Style.UNKNOWN)
    llm_client = _make_llm(llm_provider, llm_model, llm_url) if check_relevance else None

    opts = VerifyOptions(
        check_url=check_url,
        check_relevance=check_relevance and llm_client is not None,
        sources=[CrossrefAdapter(), OpenAlexAdapter(), SemanticScholarAdapter(), ArXivAdapter()],
        llm_client=llm_client,
        use_cache=use_cache,
        domain_mode=domain_mode,
    )
    report = await verify_one(ref, opts)
    return report.model_dump(mode="json")


async def verify_many(
    references: list[str],
    *,
    check_url: bool = True,
    check_relevance: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_url: str | None = None,
    domain_mode: str = "auto",
    use_cache: bool = True,
    concurrency: int = 8,
) -> list[dict]:
    """
    Verify a list of reference strings. Async.

    Same keyword arguments as :func:`verify`. Returns a list of report dicts.

    Example::

        import asyncio, citesentry

        refs = [
            "Vaswani et al. (2017). Attention is all you need. NeurIPS.",
            "LeCun et al. (1989). Backpropagation applied to handwritten zip code recognition.",
        ]
        reports = asyncio.run(citesentry.verify_many(
            refs,
            llm_provider="ollama",
            llm_model="llama3.2",
        ))
        for r in reports:
            print(r["overall_verdict"], r["reference"]["title"])
    """
    from citesentry.parse.plaintext import extract_fields, Style
    from citesentry.core import engine as _engine
    from citesentry.core.cascade import VerifyOptions
    from citesentry.sources.crossref import CrossrefAdapter
    from citesentry.sources.openalex import OpenAlexAdapter
    from citesentry.sources.semantic_scholar import SemanticScholarAdapter
    from citesentry.sources.arxiv import ArXivAdapter

    parsed = [extract_fields(r, Style.UNKNOWN) for r in references]
    llm_client = _make_llm(llm_provider, llm_model, llm_url) if check_relevance else None

    opts = VerifyOptions(
        check_url=check_url,
        check_relevance=check_relevance and llm_client is not None,
        sources=[CrossrefAdapter(), OpenAlexAdapter(), SemanticScholarAdapter(), ArXivAdapter()],
        llm_client=llm_client,
        use_cache=use_cache,
        domain_mode=domain_mode,
        concurrency=concurrency,
    )
    reports = await _engine.verify_many(parsed, opts)
    return [r.model_dump(mode="json") for r in reports]
