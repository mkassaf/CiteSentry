from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from citesentry.models import Reference

_GROBID_API = "https://kermitt2-grobid.hf.space/api"
_NS = "http://www.tei-c.org/ns/1.0"


def _tag(name: str) -> str:
    return f"{{{_NS}}}{name}"


def _parse_biblstruct(bib: ET.Element) -> Reference | None:
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    urls: list[str] = []

    # Title: prefer analytic title (article/chapter), fall back to monogr (book/proceedings)
    for parent_tag in ["analytic", "monogr"]:
        parent = bib.find(_tag(parent_tag))
        if parent is None:
            continue
        for t in parent.findall(_tag("title")):
            if t.get("level") in ("a", "m") and t.text:
                title = t.text.strip()
                break
        if title:
            break

    # Authors
    for author in bib.iter(_tag("author")):
        persname = author.find(_tag("persName"))
        if persname is None:
            continue
        surname_elem = persname.find(_tag("surname"))
        forename_elem = persname.find(_tag("forename"))
        surname = (surname_elem.text or "").strip() if surname_elem is not None else ""
        forename = (forename_elem.text or "").strip() if forename_elem is not None else ""
        if surname:
            authors.append(f"{surname}, {forename}" if forename else surname)

    # Year from imprint date
    for date in bib.iter(_tag("date")):
        m = re.search(r'\b(19|20)\d{2}\b', date.get("when", ""))
        if m:
            year = int(m.group())
            break

    # Identifiers
    for idno in bib.iter(_tag("idno")):
        id_type = idno.get("type", "").lower()
        val = (idno.text or "").strip()
        if not val:
            continue
        if id_type == "doi":
            doi = val
        elif id_type == "arxiv":
            arxiv_id = re.sub(r'^arxiv:', '', val, flags=re.IGNORECASE)

    # URLs from ptr elements
    for ptr in bib.iter(_tag("ptr")):
        target = ptr.get("target", "")
        if target.startswith("http") and "doi.org" not in target:
            urls.append(target)

    if not title and not doi and not arxiv_id:
        return None

    parts: list[str] = []
    if authors:
        parts.append(", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""))
    if title:
        parts.append(title)
    if year:
        parts.append(f"({year})")

    return Reference(
        raw=" ".join(parts),
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        arxiv_id=arxiv_id,
        urls=urls,
    )


def _parse_tei_xml(xml_text: str) -> list[Reference]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [r for bib in root.iter(_tag("biblStruct")) if (r := _parse_biblstruct(bib))]


def parse_pdf_via_grobid(path: Path, api_url: str = _GROBID_API) -> list[Reference] | None:
    """
    Extract references from a PDF using the GROBID REST API.
    Uses the public HuggingFace Spaces instance by default.
    Returns None if GROBID is unavailable or the response is empty.
    """
    try:
        import httpx
    except ImportError:
        return None

    try:
        with httpx.Client(timeout=90.0) as client:
            with open(path, "rb") as f:
                resp = client.post(
                    f"{api_url}/processReferences",
                    files={"input": (path.name, f, "application/pdf")},
                    data={"consolidateReferences": "0"},
                )
        if resp.status_code != 200:
            return None
        refs = _parse_tei_xml(resp.text)
        return refs if refs else None
    except Exception:
        return None
