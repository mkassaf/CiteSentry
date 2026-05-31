from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from citesentry.config import get_settings
from citesentry.models import Candidate, Reference
from citesentry.sources.base import SourceAdapter

_BASE = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _entry_to_candidate(entry: ET.Element) -> Candidate:
    def text(tag: str) -> str | None:
        el = entry.find(f"atom:{tag}", _NS)
        return el.text.strip() if el is not None and el.text else None

    title = text("title")
    if title:
        title = re.sub(r"\s+", " ", title)

    year = None
    published = text("published")
    if published:
        m = re.match(r"(\d{4})", published)
        if m:
            year = int(m.group(1))

    authors = []
    for author in entry.findall("atom:author", _NS):
        name_el = author.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    arxiv_id = None
    id_el = entry.find("atom:id", _NS)
    if id_el is not None and id_el.text:
        m = re.search(r"arxiv\.org/abs/([^\s/v]+)", id_el.text)
        if m:
            arxiv_id = m.group(1)

    doi = None
    doi_el = entry.find("{http://arxiv.org/schemas/atom}doi")
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    return Candidate(
        title=title,
        authors=authors,
        year=year,
        venue="arXiv",
        doi=doi,
        arxiv_id=arxiv_id,
        source="arxiv",
    )


class ArXivAdapter(SourceAdapter):
    name = "arxiv"

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
        # Handle arXiv-issued DOIs: 10.48550/arXiv.XXXX.XXXXX
        m = re.search(r"10\.48550/arXiv\.(\d+\.\d+)", doi, re.IGNORECASE)
        if m:
            return await self.lookup_arxiv_id(m.group(1))
        return None

    async def lookup_arxiv_id(self, arxiv_id: str) -> Candidate | None:
        client = await self._get_client()
        clean_id = re.sub(r"v\d+$", "", arxiv_id)
        try:
            r = await client.get(_BASE, params={"id_list": clean_id, "max_results": "1"})
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                entries = root.findall("atom:entry", _NS)
                if entries:
                    return _entry_to_candidate(entries[0])
        except (httpx.HTTPError, ET.ParseError):
            pass
        return None

    async def search(self, ref: Reference) -> list[Candidate]:
        if ref.arxiv_id:
            c = await self.lookup_arxiv_id(ref.arxiv_id)
            return [c] if c else []
        if not ref.title:
            return []
        client = await self._get_client()
        query = f"ti:{ref.title}"
        try:
            r = await client.get(
                _BASE, params={"search_query": query, "max_results": "5"}
            )
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                return [_entry_to_candidate(e) for e in root.findall("atom:entry", _NS)]
        except (httpx.HTTPError, ET.ParseError):
            pass
        return []
