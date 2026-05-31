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

Verdicts: `VERIFIED`, `METADATA_MISMATCH`, `DEAD_URL`, `CONTENT_DRIFT`, `NOT_FOUND`, `UNRESOLVABLE`.

`NOT_FOUND` means "could not verify — likely fabricated, needs manual review." Never "fake."

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

## Caching

Results are cached in a SQLite database (`~/.cache/citesentry/cache.db`). Pass `--no-cache` to bypass.
