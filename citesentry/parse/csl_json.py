from __future__ import annotations

import json
import re

from citesentry.models import Reference


def _name(contributor: dict) -> str:
    family = contributor.get("family", "")
    given = contributor.get("given", "")
    lit = contributor.get("literal", "")
    if family:
        return f"{given} {family}".strip() if given else family
    return lit


def _year_from_date(date_obj: dict | None) -> int | None:
    if not date_obj:
        return None
    parts = date_obj.get("date-parts", [[]])
    if parts and parts[0]:
        try:
            return int(parts[0][0])
        except (ValueError, TypeError):
            pass
    raw = date_obj.get("raw", "")
    m = re.search(r"\d{4}", str(raw))
    return int(m.group()) if m else None


def parse_csl_json(text: str) -> list[Reference]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]

    refs = []
    for item in data:
        title = item.get("title")

        authors = []
        for field in ("author", "editor"):
            contributors = item.get(field, [])
            if contributors:
                authors = [_name(c) for c in contributors if _name(c)]
                break

        year = _year_from_date(item.get("issued")) or _year_from_date(item.get("accessed"))

        venue = (
            item.get("container-title")
            or item.get("publisher")
            or item.get("collection-title")
        )

        doi = item.get("DOI")

        urls = []
        url = item.get("URL")
        if url:
            urls = [url]

        arxiv_id = None
        for u in urls:
            m = re.search(r"arxiv\.org/abs/([^\s/]+)", u)
            if m:
                arxiv_id = m.group(1)
                break

        pmid = item.get("PMID")

        raw = f"{title or ''} {' '.join(authors[:2])} {year or ''}".strip()

        refs.append(
            Reference(
                raw=raw,
                title=title,
                authors=authors,
                year=year,
                venue=str(venue) if venue else None,
                doi=doi,
                arxiv_id=arxiv_id,
                urls=urls,
                pmid=str(pmid) if pmid else None,
            )
        )
    return refs
