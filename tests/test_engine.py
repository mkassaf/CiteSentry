from __future__ import annotations

import pytest
import respx
import httpx

from citesentry.models import Reference, Verdict, CheckStatus
from citesentry.core.engine import verify_one, verify_many
from citesentry.core.cascade import VerifyOptions
from citesentry.sources.openalex import OpenAlexAdapter

_OPENALEX_WORK = {
    "id": "https://openalex.org/W2964232343",
    "title": "Attention is all you need",
    "doi": "https://doi.org/10.48550/arXiv.1706.03762",
    "publication_year": 2017,
    "authorships": [
        {"author": {"display_name": "Ashish Vaswani"}},
        {"author": {"display_name": "Noam Shazeer"}},
    ],
    "primary_location": {
        "source": {"display_name": "Advances in Neural Information Processing Systems"}
    },
    "ids": {},
}


@pytest.mark.asyncio
class TestEngine:
    def _opts(self, sources=None, llm_client=None, check_url=False, check_relevance=False):
        return VerifyOptions(
            sources=sources or [],
            llm_client=llm_client,
            check_url=check_url,
            check_relevance=check_relevance,
            use_cache=False,
            domain_mode="none",
        )

    async def test_verified_with_matching_doi(self):
        doi = "10.48550/arXiv.1706.03762"
        ref = Reference(
            title="Attention is all you need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            year=2017,
            doi=doi,
        )
        async with respx.mock:
            respx.get(f"https://api.openalex.org/works/https://doi.org/{doi}").mock(
                return_value=httpx.Response(200, json=_OPENALEX_WORK)
            )
            adapter = OpenAlexAdapter()
            opts = self._opts(sources=[adapter])
            report = await verify_one(ref, opts)
            assert report.overall_verdict == Verdict.VERIFIED
            await adapter.close()

    async def test_not_found_for_unknown_paper(self):
        ref = Reference(
            title="Completely Made Up Paper That Does Not Exist",
            authors=["Fictional Author"],
            year=2099,
        )
        async with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            adapter = OpenAlexAdapter()
            opts = self._opts(sources=[adapter])
            report = await verify_one(ref, opts)
            assert report.overall_verdict == Verdict.NOT_FOUND
            await adapter.close()

    async def test_unresolvable_empty_ref(self):
        ref = Reference()
        opts = self._opts()
        report = await verify_one(ref, opts)
        assert report.overall_verdict == Verdict.UNRESOLVABLE

    async def test_verify_many(self):
        refs = [
            Reference(title="Nonexistent A", authors=["Nobody"], year=2099),
            Reference(title="Nonexistent B", authors=["Anybody"], year=2099),
        ]
        async with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            adapter = OpenAlexAdapter()
            opts = self._opts(sources=[adapter])
            reports = await verify_many(refs, opts)
            assert len(reports) == 2
            assert all(r.overall_verdict == Verdict.NOT_FOUND for r in reports)
            await adapter.close()

    async def test_verdict_display_not_found_no_fake(self):
        ref = Reference(title="fake paper", authors=["nobody"], year=2099)
        async with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            adapter = OpenAlexAdapter()
            opts = self._opts(sources=[adapter])
            report = await verify_one(ref, opts)
            display = report.verdict_display()
            assert "fake" not in display.lower()
            assert "manual review" in display.lower() or "verify" in display.lower()
            await adapter.close()

    async def test_dead_url_verdict(self):
        ref = Reference(
            title="Attention is all you need",
            authors=["Ashish Vaswani"],
            year=2017,
            doi="10.48550/arXiv.1706.03762",
            urls=["https://example.com/dead-paper"],
        )
        async with respx.mock:
            respx.get(
                "https://api.openalex.org/works/https://doi.org/10.48550/arXiv.1706.03762"
            ).mock(return_value=httpx.Response(200, json=_OPENALEX_WORK))
            respx.head("https://example.com/dead-paper").mock(
                return_value=httpx.Response(404)
            )
            adapter = OpenAlexAdapter()
            opts = self._opts(sources=[adapter], check_url=True)
            report = await verify_one(ref, opts)
            assert report.overall_verdict == Verdict.DEAD_URL
            await adapter.close()
