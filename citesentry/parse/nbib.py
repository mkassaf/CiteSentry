from __future__ import annotations

import re

from citesentry.models import Reference

_FIELD_RE = re.compile(r"^([A-Z]{2,4})\s*-\s*(.*)$")


def parse_nbib(text: str) -> list[Reference]:
    entries: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    last_tag = None

    for line in text.splitlines():
        line = line.rstrip()
        m = _FIELD_RE.match(line)
        if m:
            tag, value = m.group(1), m.group(2).strip()
            last_tag = tag
            if tag not in current:
                current[tag] = []
            current[tag].append(value)
            if tag == "ER":
                if current:
                    entries.append(current)
                current = {}
                last_tag = None
        elif last_tag and line.startswith("      "):
            current[last_tag][-1] += " " + line.strip()

    if current:
        entries.append(current)

    refs = []
    for entry in entries:
        if not entry:
            continue

        def first(tag: str) -> str | None:
            vals = entry.get(tag, [])
            return vals[0] if vals else None

        def all_vals(tag: str) -> list[str]:
            return entry.get(tag, [])

        title = first("TI") or first("T1")
        authors = all_vals("AU") or all_vals("FAU")
        pmid = first("PMID")

        year = None
        dp = first("DP")
        if dp:
            m2 = re.search(r"\d{4}", dp)
            if m2:
                year = int(m2.group())

        venue = first("JT") or first("SO") or first("T2")
        doi = first("LID")
        if doi and "[doi]" in doi.lower():
            doi = re.sub(r"\s*\[doi\]", "", doi, flags=re.IGNORECASE).strip()
        elif doi and not doi.startswith("10."):
            doi = None

        urls: list[str] = []
        for ab_tag in ("AID",):
            for v in all_vals(ab_tag):
                if v.startswith("http"):
                    urls.append(v)

        abstract = first("AB")

        raw = f"{title or ''} {' '.join(authors[:2])} {year or ''}".strip()

        refs.append(
            Reference(
                raw=raw,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                urls=urls,
                pmid=pmid,
            )
        )
    return refs
