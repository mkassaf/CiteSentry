from __future__ import annotations

import re

import httpx

from citesentry.config import get_settings
from citesentry.models import Candidate, Reference
from citesentry.sources.base import SourceAdapter

_BASE = "https://api.openalex.org"


def _work_to_candidate(work: dict) -> Candidate:
    authors = []
    for a in work.get("authorships", []):
        name = a.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    doi = work.get("doi")
    if doi:
        doi = re.sub(r"^https?://doi\.org/", "", doi)

    ids = work.get("ids", {})
    arxiv_id = None
    arxiv_url = ids.get("arxiv", "")
    if arxiv_url:
        m = re.search(r"arxiv\.org/abs/([^\s/]+)", arxiv_url)
        if m:
            arxiv_id = m.group(1)

    venue = None
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    venue = src.get("display_name")

    pub_year = work.get("publication_year")

    return Candidate(
        title=work.get("title"),
        authors=authors,
        year=pub_year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        source="openalex",
    )


class OpenAlexAdapter(SourceAdapter):
    name = "openalex"

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

    def _mailto_params(self) -> dict:
        return {"mailto": get_settings().mailto}

    async def lookup_doi(self, doi: str) -> Candidate | None:
        client = await self._get_client()
        url = f"{_BASE}/works/https://doi.org/{doi}"
        try:
            r = await client.get(url, params=self._mailto_params())
            if r.status_code == 200:
                return _work_to_candidate(r.json())
        except httpx.HTTPError:
            pass
        return None

    async def search(self, ref: Reference) -> list[Candidate]:
        if not ref.title:
            return []
        client = await self._get_client()
        params = {
            **self._mailto_params(),
            "search": ref.title,
            "per-page": "5",
        }
        if ref.year:
            params["filter"] = f"publication_year:{ref.year}"
        try:
            r = await client.get(f"{_BASE}/works", params=params)
            if r.status_code == 200:
                results = r.json().get("results", [])
                return [_work_to_candidate(w) for w in results]
        except httpx.HTTPError:
            pass
        return []
