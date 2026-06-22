# CiteSentry

[![PyPI](https://img.shields.io/pypi/v/citesentry)](https://pypi.org/project/citesentry/)
[![Python](https://img.shields.io/pypi/pyversions/citesentry)](https://pypi.org/project/citesentry/)
[![CI](https://github.com/mkassaf/CiteSentry/actions/workflows/publish.yml/badge.svg)](https://github.com/mkassaf/CiteSentry/actions/workflows/publish.yml)

Citation verification tool: check whether references actually exist, whether their URLs are live, and whether the content is relevant to the citation context.

## What it does

Three checks per reference:

1. **Existence** — resolves against OpenAlex, Crossref, Semantic Scholar, arXiv, DBLP (CS), PubMed (biomedical), and Google Books (textbooks)
2. **URL liveness** — HTTP HEAD/GET check; classifies 2xx/4xx/timeout/bot-protection
3. **Content relevance** — LLM-backed check comparing fetched content to the cited title/topic (requires `DEEPSEEK_API_KEY` for CLI, or uses Claude via MCP sampling)

## Verdicts

| Verdict | Meaning | Action |
|---|---|---|
| `VERIFIED` | Paper found in a scholarly database with matching title, authors, year | None — citation is good |
| `METADATA_MISMATCH` | Paper found, but a field in your citation differs from the database record | Correct the mismatched field; the paper itself is real |
| `DEAD_URL` | Paper exists but one or more cited URLs return 4xx/5xx or time out | Update or remove the URL |
| `CONTENT_DRIFT` | Paper exists and URL is live, but fetched content doesn't match what the citation claims | Review whether you are citing the right paper |
| `NOT_FOUND` | Could not verify in any database — may be fabricated, obscure, or not yet indexed | Manual verification recommended; see note below |
| `UNRESOLVABLE` | Could not attempt verification — citation is missing enough fields (no title, no DOI, no authors) | Add missing fields (year, DOI, venue) and re-run |

### NOT_FOUND is not "fake"

`NOT_FOUND` means the tool could not confirm the paper in the databases it queries. Common legitimate reasons:

- **Recent publications** — papers from the past 6–12 months are often not yet indexed
- **Preprints** — papers only on institutional repositories or not yet on arXiv
- **Truncated or missing DOI** — without a DOI, title search may miss the paper
- **Obscure venues** — proceedings from smaller conferences may not be in major databases

### Expected verification rates by publication year

| Publication year | Typical verification rate |
|---|---|
| ≤ 2023 | 85–100% |
| 2024 | 60–85% |
| 2025 | 30–60% |
| 2026 | 10–30% |

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
# Check a PDF — extracts references automatically (PyMuPDF, multi-column aware)
citesentry check paper.pdf
citesentry check paper.pdf --no-llm           # skip relevance check
citesentry check paper.pdf --format md > report.md

# Check a BibTeX / RIS / CSL-JSON / NBIB / plaintext file
citesentry check refs.bib
citesentry check refs.ris
citesentry check refs.json

# Read from stdin
cat refs.txt | citesentry check -

# Single ad-hoc reference
citesentry check-one "Vaswani et al. (2017). Attention is all you need. NeurIPS."

# Output formats: table (default), json, md
citesentry check refs.bib --format json
citesentry check refs.bib --format md > report.md

# Skip individual checks
citesentry check refs.bib --no-llm       # skip relevance (no API key needed)
citesentry check refs.bib --no-url       # skip URL liveness
citesentry check refs.bib --no-cache     # bypass cache (forces fresh lookups)

# Domain adapters (auto by default)
citesentry check refs.bib --domain pubmed   # force PubMed only
citesentry check refs.bib --domain dblp    # force DBLP only
citesentry check refs.bib --domain none    # disable domain adapters
```

Exit code is non-zero if any reference is `NOT_FOUND` or `DEAD_URL` (useful in CI).

## PDF support

CiteSentry uses **PyMuPDF** for PDF text extraction, which handles multi-column layouts (IEEE/ACM conference papers) correctly. References are automatically located, split, and parsed.

Supported citation styles auto-detected from the reference section:
- LNCS / Springer (`Lastname, I.: Title. Venue (Year)`)
- IEEE (`[N] Authors, "Title," Venue, Year`)
- APA, Vancouver, MLA, Chicago

### LLM fallback for garbled references

If some references can't be parsed (garbled PDF text, unusual formatting), CiteSentry automatically uses the LLM to recover the fields — no extra configuration needed. This requires `DEEPSEEK_API_KEY` for CLI or runs via MCP sampling in the MCP server.

To skip LLM entirely: `--no-llm`.

### GROBID (optional, best quality)

For the highest-quality reference extraction, run a local GROBID server:

```bash
docker run -t --rm -p 8070:8070 lfoppiano/grobid:0.8.1
export CITESENTRY_GROBID_URL=http://localhost:8070/api
citesentry check paper.pdf
```

When GROBID is available, it is used as the primary extractor. PyMuPDF is the fallback when GROBID is not running.

### marker (optional, better text quality for hard PDFs)

[marker](https://github.com/datalab-to/marker) converts a PDF to Markdown using layout/OCR models instead of raw text extraction. It handles scanned pages, complex layouts, and tables better than PyMuPDF, and its `#`-style Markdown headings make the references section easier to locate reliably.

It's opt-in: `marker-pdf` pulls in PyTorch and several GB of layout/OCR models, and conversion is much slower than PyMuPDF (seconds to minutes per PDF, especially on CPU), so it's never enabled just because the package happens to be installed.

```bash
pip install citesentry[marker]
export CITESENTRY_USE_MARKER=1
citesentry check paper.pdf
```

When enabled, marker is tried first within the text-extraction fallback path (i.e. after GROBID, before PyMuPDF). If marker isn't installed or conversion fails, CiteSentry silently falls back to PyMuPDF → pypdf → pdfminer as usual.

## MCP server (Claude Desktop / Claude Code)

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "citesentry": {
      "command": "citesentry-mcp",
      "env": {
        "CITESENTRY_MAILTO": "you@example.com",
        "SEMANTIC_SCHOLAR_API_KEY": "your_s2_key",
        "GOOGLE_BOOKS_API_KEY": "your_google_key",
        "DEEPSEEK_API_KEY": "sk-...",
        "OLLAMA_MODEL": "llama3.2"
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
      "env": {
        "CITESENTRY_MAILTO": "you@example.com",
        "SEMANTIC_SCHOLAR_API_KEY": "your_s2_key",
        "GOOGLE_BOOKS_API_KEY": "your_google_key"
      }
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
  -e SEMANTIC_SCHOLAR_API_KEY=your_s2_key \
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
    env={
        "CITESENTRY_MAILTO": "you@example.com",
        "SEMANTIC_SCHOLAR_API_KEY": "your_s2_key",
    },
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

All API keys are **optional** — CiteSentry works without any keys but will hit anonymous rate limits faster when checking large reference lists.

| Variable | Default | Description |
|---|---|---|
| `CITESENTRY_MAILTO` | `citesentry@example.com` | Polite email for OpenAlex/Crossref API (strongly recommended) |
| `SEMANTIC_SCHOLAR_API_KEY` | *(optional)* | Raises Semantic Scholar rate limit from ~1 req/s to 100 req/5s — see below |
| `GOOGLE_BOOKS_API_KEY` | *(optional)* | Raises Google Books limit from ~1k req/day to 100k/day; used for textbook lookup |
| `CITESENTRY_GROBID_URL` | *(optional)* | GROBID REST endpoint for high-quality PDF parsing; use `http://localhost:8070/api` for a local Docker instance |
| `CITESENTRY_USE_MARKER` | *(optional)* | Set to `1`/`true` to use [marker](https://github.com/datalab-to/marker) (PDF→Markdown via layout/OCR models) for PDF text extraction; requires `pip install citesentry[marker]` |
| `DEEPSEEK_API_KEY` | *(optional)* | Enables relevance checks via DeepSeek; takes priority over Ollama if both are set |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint for DeepSeek |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model name |
| `OLLAMA_MODEL` | *(optional)* | Enables relevance checks via local Ollama (e.g. `llama3.2`, `mistral`); used when `DEEPSEEK_API_KEY` is not set |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |

### Getting free API keys

**Semantic Scholar** (recommended — significantly improves reliability for large reference lists):
1. Go to **[semanticscholar.org/product/api#api-key](https://www.semanticscholar.org/product/api#api-key)**
2. Fill in the form — free, approved within minutes
3. Add to your shell profile: `export SEMANTIC_SCHOLAR_API_KEY=your_key`

**Ollama** (free, local, no internet required):
1. Install Ollama from [ollama.com](https://ollama.com) and pull a model: `ollama pull llama3.2`
2. Set `export OLLAMA_MODEL=llama3.2` — CiteSentry will use it automatically when `DEEPSEEK_API_KEY` is not set
3. Works with any model Ollama supports; `llama3.2` or `mistral` are good choices for relevance checking

**Google Books** (recommended when references include textbooks):
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Enable the "Books API" and create an API key
3. Add to your shell profile: `export GOOGLE_BOOKS_API_KEY=your_key`

## Supported input formats

| Format | Extension | Notes |
|---|---|---|
| PDF | `.pdf` | PyMuPDF extraction; multi-column aware; GROBID optional; marker optional |
| BibTeX | `.bib` | via bibtexparser |
| RIS | `.ris` | Zotero, Mendeley, EndNote, Web of Science |
| CSL JSON | `.json` | Zotero exports |
| PubMed NBIB | `.nbib` | PubMed direct export |
| DOI list | `.txt` | One DOI per line |
| Plaintext | `.txt` | IEEE, APA, LNCS/Springer, Vancouver, MLA, Chicago; auto-detected |

## Reference enrichment

When a citation is incomplete (missing year, DOI, or venue) but the tool finds a matching paper in a database, the result includes an `enriched` field with the complete metadata. Visible in JSON output:

```json
{
  "overall_verdict": "VERIFIED",
  "reference": { "title": "SOEN-101: ...", "year": null, "doi": null },
  "enriched":  { "title": "SOEN-101: ...", "year": 2025, "doi": "10.1109/ICSE55347.2025.00638", "venue": "ICSE" }
}
```

## Caching

Results are cached in SQLite (`~/.cache/citesentry/cache.db`):
- **PASS / VERIFIED** results: cached for 30 days
- **FAIL / NOT_FOUND** results: cached for 1 day (so recent publications get re-checked as databases update)

To force a fresh lookup: `--no-cache`, or delete `~/.cache/citesentry/cache.db`.
