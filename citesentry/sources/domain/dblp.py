from __future__ import annotations

import re

import httpx

from citesentry.config import get_settings
from citesentry.models import Candidate, Reference
from citesentry.sources.base import SourceAdapter

_BASE = "https://dblp.org/search/publ/api"

_CS_PATTERNS = [
    "neurips", "nips", "icml", "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl",
    "iclr", "vldb", "sigmod", "sigkdd", "kdd", "icde", "www", "iswc",
    "aaai", "ijcai", "uai", "aistats", "sosp", "osdi", "eurosys", "nsdi",
    "pldi", "popl", "oopsla", "asplos", "isca", "micro", "hpca",
    "ieee transactions", "acm transactions", "journal of machine learning",
    "journal of artificial intelligence", "artificial intelligence",
]


def is_cs(ref: Reference) -> bool:
    if ref.arxiv_id:
        return True
    venue = (ref.venue or "").lower()
    return any(p in venue for p in _CS_PATTERNS)


def _hit_to_candidate(hit: dict) -> Candidate:
    info = hit.get("info", {})
    authors_data = info.get("authors", {}).get("author", [])
    if isinstance(authors_data, str):
        authors = [authors_data]
    elif isinstance(authors_data, dict):
        authors = [authors_data.get("text", "")]
    else:
        authors = [a.get("text", "") for a in authors_data if isinstance(a, dict)]

    year_str = info.get("year")
    year = int(year_str) if year_str and year_str.isdigit() else None

    doi = info.get("doi")

    return Candidate(
        title=info.get("title"),
        authors=[a for a in authors if a],
        year=year,
        venue=info.get("venue"),
        doi=doi,
        source="dblp",
    )


class DBLPAdapter(SourceAdapter):
    name = "dblp"

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
        return None

    async def search(self, ref: Reference) -> list[Candidate]:
        if not ref.title:
            return []
        client = await self._get_client()
        params = {"q": ref.title, "format": "json", "h": "5"}
        try:
            r = await client.get(_BASE, params=params)
            if r.status_code == 200:
                hits = r.json().get("result", {}).get("hits", {}).get("hit", [])
                return [_hit_to_candidate(h) for h in hits]
        except httpx.HTTPError:
            pass
        return []
