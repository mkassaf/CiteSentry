from __future__ import annotations

from pathlib import Path

import pytest

from refsift.models import Reference
from refsift.parse.bibtex import parse_bibtex
from refsift.parse.ris import parse_ris
from refsift.parse.csl_json import parse_csl_json
from refsift.parse.nbib import parse_nbib
from refsift.parse.doi_list import parse_doi_list
from refsift.parse.plaintext import split, detect_style, extract_fields, Style, parse_plaintext
from refsift.parse.detect import auto_parse

FIXTURES = Path(__file__).parent / "fixtures"


class TestBibtex:
    def test_parses_known_real(self):
        refs = parse_bibtex((FIXTURES / "known_real.bib").read_text())
        assert len(refs) == 5
        titles = {r.title for r in refs}
        assert "Attention is all you need" in titles

    def test_extracts_doi(self):
        refs = parse_bibtex((FIXTURES / "known_real.bib").read_text())
        attention = next(r for r in refs if r.title and "Attention" in r.title)
        assert attention.doi is not None
        assert "1706.03762" in attention.doi

    def test_extracts_authors(self):
        refs = parse_bibtex((FIXTURES / "known_real.bib").read_text())
        attention = next(r for r in refs if r.title and "Attention" in r.title)
        assert len(attention.authors) >= 2
        assert any("Vaswani" in a for a in attention.authors)

    def test_extracts_year(self):
        refs = parse_bibtex((FIXTURES / "known_real.bib").read_text())
        attention = next(r for r in refs if r.title and "Attention" in r.title)
        assert attention.year == 2017


class TestRis:
    def test_parses_sample(self):
        refs = parse_ris((FIXTURES / "sample.ris").read_text())
        assert len(refs) == 2

    def test_roundtrip_title(self):
        refs = parse_ris((FIXTURES / "sample.ris").read_text())
        titles = {r.title for r in refs}
        assert "Attention is all you need" in titles

    def test_roundtrip_doi(self):
        refs = parse_ris((FIXTURES / "sample.ris").read_text())
        attention = next(r for r in refs if r.title and "Attention" in r.title)
        assert attention.doi is not None


class TestCslJson:
    def test_parses_sample(self):
        refs = parse_csl_json((FIXTURES / "sample.json").read_text())
        assert len(refs) == 2

    def test_roundtrip_title(self):
        refs = parse_csl_json((FIXTURES / "sample.json").read_text())
        titles = {r.title for r in refs}
        assert "Attention is all you need" in titles

    def test_roundtrip_authors(self):
        refs = parse_csl_json((FIXTURES / "sample.json").read_text())
        attention = next(r for r in refs if r.title and "Attention" in r.title)
        assert any("Vaswani" in a for a in attention.authors)


class TestNbib:
    def test_parses_sample(self):
        refs = parse_nbib((FIXTURES / "sample.nbib").read_text())
        assert len(refs) >= 1

    def test_extracts_pmid(self):
        refs = parse_nbib((FIXTURES / "sample.nbib").read_text())
        pmids = [r.pmid for r in refs if r.pmid]
        assert "34519632" in pmids

    def test_extracts_title(self):
        refs = parse_nbib((FIXTURES / "sample.nbib").read_text())
        titles = [r.title for r in refs if r.title]
        assert any("deep learning" in t.lower() for t in titles)

    def test_extracts_doi(self):
        refs = parse_nbib((FIXTURES / "sample.nbib").read_text())
        dois = [r.doi for r in refs if r.doi]
        assert any("10." in d for d in dois)


class TestDoiList:
    def test_parses_dois(self):
        text = "10.1234/test.001\n10.5678/test.002\n"
        refs = parse_doi_list(text)
        assert len(refs) == 2
        assert refs[0].doi == "10.1234/test.001"


class TestPlaintext:
    def test_split_numbered_ieee(self):
        text = (FIXTURES / "ieee_style.txt").read_text()
        chunks = split(text)
        assert len(chunks) == 5

    def test_split_blank_lines_apa(self):
        text = (FIXTURES / "apa_style.txt").read_text()
        chunks = split(text)
        assert len(chunks) == 5

    def test_detect_style_ieee(self):
        text = (FIXTURES / "ieee_style.txt").read_text()
        chunks = split(text)
        style = detect_style(chunks)
        assert style == Style.IEEE

    def test_detect_style_apa(self):
        text = (FIXTURES / "apa_style.txt").read_text()
        chunks = split(text)
        style = detect_style(chunks)
        assert style == Style.APA

    def test_pdf_copypaste_hyphen_cleanup(self):
        text = (FIXTURES / "pdf_copypaste.txt").read_text()
        chunks = split(text)
        assert len(chunks) >= 3
        full_text = " ".join(chunks)
        assert "Neural" in full_text
        assert "Neu-" not in full_text

    def test_extract_year(self):
        chunk = '[1] A. Author, "Some Paper," Journal, 2021.'
        ref = extract_fields(chunk, Style.IEEE)
        assert ref.year == 2021

    def test_extract_doi(self):
        chunk = 'Some paper. doi: 10.1234/test.001'
        ref = extract_fields(chunk)
        assert ref.doi == "10.1234/test.001"

    def test_extract_url(self):
        chunk = 'Some paper. Available at https://example.com/paper'
        ref = extract_fields(chunk)
        assert "https://example.com/paper" in ref.urls

    def test_extract_arxiv_id(self):
        chunk = 'Attention is all you need. arXiv:1706.03762, 2017.'
        ref = extract_fields(chunk)
        assert ref.arxiv_id == "1706.03762"


class TestAutoDetect:
    def test_detects_bibtex_by_extension(self):
        refs = auto_parse(FIXTURES / "known_real.bib")
        assert len(refs) == 5

    def test_detects_ris_by_extension(self):
        refs = auto_parse(FIXTURES / "sample.ris")
        assert len(refs) == 2

    def test_detects_json_by_extension(self):
        refs = auto_parse(FIXTURES / "sample.json")
        assert len(refs) == 2

    def test_detects_nbib_by_extension(self):
        refs = auto_parse(FIXTURES / "sample.nbib")
        assert len(refs) >= 1

    def test_detects_plaintext_by_content(self):
        refs = auto_parse(FIXTURES / "ieee_style.txt")
        assert len(refs) >= 3
