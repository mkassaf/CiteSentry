from __future__ import annotations

import re

import httpx

from refsift.config import get_settings
from refsift.models import Candidate, Reference
from refsift.sources.base import SourceAdapter

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "title,authors,year,venue,externalIds,abstract"


def _paper_to_candidate(paper: dict) -> Candidate:
    authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
    ext = paper.get("externalIds", {})
    doi = ext.get("DOI")
    arxiv_id = ext.get("ArXiv")

    abstract = paper.get("abstract", "")

    return Candidate(
        title=paper.get("title"),
        authors=authors,
        year=paper.get("year"),
        venue=paper.get("venue"),
        doi=doi,
        arxiv_id=arxiv_id,
        source="semantic_scholar",
    )


class SemanticScholarAdapter(SourceAdapter):
    name = "semantic_scholar"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=get_settings().request_timeout)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()

    async def lookup_doi(self, doi: str) -> Candidate | None:
        client = await self._get_client()
        url = f"{_BASE}/paper/DOI:{doi}"
        try:
            r = await client.get(url, params={"fields": _FIELDS})
            if r.status_code == 200:
                return _paper_to_candidate(r.json())
        except httpx.HTTPError:
            pass
        return None

    async def search(self, ref: Reference) -> list[Candidate]:
        if not ref.title:
            return []
        client = await self._get_client()
        params = {"query": ref.title, "fields": _FIELDS, "limit": "5"}
        try:
            r = await client.get(f"{_BASE}/paper/search", params=params)
            if r.status_code == 200:
                papers = r.json().get("data", [])
                return [_paper_to_candidate(p) for p in papers]
        except httpx.HTTPError:
            pass
        return []
