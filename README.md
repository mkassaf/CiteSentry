# refsift

[![PyPI](https://img.shields.io/pypi/v/refsift)](https://pypi.org/project/refsift/)
[![Python](https://img.shields.io/pypi/pyversions/refsift)](https://pypi.org/project/refsift/)
[![CI](https://github.com/mkassaf/refsift/actions/workflows/publish.yml/badge.svg)](https://github.com/mkassaf/refsift/actions/workflows/publish.yml)

Citation verification tool: check whether references actually exist, whether their URLs are live, and whether the content is relevant to the citation.

## What it does

Three checks per reference:

1. **Existence** — resolves against OpenAlex, Crossref, Semantic Scholar, arXiv, and domain-specific databases (PubMed for biomedical, DBLP for CS)
2. **URL liveness** — HTTP HEAD/GET check; classifies 2xx/4xx/timeout/bot-protection
3. **Content relevance** — LLM-backed check comparing fetched content to the cited title/topic (requires `DEEPSEEK_API_KEY` for CLI use)

Verdicts: `VERIFIED`, `METADATA_MISMATCH`, `DEAD_URL`, `CONTENT_DRIFT`, `NOT_FOUND`, `UNRESOLVABLE`.

`NOT_FOUND` means "could not verify — likely fabricated, needs manual review." Never "fake."

## Install

```bash
pip install refsift                 # basic install
pip install "refsift[cli-llm]"      # + DeepSeek for relevance checks
```

For development:

```bash
git clone https://github.com/mkassaf/refsift
cd refsift
pip install -e ".[dev]"
```

## CLI usage

```bash
# Check a BibTeX file
refsift check refs.bib

# Check a RIS/CSL-JSON/NBIB/plaintext file
refsift check refs.ris
refsift check refs.json

# Read from stdin
cat refs.txt | refsift check -

# Single ad-hoc reference
refsift check-one "Vaswani et al. (2017). Attention is all you need. NeurIPS."

# Output formats: table (default), json, md
refsift check refs.bib --format json
refsift check refs.bib --format md > report.md

# Skip checks
refsift check refs.bib --no-llm       # skip relevance (no API key needed)
refsift check refs.bib --no-url       # skip URL liveness

# Domain adapters (auto by default)
refsift check refs.bib --domain pubmed   # force PubMed only
refsift check refs.bib --domain none     # disable domain adapters

# Override plaintext style detection
refsift check refs.txt --style ieee
```

Exit code is non-zero if any reference is `NOT_FOUND` or `DEAD_URL` (useful in CI).

## MCP server (Claude Desktop / Claude Code)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "refsift": {
      "command": "refsift-mcp",
      "env": {
        "REFSIFT_MAILTO": "you@example.com",
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

Or with `uvx` (no prior install needed):

```json
{
  "mcpServers": {
    "refsift": {
      "command": "uvx",
      "args": ["--from", "refsift", "refsift-mcp"],
      "env": { "REFSIFT_MAILTO": "you@example.com" }
    }
  }
}
```

MCP tools exposed:
- `verify_reference(reference, check_url, check_relevance)` — single reference
- `verify_reference_list(references, format, check_url, check_relevance)` — batch
- `check_url_alive(url)` — standalone URL check

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `REFSIFT_MAILTO` | `refsift@example.com` | Polite email for OpenAlex/Crossref API |
| `DEEPSEEK_API_KEY` | — | Required for relevance checks in CLI |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model for relevance judgments |

## Supported input formats

- BibTeX (`.bib`) — via bibtexparser
- RIS (`.ris`) — via rispy; covers Zotero, Mendeley, EndNote, Web of Science
- CSL JSON (`.json`) — Zotero exports
- PubMed NBIB (`.nbib`)
- DOI list (`.txt` with one DOI per line)
- Plaintext reference sections — IEEE, APA, Vancouver, MLA, Chicago; auto-detected
- PDF (`.pdf`) — extracts reference section text via pdfminer.six

## Caching

Results are cached in a SQLite database (`~/.cache/refsift/cache.db`). Pass `--no-cache` to bypass.
