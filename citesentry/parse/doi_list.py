from __future__ import annotations

import re

from citesentry.models import Reference

_DOI_RE = re.compile(r"10\.\d{4,}/\S+")


def parse_doi_list(text: str) -> list[Reference]:
    refs = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _DOI_RE.search(line)
        if m:
            doi = m.group().rstrip(".,;)")
            refs.append(Reference(raw=line, doi=doi))
    return refs
