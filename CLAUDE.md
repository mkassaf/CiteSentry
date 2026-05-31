# refsift — Claude Code session notes

## Guardrails (non-negotiable)

- Never label a reference "fake" or "fraudulent" — only "could not verify / needs review."
- Never bypass CAPTCHA or bot-protection; classify as SKIPPED.
- Never hardcode API keys; read from env; degrade gracefully when absent.
- Core (`refsift/core/`, `refsift/checks/`, `refsift/sources/`, `refsift/parse/`) must never import Typer, Rich, or MCP.
- MCP server stdout must stay clean (JSON-RPC stream). Log to stderr only.
- Always send `mailto` to OpenAlex/Crossref; respect rate limits; cache aggressively.
- Report all counts honestly: checked, skipped, errored — never silently drop.

## Architecture

```
                 ┌─────────────────────────┐
   bib/pdf/txt → │   refsift.core (library) │ → VerificationReport (pydantic)
                 └─────────────────────────┘
                      ▲                  ▲
                      │                  │
              refsift.cli         refsift.mcp_server
            (Typer + Rich)         (FastMCP / stdio)
```

If verification logic ever appears inside `cli.py` or `mcp_server.py`, that is a bug — move it to core.

## LLM strategy

- MCP server: uses MCP sampling (`ctx.sample()`) — no API key needed.
- CLI: uses DeepSeek via OpenAI-compatible endpoint; requires `DEEPSEEK_API_KEY`.
- `--no-llm` skips relevance checks entirely; tool remains fully usable.

## Verdict wording

`NOT_FOUND` → "could not verify — likely fabricated, needs manual review"
Never use the word "fake."
