from __future__ import annotations

import re

from refsift.models import Reference


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"[{}]", "", s).strip()
    return s or None


def _parse_authors(author_str: str) -> list[str]:
    parts = re.split(r"\s+and\s+", author_str, flags=re.IGNORECASE)
    result = []
    for p in parts:
        cleaned = _clean(p)
        if cleaned:
            result.append(cleaned)
    return result


def parse_bibtex(text: str) -> list[Reference]:
    try:
        import bibtexparser
    except ImportError as e:
        raise ImportError("bibtexparser is required: pip install bibtexparser") from e

    db = bibtexparser.loads(text)
    refs = []
    for entry in db.entries:
        title = _clean(entry.get("title"))
        author_raw = entry.get("author", "")
        authors = _parse_authors(author_raw) if author_raw else []

        year = None
        year_raw = entry.get("year", "")
        m = re.search(r"\d{4}", year_raw)
        if m:
            year = int(m.group())

        venue = None
        for venue_key in ("journal", "booktitle", "publisher", "school"):
            v = _clean(entry.get(venue_key))
            if v:
                venue = v
                break

        doi = _clean(entry.get("doi"))

        arxiv_id = None
        eprint = entry.get("eprint", "")
        if eprint:
            m2 = re.match(r"(\d{4}\.\d+|[a-z\-]+/\d+)", eprint)
            if m2:
                arxiv_id = m2.group(1)
        url_field = entry.get("url", "")
        if not arxiv_id and "arxiv.org" in url_field:
            m3 = re.search(r"arxiv\.org/abs/([^\s/]+)", url_field)
            if m3:
                arxiv_id = m3.group(1)

        urls = []
        if url_field and "arxiv.org" not in url_field:
            urls = [url_field]

        pmid = _clean(entry.get("pmid"))

        raw_parts = [title or "", " ".join(authors[:2]), str(year or ""), venue or ""]
        raw = " ".join(p for p in raw_parts if p).strip()

        refs.append(
            Reference(
                raw=raw,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                arxiv_id=arxiv_id,
                urls=urls,
                pmid=pmid,
            )
        )
    return refs
