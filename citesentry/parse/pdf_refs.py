from __future__ import annotations

import re
from pathlib import Path

from citesentry.models import Reference

# ---------------------------------------------------------------------------
# Bibliography heading patterns (ordered most-specific → most-general).
# Adapted from refchecker (markrussinovich/refchecker).
# Each pattern anchors to a newline so we don't match "cross-references" etc.
# They tolerate PDF extraction artifacts: tabs, page numbers, non-breaking
# spaces (\xa0), and extra digits that appear before/after the heading.
# ---------------------------------------------------------------------------
_BIB_HEADER_PATTERNS = [
    # Numbered section header: "7. References", "12 References"
    re.compile(
        r'\n[\s\d\t\r\xa0]*\d+\.?\s+(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography)\s*:?\s*\n',
    ),
    # Standard headings with leading PDF noise (tabs, page nums, \xa0)
    re.compile(
        r'\n[\s\t\r\xa0\d]*'
        r'(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography|'
        r'WORKS\s+CITED|Works\s+Cited|LITERATURE\s+CITED|Literature\s+Cited|'
        r'CITED\s+WORKS|Cited\s+Works)'
        r'\s*:?\s*(?:\d*\s*)\n',
    ),
    # Heading immediately followed by a reference (no trailing blank line)
    re.compile(
        r'\n[\s\t\r\xa0\d]*'
        r'(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography)'
        r'\s*:?\s+(?=[A-Z\d\[\(])',
    ),
    # Inline line-number artefact: "559\tReferences 560\t"
    re.compile(r'\d+\s*\t\s*(?:References|REFERENCES)\s*\d*\s*\t'),
    # Heading preceded by spaces/line-nums without a leading newline
    re.compile(
        r'\s(?:REFERENCES|References|BIBLIOGRAPHY|Bibliography)\s*:?\s+(?=\d|[A-Z])',
    ),
]

# Markdown heading markers (from marker's PDF->Markdown output, e.g. "## References").
# Stripped before heading-pattern matching so marker's output is handled the same
# way as plain extracted text, instead of duplicating every pattern above with a
# leading "#*" alternative.
_MD_HEADING_RE = re.compile(r'^[ \t]{0,3}#{1,6}[ \t]+', re.MULTILINE)

# Sections that mark the end of a bibliography
_END_SECTION_RE = re.compile(
    r'^\s*(?:'
    r'APPENDIX|Appendix|'
    r'SUPPLEMENTARY\s+MATERIAL|Supplementary\s+Material|'
    r'SUPPLEMENTAL\s+MATERIAL|Supplemental\s+Material|'
    r'ACKNOWLEDGMENTS?|Acknowledgments?|ACKNOWLEDGEMENTS?|Acknowledgements?|'
    r'AUTHOR\s+CONTRIBUTIONS?|Author\s+Contributions?|'
    r'FUNDING|Funding|'
    r'ETHICS\s+STATEMENT|Ethics\s+Statement|'
    r'CONFLICT\s+OF\s+INTEREST|Conflict\s+of\s+Interest|'
    r'DATA\s+AVAILABILITY|Data\s+Availability|'
    r'ABOUT\s+THE\s+AUTHORS?|About\s+the\s+Authors?|'
    r'INDEX|Glossary'
    r')\s*\.?\s*$',
    re.IGNORECASE,
)


def _extract_text(path: Path) -> str:
    """
    Extract full text from a PDF.

    If CITESENTRY_USE_MARKER is set, tries marker (PDF -> Markdown) first for
    better layout/heading fidelity on hard documents. Otherwise (or if marker
    isn't installed / fails) falls back to three backends in order:
    PyMuPDF (best multi-column support) → pypdf → pdfminer.
    """
    from citesentry.config import get_settings
    if get_settings().use_marker:
        from citesentry.parse.marker_pdf import convert_pdf_to_markdown
        text = convert_pdf_to_markdown(path)
        if text:
            return text

    # 1. PyMuPDF
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n".join(pages)
    except ImportError:
        pass

    # 2. pypdf (used by refchecker)
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            try:
                text = page.extract_text()
                if text:
                    parts.append(text)
            except Exception:
                continue
        return "\n".join(parts)
    except ImportError:
        pass

    # 3. pdfminer (fallback)
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError as e:
        raise ImportError(
            "No PDF backend found. Install one of: pymupdf, pypdf, pdfminer.six"
        ) from e


def _find_ref_section(text: str) -> str | None:
    """
    Locate the bibliography/references section in extracted PDF text.

    Strategy (adapted from refchecker):
    - Try each of the heading patterns above
    - Skip matches in the first 20% of the document (avoids "see references" etc.)
    - Among all matches, keep the LAST one (bibliography is near the end)
    - Trim the section at the first known post-bibliography heading
    """
    n = len(text)
    min_pos = int(n * 0.20)   # ignore the first 20 % of the document

    best_match = None
    for pattern in _BIB_HEADER_PATTERNS:
        for m in pattern.finditer(text):
            if m.start() < min_pos:
                continue
            if best_match is None or m.start() > best_match.start():
                best_match = m

    # Fallback: plain-line search for the heading word on its own line
    if best_match is None:
        fallback = re.compile(
            r'\n[^\n]{0,20}?\b(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\b\s*:?\s*\n',
        )
        for m in fallback.finditer(text):
            if m.start() > n * 0.40:
                if best_match is None or m.start() > best_match.start():
                    best_match = m

    if best_match is None:
        return None

    bib_text = text[best_match.end():].strip()

    # Trim at a known end-of-bibliography section heading
    lines = bib_text.splitlines()
    end = len(lines)
    for j, line in enumerate(lines):
        if j > 5 and _END_SECTION_RE.match(line.strip()):
            end = j
            break

    return "\n".join(lines[:end])


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
    text = _MD_HEADING_RE.sub('', text)
    ref_section = _find_ref_section(text)
    if ref_section is None:
        ref_section = text
    return parse_plaintext(ref_section)
