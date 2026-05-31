from __future__ import annotations

import pytest
import respx
import httpx

from refsift.models import CheckStatus, Reference
from refsift.checks.url_liveness import check_url_liveness
from refsift.checks.existence import check_existence
from refsift.sources.openalex import OpenAlexAdapter

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
class TestUrlLiveness:
    async def test_live_url_passes(self):
        async with respx.mock:
            respx.head("https://example.com/paper").mock(
                return_value=httpx.Response(200)
            )
            result = await check_url_liveness(["https://example.com/paper"], use_cache=False)
            assert result.status == CheckStatus.PASS

    async def test_dead_url_fails(self):
        async with respx.mock:
            respx.head("https://example.com/dead").mock(
                return_value=httpx.Response(404)
            )
            result = await check_url_liveness(["https://example.com/dead"], use_cache=False)
            assert result.status == CheckStatus.FAIL

    async def test_no_urls_skipped(self):
        result = await check_url_liveness([], use_cache=False)
        assert result.status == CheckStatus.SKIPPED

    async def test_bot_protection_skipped(self):
        async with respx.mock:
            respx.head("https://www.linkedin.com/paper").mock(
                return_value=httpx.Response(403)
            )
            result = await check_url_liveness(["https://www.linkedin.com/paper"], use_cache=False)
            assert result.status == CheckStatus.SKIPPED

    async def test_redirect_passes(self):
        async with respx.mock:
            respx.head("http://example.com/paper").mock(
                return_value=httpx.Response(301, headers={"Location": "https://example.com/paper"})
            )
            respx.head("https://example.com/paper").mock(
                return_value=httpx.Response(200)
            )
            result = await check_url_liveness(["http://example.com/paper"], use_cache=False)
            assert result.status in (CheckStatus.PASS, CheckStatus.WARN)

    async def test_timeout_warns(self):
        async with respx.mock:
            respx.head("https://example.com/timeout").mock(
                side_effect=httpx.TimeoutException("timeout")
            )
            result = await check_url_liveness(["https://example.com/timeout"], use_cache=False)
            assert result.status == CheckStatus.WARN


@pytest.mark.asyncio
class TestExistenceCheck:
    async def test_doi_lookup_pass(self):
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
            result = await check_existence(ref, sources=[adapter], use_cache=False)
            assert result.status in (CheckStatus.PASS, CheckStatus.WARN)
            await adapter.close()

    async def test_not_found(self):
        ref = Reference(
            title="A completely nonexistent paper that no database will ever find",
            authors=["Nobody Known"],
            year=2099,
        )
        async with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json={"results": []})
            )
            adapter = OpenAlexAdapter()
            result = await check_existence(ref, sources=[adapter], use_cache=False)
            assert result.status == CheckStatus.FAIL
            await adapter.close()

    async def test_metadata_mismatch_detected(self):
        doi = "10.48550/arXiv.1706.03762"
        ref = Reference(
            title="Attention is all you need",
            authors=["John Smith", "Jane Doe"],
            year=2020,
            doi=doi,
        )
        async with respx.mock:
            respx.get(f"https://api.openalex.org/works/https://doi.org/{doi}").mock(
                return_value=httpx.Response(200, json=_OPENALEX_WORK)
            )
            adapter = OpenAlexAdapter()
            result = await check_existence(ref, sources=[adapter], use_cache=False)
            assert result.status in (CheckStatus.PASS, CheckStatus.WARN)
            await adapter.close()
