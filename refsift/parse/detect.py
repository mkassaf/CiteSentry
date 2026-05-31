from __future__ import annotations

import re
from pathlib import Path

from refsift.models import Reference

_DOI_LINE_RE = re.compile(r"^\s*10\.\d{4,}/\S+\s*$")


def auto_parse(source: str | Path, format_hint: str | None = None) -> list[Reference]:
    """Detect format and parse references from a file path or raw string."""
    text: str
    extension: str | None = None

    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and len(source) < 300):
        path = Path(source) if isinstance(source, str) else source
        if path.exists():
            extension = path.suffix.lower()
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = str(source)
    else:
        text = source

    if format_hint:
        return _dispatch(text, format_hint, path=None)

    if extension:
        fmt = {
            ".bib": "bibtex",
            ".ris": "ris",
            ".json": "csl_json",
            ".nbib": "nbib",
            ".pdf": "pdf",
        }.get(extension)
        if fmt:
            actual_path = Path(source) if isinstance(source, (str, Path)) and Path(source).exists() else None
            return _dispatch(text, fmt, path=actual_path)

    return _sniff_and_parse(text)


def _sniff_and_parse(text: str) -> list[Reference]:
    stripped = text.strip()

    stripped_lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    if stripped_lines and all(_DOI_LINE_RE.match(l) for l in stripped_lines[:5]):
        from refsift.parse.doi_list import parse_doi_list
        return parse_doi_list(text)

    if any(l.startswith("@") and re.match(r"@\w+\s*{", l) for l in stripped_lines[:10]):
        from refsift.parse.bibtex import parse_bibtex
        return parse_bibtex(text)

    if any(l.startswith("TY  -") for l in stripped_lines[:5]):
        from refsift.parse.ris import parse_ris
        return parse_ris(text)

    if any(l.startswith("PMID-") for l in stripped_lines[:5]):
        from refsift.parse.nbib import parse_nbib
        return parse_nbib(text)

    if stripped.startswith("[{") or stripped.startswith("[  {"):
        try:
            import json
            json.loads(stripped)
            from refsift.parse.csl_json import parse_csl_json
            return parse_csl_json(text)
        except (json.JSONDecodeError, Exception):
            pass

    from refsift.parse.plaintext import parse_plaintext
    return parse_plaintext(text)


def _dispatch(text: str, fmt: str, path: Path | None = None) -> list[Reference]:
    if fmt == "bibtex":
        from refsift.parse.bibtex import parse_bibtex
        return parse_bibtex(text)
    elif fmt == "ris":
        from refsift.parse.ris import parse_ris
        return parse_ris(text)
    elif fmt == "csl_json":
        from refsift.parse.csl_json import parse_csl_json
        return parse_csl_json(text)
    elif fmt == "nbib":
        from refsift.parse.nbib import parse_nbib
        return parse_nbib(text)
    elif fmt == "doi_list":
        from refsift.parse.doi_list import parse_doi_list
        return parse_doi_list(text)
    elif fmt == "pdf":
        if path and path.exists():
            from refsift.parse.pdf_refs import parse_pdf_refs
            return parse_pdf_refs(path)
        return []
    else:
        from refsift.parse.plaintext import parse_plaintext
        return parse_plaintext(text)
