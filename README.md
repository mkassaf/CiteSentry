# CiteSentry

[![PyPI](https://img.shields.io/pypi/v/citesentry)](https://pypi.org/project/citesentry/)
[![Python](https://img.shields.io/pypi/pyversions/citesentry)](https://pypi.org/project/citesentry/)
[![CI](https://github.com/mkassaf/CiteSentry/actions/workflows/publish.yml/badge.svg)](https://github.com/mkassaf/CiteSentry/actions/workflows/publish.yml)

Citation verification tool: check whether references actually exist, whether their URLs are live, and whether the content is relevant to the citation.

## What it does

Three checks per reference:

1. **Existence** — resolves against OpenAlex, Crossref, Semantic Scholar, arXiv, and domain-specific databases (PubMed for biomedical, DBLP for CS)
2. **URL liveness** — HTTP HEAD/GET check; classifies 2xx/4xx/timeout/bot-protection
3. **Content relevance** — LLM-backed check comparing fetched content to the cited title/topic (requires `DEEPSEEK_API_KEY` for CLI use)

## Verdicts

| Verdict | Meaning | Action |
|---|---|---|
| `VERIFIED` | Paper found in a scholarly database with matching title, authors, year, and DOI | None — citation is good |
| `METADATA_MISMATCH` | Paper found, but a field in your citation differs from the database record (commonly a truncated or wrong DOI) | Correct the mismatched field; the paper itself is real |
| `DEAD_URL` | Paper exists but one or more cited URLs return 4xx/5xx or time out | Update or remove the URL |
| `CONTENT_DRIFT` | Paper exists and URL is live, but fetched content doesn't match what the citation claims | Review whether you are citing the right paper |
| `NOT_FOUND` | Could not verify in any database — may be fabricated, obscure, or not yet indexed | Manual verification recommended; see note below |
| `UNRESOLVABLE` | Could not attempt verification — citation is missing enough fields (no title, no DOI, no authors) or the existence check errored | Add missing fields (year, DOI, venue) and re-run |

### NOT_FOUND is not "fake"

`NOT_FOUND` means the tool could not confirm the paper in the databases it queries (OpenAlex, Crossref, Semantic Scholar, arXiv, PubMed, DBLP). Common legitimate reasons:

- **Recent publications** — papers from the past 6–12 months are often not yet indexed, especially conference proceedings
- **Preprints** — papers only on institutional repositories or not yet on arXiv
- **Truncated or missing DOI** — without a DOI, title search may not find the paper
- **Obscure venues** — proceedings from smaller conferences may not be in major databases

A high `NOT_FOUND` rate in a survey of 2025–2026 literature (30–40%) is normal and expected.

### Expected verification rates by publication year

| Publication year | Typical verification rate |
|---|---|
| ≤ 2023 | 85–100% |
| 2024 | 60–85% |
| 2025 | 30–60% |
| 2026 | 10–30% |

Rates are lower for recent years due to database indexing lag, not citation quality.

## Install

```bash
pip install citesentry                 # basic install
pip install "citesentry[cli-llm]"      # + DeepSeek for relevance checks
```

For development:

```bash
git clone https://github.com/mkassaf/CiteSentry
cd CiteSentry
pip install -e ".[dev]"
```

## CLI usage

```bash
# Check a PDF paper — extracts and verifies the references section automatically
citesentry check paper.pdf --no-llm
citesentry check paper.pdf --no-llm --format md > report.md

# Check a BibTeX file
citesentry check refs.bib

# Check a RIS/CSL-JSON/NBIB/plaintext file
citesentry check refs.ris
citesentry check refs.json

# Read from stdin
cat refs.txt | citesentry check -

# Single ad-hoc reference
citesentry check-one "Vaswani et al. (2017). Attention is all you need. NeurIPS."

# Output formats: table (default), json, md
citesentry check refs.bib --format json
citesentry check refs.bib --format md > report.md

# Skip checks
citesentry check refs.bib --no-llm       # skip relevance (no API key needed)
citesentry check refs.bib --no-url       # skip URL liveness

# Domain adapters (auto by default)
citesentry check refs.bib --domain pubmed   # force PubMed only
citesentry check refs.bib --domain none     # disable domain adapters

# Override plaintext style detection
citesentry check refs.txt --style ieee
```

Exit code is non-zero if any reference is `NOT_FOUND` or `DEAD_URL` (useful in CI).

### PDF input — known limitation

pdfminer.six works well for single-column PDFs. **Two-column papers** (most IEEE/ACM conference papers) often produce jumbled text when columns are mixed, which breaks reference parsing. If you see very few references parsed or garbled titles, extract the references section manually first:

```bash
# Copy-paste the references section into a text file, then:
citesentry check refs.txt --no-llm
```

## MCP server (Claude Desktop / Claude Code)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "citesentry": {
      "command": "citesentry-mcp",
      "env": {
        "CITESENTRY_MAILTO": "you@example.com",
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
    "citesentry": {
      "command": "uvx",
      "args": ["--from", "citesentry", "citesentry-mcp"],
      "env": { "CITESENTRY_MAILTO": "you@example.com" }
    }
  }
}
```

MCP tools exposed:
- `verify_reference(reference, check_url, check_relevance)` — single reference
- `verify_reference_list(references, format, check_url, check_relevance)` — batch
- `check_url_alive(url)` — standalone URL check

### Claude Code (CLI)

Register the server once:

```bash
claude mcp add citesentry \
  -e CITESENTRY_MAILTO=you@example.com \
  -- uvx --from citesentry citesentry-mcp
```

Then in any Claude Code session, ask naturally:

> "Use citesentry to verify this reference: Vaswani et al. (2017). Attention is all you need. NeurIPS."

> "Check whether all the references in refs.bib are real."

> "Is https://arxiv.org/abs/1706.03762 still live?"

### Any MCP-compatible agent (Python example)

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server = StdioServerParameters(
    command="uvx",
    args=["--from", "citesentry", "citesentry-mcp"],
    env={"CITESENTRY_MAILTO": "you@example.com"},
)

async def main():
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "verify_reference",
                {"reference": "Vaswani et al. (2017). Attention is all you need. NeurIPS."},
            )
            print(result.content[0].text)

asyncio.run(main())
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CITESENTRY_MAILTO` | `citesentry@example.com` | Polite email for OpenAlex/Crossref API |
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

## Reference enrichment

When a citation is incomplete (missing year, DOI, or venue) but the tool finds a matching paper in a database, the result includes an `enriched` field with the complete metadata sourced from the database. This is visible in JSON output:

```json
{
  "overall_verdict": "VERIFIED",
  "reference": { "title": "SOEN-101: ...", "year": null, "doi": null },
  "enriched":  { "title": "SOEN-101: ...", "year": 2025, "doi": "10.1109/ICSE55347.2025.00638", "venue": "ICSE" }
}
```

Use this to correct incomplete citations in your bibliography without manual searching.

## Caching

Results are cached in a SQLite database (`~/.cache/citesentry/cache.db`). Pass `--no-cache` to bypass.
