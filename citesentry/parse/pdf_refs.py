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
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError as e:
        raise ImportError("pdfminer.six is required: pip install pdfminer.six") from e


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


def parse_pdf_refs(path: Path) -> list[Reference]:
    from citesentry.parse.plaintext import parse_plaintext

    text = _extract_text(path)
    ref_section = _find_ref_section(text)
    if ref_section is None:
        ref_section = text

    return parse_plaintext(ref_section)
