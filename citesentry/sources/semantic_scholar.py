from __future__ import annotations

import asyncio
import re
import urllib.parse

import httpx

from citesentry.config import get_settings
from citesentry.models import Candidate, Reference
from citesentry.sources.base import SourceAdapter

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "title,authors,year,venue,externalIds,abstract"


def _paper_to_candidate(paper: dict) -> Candidate:
    authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
    ext = paper.get("externalIds", {})
    doi = ext.get("DOI")
    arxiv_id = ext.get("ArXiv")

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
            settings = get_settings()
            headers = {}
            if getattr(settings, "semantic_scholar_api_key", None):
                headers["x-api-key"] = settings.semantic_scholar_api_key
            self._client = httpx.AsyncClient(
                timeout=settings.request_timeout,
                headers=headers,
            )
        return self._client

    async def _get(self, url: str, params: dict) -> dict | None:
        """GET with automatic 429 retry (up to 3 attempts, exponential backoff)."""
        client = await self._get_client()
        for attempt in range(3):
            try:
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
                    continue
                return None
            except httpx.HTTPError:
                return None
        return None

    async def close(self) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()

    async def lookup_doi(self, doi: str) -> Candidate | None:
        data = await self._get(f"{_BASE}/paper/DOI:{doi}", {"fields": _FIELDS})
        return _paper_to_candidate(data) if data and data.get("title") else None

    async def lookup_arxiv_id(self, arxiv_id: str) -> Candidate | None:
        clean = re.sub(r"v\d+$", "", arxiv_id.strip())
        data = await self._get(f"{_BASE}/paper/arXiv:{clean}", {"fields": _FIELDS})
        return _paper_to_candidate(data) if data and data.get("title") else None

    async def lookup_url(self, url: str) -> Candidate | None:
        encoded = urllib.parse.quote(url, safe="")
        data = await self._get(f"{_BASE}/paper/URL:{encoded}", {"fields": _FIELDS})
        return _paper_to_candidate(data) if data and data.get("title") else None

    async def search(self, ref: Reference) -> list[Candidate]:
        if not ref.title:
            return []
        data = await self._get(
            f"{_BASE}/paper/search",
            {"query": ref.title, "fields": _FIELDS, "limit": "5"},
        )
        if data:
            return [_paper_to_candidate(p) for p in data.get("data", [])]
        return []
