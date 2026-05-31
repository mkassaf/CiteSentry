from __future__ import annotations

import httpx

from refsift.config import get_settings
from refsift.models import Candidate, Reference
from refsift.sources.base import SourceAdapter

_BASE = "https://api.unpaywall.org/v2"


class UnpaywallAdapter(SourceAdapter):
    name = "unpaywall"

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
        return []

    async def get_oa_url(self, doi: str) -> str | None:
        """Return best OA full-text URL for a DOI, or None."""
        client = await self._get_client()
        mailto = get_settings().mailto
        try:
            r = await client.get(f"{_BASE}/{doi}", params={"email": mailto})
            if r.status_code == 200:
                data = r.json()
                best = data.get("best_oa_location") or {}
                return best.get("url_for_pdf") or best.get("url")
        except httpx.HTTPError:
            pass
        return None
