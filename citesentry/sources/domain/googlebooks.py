from __future__ import annotations

import httpx

from citesentry.config import get_settings
from citesentry.models import Candidate, Reference
from citesentry.sources.base import SourceAdapter

_BASE = "https://www.googleapis.com/books/v1/volumes"

# Keywords that suggest a reference is a book rather than a paper
_BOOK_SIGNALS = [
    "springer", "wiley", "elsevier", "morgan kaufmann", "o'reilly", "oreilly",
    "mit press", "cambridge university press", "oxford university press",
    "addison-wesley", "pearson", "mcgraw-hill", "isbn",
    "edition", "2nd ed", "3rd ed", "4th ed", "chapter", "textbook",
]


def is_book(ref: Reference) -> bool:
    text = " ".join(filter(None, [ref.venue, ref.raw])).lower()
    return any(sig in text for sig in _BOOK_SIGNALS)


def _item_to_candidate(item: dict) -> Candidate:
    info = item.get("volumeInfo", {})
    authors_raw = info.get("authors", [])
    year = None
    published = info.get("publishedDate", "")
    if published:
        import re
        m = re.search(r"\b(19|20)\d{2}\b", published)
        if m:
            year = int(m.group())

    isbn_list = info.get("industryIdentifiers", [])
    doi = None
    for ident in isbn_list:
        if ident.get("type") in ("ISBN_13", "ISBN_10"):
            doi = f"ISBN:{ident.get('identifier', '')}"
            break

    return Candidate(
        title=info.get("title"),
        authors=authors_raw,
        year=year,
        venue=info.get("publisher"),
        doi=doi,
        source="google_books",
    )


class GoogleBooksAdapter(SourceAdapter):
    name = "google_books"

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
        query = ref.title
        if ref.authors:
            first = ref.authors[0].strip()
            surname = first.split(",")[0].strip() if "," in first else first.split()[-1].strip()
            query += f" {surname}"
        params: dict = {"q": query, "maxResults": 5, "printType": "books"}
        api_key = getattr(get_settings(), "google_books_api_key", None)
        if api_key:
            params["key"] = api_key
        try:
            r = await client.get(_BASE, params=params)
            if r.status_code == 200:
                items = r.json().get("items", [])
                return [_item_to_candidate(i) for i in items]
        except httpx.HTTPError:
            pass
        return []
