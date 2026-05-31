from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from refsift.config import get_settings
from refsift.models import Candidate, Reference
from refsift.sources.base import SourceAdapter

_EBASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_BIOMEDICAL_PATTERNS = [
    "nature", "lancet", "nejm", "new england journal", "plos", "cell",
    "bmj", "british medical journal", "jama", "annals of internal medicine",
    "circulation", "blood", "cancer", "gastroenterology", "hepatology",
    "neurology", "brain", "gut", "chest", "pediatrics",
]


def is_biomedical(ref: Reference) -> bool:
    if ref.pmid:
        return True
    venue = (ref.venue or "").lower()
    return any(p in venue for p in _BIOMEDICAL_PATTERNS)


class PubMedAdapter(SourceAdapter):
    name = "pubmed"

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

    def _base_params(self) -> dict:
        return {
            "tool": "refsift",
            "email": get_settings().mailto,
            "retmode": "json",
        }

    async def lookup_doi(self, doi: str) -> Candidate | None:
        client = await self._get_client()
        params = {**self._base_params(), "db": "pubmed", "term": f"{doi}[DOI]", "retmax": "1"}
        try:
            r = await client.get(f"{_EBASE}/esearch.fcgi", params=params)
            if r.status_code != 200:
                return None
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if ids:
                return await self._fetch_by_pmid(ids[0])
        except httpx.HTTPError:
            pass
        return None

    async def search(self, ref: Reference) -> list[Candidate]:
        if not ref.title and not ref.pmid:
            return []
        if ref.pmid:
            c = await self._fetch_by_pmid(ref.pmid)
            return [c] if c else []

        client = await self._get_client()
        term = f"{ref.title}[Title]"
        if ref.authors:
            term += f" AND {ref.authors[0].split()[-1]}[Author]"
        params = {**self._base_params(), "db": "pubmed", "term": term, "retmax": "5"}
        try:
            r = await client.get(f"{_EBASE}/esearch.fcgi", params=params)
            if r.status_code != 200:
                return []
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            candidates = []
            for pmid in ids[:5]:
                c = await self._fetch_by_pmid(pmid)
                if c:
                    candidates.append(c)
            return candidates
        except httpx.HTTPError:
            pass
        return []

    async def _fetch_by_pmid(self, pmid: str) -> Candidate | None:
        client = await self._get_client()
        params = {**self._base_params(), "db": "pubmed", "id": pmid, "rettype": "xml", "retmode": "xml"}
        try:
            r = await client.get(f"{_EBASE}/efetch.fcgi", params=params)
            if r.status_code != 200:
                return None
            return _parse_pubmed_xml(r.text, pmid)
        except (httpx.HTTPError, ET.ParseError):
            pass
        return None


def _parse_pubmed_xml(xml_text: str, pmid: str) -> Candidate | None:
    try:
        root = ET.fromstring(xml_text)
        article = root.find(".//PubmedArticle/MedlineCitation/Article")
        if article is None:
            return None

        title_el = article.find("ArticleTitle")
        title = title_el.text if title_el is not None else None

        authors = []
        for author in article.findall(".//Author"):
            last = author.find("LastName")
            fore = author.find("ForeName")
            if last is not None and last.text:
                name = last.text
                if fore is not None and fore.text:
                    name = f"{fore.text} {name}"
                authors.append(name)

        year = None
        pub_date = article.find(".//PubDate")
        if pub_date is not None:
            year_el = pub_date.find("Year")
            if year_el is not None and year_el.text:
                try:
                    year = int(year_el.text)
                except ValueError:
                    pass

        journal_el = article.find(".//Journal/Title")
        venue = journal_el.text if journal_el is not None else None

        doi = None
        for id_el in root.findall(".//ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text
                break

        return Candidate(
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            source="pubmed",
        )
    except ET.ParseError:
        return None
