from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING

from refsift.models import Reference

if TYPE_CHECKING:
    pass

_DOI_RE = re.compile(r"10\.\d{4,}/\S+")
_URL_RE = re.compile(r"https?://[^\s,;>\"')]+")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_NUMBERED_RE = re.compile(r"^\s*(\[?\d+\]?\.?\)?\s+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+\s+)")
_AUTHOR_YEAR_RE = re.compile(
    r"^[A-Z][a-zA-ZÀ-ÿ\-\']+,?\s+([A-Z]\.?\s*)+(?:\d{4}|,)"
)


class Style(str, Enum):
    IEEE = "IEEE"
    APA = "APA"
    VANCOUVER = "VANCOUVER"
    MLA = "MLA"
    CHICAGO = "CHICAGO"
    UNKNOWN = "UNKNOWN"


def _fix_hyphenated_breaks(text: str) -> str:
    return re.sub(r"(\w)-\n\s*(\w)", r"\1\2", text)


def _cleanup_chunk(chunk: str) -> str:
    chunk = _fix_hyphenated_breaks(chunk)
    chunk = re.sub(r"\s+", " ", chunk).strip()
    chunk = _NUMBERED_RE.sub("", chunk, count=1).strip()
    return chunk


def split(text: str) -> list[str]:
    text = _fix_hyphenated_breaks(text)
    lines = text.splitlines()

    for strategy in [
        _split_numbered,
        _split_blank_lines,
        _split_hanging_indent,
        _split_author_year,
    ]:
        chunks = strategy(lines)
        cleaned = [_cleanup_chunk(c) for c in chunks if _cleanup_chunk(c)]
        if len(cleaned) >= 2:
            return cleaned

    cleaned = [_cleanup_chunk(text)]
    return [c for c in cleaned if c]


def _split_numbered(lines: list[str]) -> list[str]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _NUMBERED_RE.match(line):
            if current:
                chunks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return []
    return [" ".join(c) for c in chunks]


def _split_blank_lines(lines: list[str]) -> list[str]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            if current:
                chunks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return []
    return [" ".join(c) for c in chunks]


def _split_hanging_indent(lines: list[str]) -> list[str]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0 and current:
            chunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return []
    return [" ".join(c) for c in chunks]


def _split_author_year(lines: list[str]) -> list[str]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _AUTHOR_YEAR_RE.match(line.strip()):
            if current:
                chunks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return []
    return [" ".join(c) for c in chunks]


# IEEE: quoted title + year; cleanup strips [N] so we match on quotes + year
_IEEE_RE = re.compile(r'"[^"]{5,}",?\s+in\s+|"[^"]{5,}[,."]\s+[A-Z].*\d{4}')
_IEEE_QUOTED_RE = re.compile(r'"[^"]{5,}".*\d{4}')
_APA_RE = re.compile(r"[A-Z][a-z]+,\s+[A-Z]\.\s+\(\d{4}\)")
_VANCOUVER_RE = re.compile(r"\d{4};\d+[\s(]")
_MLA_RE = re.compile(r'"[^"]+"\s+.*vol\.\s+\d+.*\(\d{4}\)')
_CHICAGO_RE = re.compile(r"\(\w+:\s*\w+,\s*\d{4}\)")


def detect_style(chunks: list[str]) -> Style:
    samples = chunks[:5]
    scores: dict[Style, int] = {s: 0 for s in Style}

    for chunk in samples:
        if _IEEE_RE.search(chunk) or _IEEE_QUOTED_RE.search(chunk):
            scores[Style.IEEE] += 2
        if _APA_RE.search(chunk):
            scores[Style.APA] += 2
        if _VANCOUVER_RE.search(chunk):
            scores[Style.VANCOUVER] += 2
        if _MLA_RE.search(chunk):
            scores[Style.MLA] += 2
        if _CHICAGO_RE.search(chunk):
            scores[Style.CHICAGO] += 2

        # secondary signals
        if re.search(r'"[^"]{5,}"', chunk):
            scores[Style.IEEE] += 1
        if re.search(r'\(\d{4}\)', chunk):
            scores[Style.APA] += 1
        if re.search(r'\d{4};\d+\(\d+\):\d+', chunk):
            scores[Style.VANCOUVER] += 1

    best_style = max(scores, key=lambda s: scores[s])
    if scores[best_style] >= 2:
        return best_style
    return Style.UNKNOWN


def extract_fields(chunk: str, style: Style = Style.UNKNOWN) -> Reference:
    doi = None
    m = _DOI_RE.search(chunk)
    if m:
        doi = m.group().rstrip(".,;)")

    urls = [u.rstrip(".,;)>\"'") for u in _URL_RE.findall(chunk)]
    urls = [u for u in urls if "doi.org" not in u]

    arxiv_id = None
    for u in urls + [chunk]:
        m2 = re.search(r"arxiv\.org/abs/([^\s/,;]+)", u)
        if m2:
            arxiv_id = m2.group(1)
            break
    if not arxiv_id:
        m3 = re.search(r"\barXiv:\s*(\d{4}\.\d+)", chunk, re.IGNORECASE)
        if m3:
            arxiv_id = m3.group(1)

    year = None
    ym = _YEAR_RE.search(chunk)
    if ym:
        year = int(ym.group())

    title = None
    authors: list[str] = []

    if style == Style.IEEE:
        title, authors = _extract_ieee(chunk)
    elif style == Style.APA:
        title, authors = _extract_apa(chunk)
    elif style == Style.VANCOUVER:
        title, authors = _extract_vancouver(chunk)
    else:
        title, authors = _extract_generic(chunk)

    return Reference(
        raw=chunk,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        arxiv_id=arxiv_id,
        urls=urls,
    )


def _extract_ieee(chunk: str) -> tuple[str | None, list[str]]:
    m = re.search(r'"([^"]{10,})"', chunk)
    title = m.group(1) if m else None

    authors_part = chunk.split('"')[0] if '"' in chunk else ""
    authors = _parse_author_list(authors_part)
    return title, authors


def _extract_apa(chunk: str) -> tuple[str | None, list[str]]:
    m = re.match(
        r"^((?:[A-Z][a-zA-ZÀ-ÿ\-\.']+,?\s+[A-Z]\.?,?\s*(?:&\s*)?)+)\s*\(\d{4}\)\.\s*([^.]+\.)",
        chunk,
    )
    if m:
        authors = _parse_author_list(m.group(1))
        title = m.group(2).strip().rstrip(".")
        return title, authors

    title_m = re.search(r"\(\d{4}\)\.\s+([^.]+)\.", chunk)
    title = title_m.group(1) if title_m else None
    return title, []


def _extract_vancouver(chunk: str) -> tuple[str | None, list[str]]:
    m = re.match(r"^(?:\d+\.\s+)?((?:[A-Z][a-zA-ZÀ-ÿ\-\.']+\s+[A-Z]{1,3},?\s*)+)\.\s+([^.]+)\.", chunk)
    if m:
        authors = _parse_author_list(m.group(1))
        title = m.group(2).strip()
        return title, authors
    return None, []


def _extract_generic(chunk: str) -> tuple[str | None, list[str]]:
    m = re.search(r'"([^"]{10,})"', chunk)
    if m:
        return m.group(1), []

    sentences = re.split(r"(?<=[.!?])\s+", chunk)
    for sentence in sentences[1:3]:
        stripped = sentence.strip()
        if len(stripped) > 20 and not re.match(r"^[A-Z]{2,}", stripped):
            return stripped.rstrip("."), []

    return None, []


def _parse_author_list(text: str) -> list[str]:
    text = text.strip().rstrip(".,")
    if not text:
        return []
    parts = re.split(r"\s+and\s+|;\s*|,\s+(?=[A-Z])", text, flags=re.IGNORECASE)
    authors = []
    for p in parts:
        p = p.strip().rstrip(",.")
        if p and len(p) > 1:
            authors.append(p)
    return authors[:10]


async def _llm_extract(chunk: str, llm_client: object) -> Reference:
    if llm_client is None:
        return Reference(raw=chunk)

    prompt = f"""\
Extract bibliographic fields from this reference as JSON.
Reference: {chunk}

Return ONLY valid JSON:
{{"title": null, "authors": [], "year": null, "venue": null, "doi": null, "arxiv_id": null, "urls": []}}
"""
    try:
        response = await llm_client.complete(prompt)  # type: ignore[union-attr]
        import json
        data = json.loads(response.strip())
        return Reference(
            raw=chunk,
            title=data.get("title"),
            authors=data.get("authors") or [],
            year=data.get("year"),
            venue=data.get("venue"),
            doi=data.get("doi"),
            arxiv_id=data.get("arxiv_id"),
            urls=data.get("urls") or [],
        )
    except Exception:
        return Reference(raw=chunk)


def parse_plaintext(text: str, style_override: Style | None = None, llm_client: object | None = None) -> list[Reference]:
    chunks = split(text)
    if not chunks:
        return []

    style = style_override or detect_style(chunks)

    refs = []
    for chunk in chunks:
        ref = extract_fields(chunk, style)
        if not ref.title and not ref.doi and not ref.arxiv_id:
            if llm_client is not None:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        pass
                    else:
                        ref = loop.run_until_complete(_llm_extract(chunk, llm_client))
                except Exception:
                    pass
        refs.append(ref)
    return refs
