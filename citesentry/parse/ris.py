from __future__ import annotations

import re

from citesentry.models import Reference


def parse_ris(text: str) -> list[Reference]:
    try:
        import rispy
    except ImportError as e:
        raise ImportError("rispy is required: pip install rispy") from e

    entries = rispy.loads(text)
    refs = []
    for entry in entries:
        title = entry.get("title") or entry.get("primary_title")
        if isinstance(title, list):
            title = title[0] if title else None

        authors = entry.get("authors") or entry.get("first_authors") or []
        if isinstance(authors, str):
            authors = [authors]

        year = None
        year_raw = entry.get("year") or entry.get("publication_year") or ""
        m = re.search(r"\d{4}", str(year_raw))
        if m:
            year = int(m.group())

        venue = (
            entry.get("journal_name")
            or entry.get("secondary_title")
            or entry.get("publisher")
        )

        doi = entry.get("doi")
        if doi and isinstance(doi, list):
            doi = doi[0]

        urls = []
        url = entry.get("url") or entry.get("link")
        if url:
            if isinstance(url, list):
                urls = url
            else:
                urls = [url]

        arxiv_id = None
        for u in urls:
            m2 = re.search(r"arxiv\.org/abs/([^\s/]+)", u)
            if m2:
                arxiv_id = m2.group(1)
                break

        pmid = entry.get("accession_number")
        if pmid and not re.match(r"^\d+$", str(pmid)):
            pmid = None

        raw = f"{title or ''} {' '.join(authors[:2])} {year or ''}".strip()

        refs.append(
            Reference(
                raw=raw,
                title=title,
                authors=[str(a) for a in authors],
                year=year,
                venue=str(venue) if venue else None,
                doi=str(doi) if doi else None,
                arxiv_id=arxiv_id,
                urls=urls,
                pmid=str(pmid) if pmid else None,
            )
        )
    return refs
