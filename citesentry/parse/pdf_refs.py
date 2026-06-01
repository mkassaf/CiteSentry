from __future__ import annotations

import re
from pathlib import Path

from citesentry.models import Reference

_HEADING_RE = re.compile(
    r"^\s*(references|bibliography|works cited|literature cited|cited works)\s*$",
    re.IGNORECASE,
)

_END_SECTION_RE = re.compile(
    r"^\s*(appendix|about the authors?|acknowledgements?|acknowledgments?|author contributions?)\s*\.?\s*$",
    re.IGNORECASE,
)


def _extract_text(path: Path) -> str:
    # PyMuPDF handles multi-column layouts and line order far better than pdfminer
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError as e:
        raise ImportError("Install pymupdf or pdfminer.six: pip install pymupdf") from e


def _find_ref_section(text: str) -> str | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line.strip()):
            ref_lines = lines[i + 1:]
            end = len(ref_lines)
            for j, rl in enumerate(ref_lines):
                if j > 5 and _END_SECTION_RE.match(rl.strip()):
                    end = j
                    break
            return "\n".join(ref_lines[:end])
    return None


def parse_pdf_refs(path: Path, use_grobid: bool = True, llm_client: object | None = None) -> list[Reference]:
    if use_grobid:
        try:
            from citesentry.config import get_settings
            from citesentry.parse.grobid import parse_pdf_via_grobid
            api_url = get_settings().grobid_api_url
            if api_url:
                refs = parse_pdf_via_grobid(path, api_url=api_url)
                if refs:
                    return refs
        except Exception:
            pass

    from citesentry.parse.plaintext import parse_plaintext
    text = _extract_text(path)
    ref_section = _find_ref_section(text)
    if ref_section is None:
        ref_section = text
    return parse_plaintext(ref_section)
