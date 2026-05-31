from __future__ import annotations

import json
import pytest
import respx
import httpx

from citesentry.models import Reference
from citesentry.sources.openalex import OpenAlexAdapter
from citesentry.sources.crossref import CrossrefAdapter
from citesentry.sources.semantic_scholar import SemanticScholarAdapter


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

_CROSSREF_ITEM = {
    "DOI": "10.48550/arXiv.1706.03762",
    "title": ["Attention is all you need"],
    "author": [
        {"given": "Ashish", "family": "Vaswani"},
        {"given": "Noam", "family": "Shazeer"},
    ],
    "published-print": {"date-parts": [[2017]]},
    "container-title": ["Advances in Neural Information Processing Systems"],
}

_SS_PAPER = {
    "paperId": "abc123",
    "title": "Attention is all you need",
    "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
    "year": 2017,
    "venue": "NeurIPS",
    "externalIds": {"DOI": "10.48550/arXiv.1706.03762"},
    "abstract": "We propose a new simple network architecture...",
}


@pytest.mark.asyncio
class TestOpenAlexAdapter:
    async def test_lookup_doi_success(self):
        doi = "10.48550/arXiv.1706.03762"
        async with respx.mock:
            respx.get(f"https://api.openalex.org/works/https://doi.org/{doi}").mock(
                return_value=httpx.Response(200, json=_OPENALEX_WORK)
            )
            adapter = OpenAlexAdapter()
            cand = await adapter.lookup_doi(doi)
            assert cand is not None
            assert cand.title == "Attention is all you need"
            assert cand.year == 2017
            assert any("Vaswani" in a for a in cand.authors)
            await adapter.close()

    async def test_lookup_doi_not_found(self):
        doi = "10.9999/nonexistent"
        async with respx.mock:
            respx.get(f"https://api.openalex.org/works/https://doi.org/{doi}").mock(
                return_value=httpx.Response(404, json={"error": "not found"})
            )
            adapter = OpenAlexAdapter()
            cand = await adapter.lookup_doi(doi)
            assert cand is None
            await adapter.close()

    async def test_search_returns_candidates(self):
        ref = Reference(title="Attention is all you need", year=2017)
        async with respx.mock:
            respx.get("https://api.openalex.org/works").mock(
                return_value=httpx.Response(200, json={"results": [_OPENALEX_WORK]})
            )
            adapter = OpenAlexAdapter()
            results = await adapter.search(ref)
            assert len(results) >= 1
            assert results[0].title == "Attention is all you need"
            await adapter.close()

    async def test_search_empty_title_returns_nothing(self):
        ref = Reference()
        adapter = OpenAlexAdapter()
        results = await adapter.search(ref)
        assert results == []
        await adapter.close()


@pytest.mark.asyncio
class TestCrossrefAdapter:
    async def test_lookup_doi_success(self):
        doi = "10.48550/arXiv.1706.03762"
        async with respx.mock:
            respx.get(f"https://api.crossref.org/works/{doi}").mock(
                return_value=httpx.Response(200, json={"message": _CROSSREF_ITEM})
            )
            adapter = CrossrefAdapter()
            cand = await adapter.lookup_doi(doi)
            assert cand is not None
            assert cand.doi == doi
            assert cand.year == 2017
            await adapter.close()

    async def test_search(self):
        ref = Reference(title="Attention is all you need")
        async with respx.mock:
            respx.get("https://api.crossref.org/works").mock(
                return_value=httpx.Response(200, json={"message": {"items": [_CROSSREF_ITEM]}})
            )
            adapter = CrossrefAdapter()
            results = await adapter.search(ref)
            assert len(results) >= 1
            await adapter.close()


@pytest.mark.asyncio
class TestSemanticScholarAdapter:
    async def test_lookup_doi(self):
        doi = "10.48550/arXiv.1706.03762"
        async with respx.mock:
            respx.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}").mock(
                return_value=httpx.Response(200, json=_SS_PAPER)
            )
            adapter = SemanticScholarAdapter()
            cand = await adapter.lookup_doi(doi)
            assert cand is not None
            assert "Attention" in (cand.title or "")
            await adapter.close()

    async def test_search(self):
        ref = Reference(title="Attention is all you need")
        async with respx.mock:
            respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
                return_value=httpx.Response(200, json={"data": [_SS_PAPER]})
            )
            adapter = SemanticScholarAdapter()
            results = await adapter.search(ref)
            assert len(results) >= 1
            await adapter.close()
