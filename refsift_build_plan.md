# refsift — Build Plan for Claude Code

> **What this is:** an implementation spec for a single citation-verification tool that ships as **both** a CLI and an **MCP server**. Hand this file to Claude Code as the source of truth. The name `refsift` is a placeholder — rename freely (`refcheck`, `citevet`, etc.) but keep it consistent across `pyproject.toml`, the package dir, and the MCP server name.

---

## 0. The one rule that governs everything

**Core logic is a pure library. The CLI and the MCP server are thin adapters over it.**

```
                 ┌─────────────────────────┐
   bib/pdf/txt → │   refsift.core (library) │ → VerificationReport (pydantic)
                 │   - parse                │
                 │   - existence check      │
                 │   - url liveness (2xx)   │
                 │   - content relevance    │
                 │   - verdict + scoring    │
                 └─────────────────────────┘
                      ▲                  ▲
                      │                  │
              refsift.cli         refsift.mcp_server
            (Typer + Rich)         (FastMCP / stdio)
```

The core must **never** import Typer, Rich, or MCP. It takes structured input and returns a `VerificationReport` object. Both frontends serialize that same object. If Claude Code ever puts verification logic inside a CLI command or an MCP tool function, that is a bug — refactor it into core.

---

## 1. What the tool does (scope)

Three checks per reference, derived from prior art (the "Cited but Not Verified" framework's three axes + existence checking from CiteAudit/hallucinator). Combine them into one pass:

1. **Existence** — does this paper actually exist? Resolve against scholarly databases by DOI, then by title+author+year. ("Is the paper correct.")
2. **URL liveness** — does each URL in the reference resolve and return a `2xx` (following redirects)? Distinguish dead (`4xx/5xx`), redirected, timeout, and blocked-by-bot-protection.
3. **Content relevance** — does the fetched content of the cited page/paper actually relate to what the reference claims to be (title/topic)? This is the LLM-backed check.

Out of scope for v1 (do NOT build): full claim-faithfulness ("does the source support the specific sentence that cites it"), PDF-of-the-whole-manuscript ingestion beyond the reference section, a web UI. Leave hooks for them but don't implement.

---

## 2. Data sources (all free, no API key, JSON)

Use a **polite `mailto` parameter** on every request where the API supports it (OpenAlex, Crossref). Make the email configurable.

Use a **polite `mailto` parameter** on every request where the API supports it (OpenAlex, Crossref). Make the email configurable.

### Core sources (always active)

| Source | Use for | Auth | Notes |
|---|---|---|---|
| **OpenAlex** | Primary existence + metadata | none | ~250M works, all disciplines. Stay under ~100k calls/day. `mailto` for polite pool. |
| **Crossref** | DOI resolution (authoritative) | none | ~150M DOI records. Best for exact DOI lookups. |
| **Semantic Scholar** | CS/AI coverage + abstracts | none (rate-limited) | Strong for CS/AI domain; good abstract source for the relevance check. |
| **arXiv** | Preprints | none | For arXiv IDs and recent preprints not yet indexed elsewhere. |
| **Unpaywall** | Open-access full text locator | none (`mailto`) | Only when relevance check needs more than an abstract. |

### Domain adapters (opt-in via config or `--domain` flag)

| Source | Domain | Auth | Notes |
|---|---|---|---|
| **PubMed / NCBI Entrez** | Biomedical, life sciences | none (rate-limited; optional API key for higher limits) | ~35M records. Use `esearch` + `efetch` from the Entrez API. Auto-activate when venue/journal looks biomedical (Nature, Lancet, NEJM, PLoS, etc.) or when MeSH terms present. `mailto` equivalent: `tool` + `email` params. |
| **DBLP** | Computer science (conferences + journals) | none | Clean, structured CS metadata back to ~1970s. REST API + BibTeX export. Auto-activate when venue looks like a CS conference/journal (NeurIPS, ICML, CVPR, ACL, ICLR, VLDB, etc.) or arXiv CS category. |

Domain adapters slot into the same `SourceAdapter` ABC as core sources — they just aren't queried by default. Auto-activation heuristics live in `checks/existence.py`; explicit opt-in overrides them.

Each source is an **adapter** behind a common interface (see §4). Querying multiple and reconciling is the point — no single source is complete.

---

## 3. Project layout

```
refsift/
├── pyproject.toml
├── README.md
├── CLAUDE.md                    # session notes for future Claude Code runs
├── refsift/
│   ├── __init__.py
│   ├── models.py                # pydantic: Reference, Candidate, CheckResult, VerificationReport
│   ├── config.py                # settings: mailto, llm key, timeouts, cache path, concurrency
│   ├── core/
│   │   ├── engine.py            # orchestrates the 3 checks -> VerificationReport. THE brain.
│   │   ├── cascade.py           # tier policy: cheap checks gate expensive ones
│   │   └── verdict.py           # scoring + verdict taxonomy
│   ├── parse/
│   │   ├── __init__.py          # auto_parse(path_or_text) dispatcher
│   │   ├── detect.py            # sniff format from extension + content; returns Parser
│   │   ├── bibtex.py            # BibTeX + BibLaTeX (.bib) via bibtexparser
│   │   ├── ris.py               # RIS (.ris) via rispy
│   │   ├── csl_json.py          # CSL JSON (.json) via stdlib json
│   │   ├── nbib.py              # PubMed/NBIB (.nbib) custom parser
│   │   ├── doi_list.py          # plain DOI-per-line .txt (regex sniff)
│   │   ├── plaintext.py         # structured splitter for raw reference sections
│   │   │   # split(text) -> list[str]         boundary detection
│   │   │   # detect_style(chunks) -> Style    APA|IEEE|Vancouver|MLA|Chicago|UNKNOWN
│   │   │   # extract_fields(chunk, style)     regex per style -> Reference
│   │   │   # _llm_extract(chunk)              LLM fallback when style=UNKNOWN or low confidence
│   │   └── pdf_refs.py          # locate + extract reference section from PDF (optional: refextract/anystyle/GROBID)
│   ├── sources/
│   │   ├── base.py              # SourceAdapter ABC: lookup_doi(), search()
│   │   ├── openalex.py
│   │   ├── crossref.py
│   │   ├── semantic_scholar.py
│   │   ├── arxiv.py
│   │   ├── unpaywall.py
│   │   └── domain/              # opt-in domain adapters
│   │       ├── pubmed.py        # NCBI Entrez: biomedical/life sciences
│   │       └── dblp.py          # DBLP: CS conferences + journals
│   ├── checks/
│   │   ├── existence.py         # uses sources/ + fuzzy matching -> CheckResult
│   │   ├── url_liveness.py      # httpx HEAD->GET, redirects, status classification
│   │   └── relevance.py         # fetch content + LLM judge -> CheckResult
│   ├── llm/
│   │   ├── base.py              # LLMClient ABC (provider-agnostic)
│   │   ├── mcp_sampling.py      # PRIMARY: delegates to host via MCP sampling/createMessage
│   │   └── deepseek.py          # CLI fallback: OpenAI-compatible endpoint, needs DEEPSEEK_API_KEY
│   ├── cache.py                 # SQLite: keyed by doi/url/title-hash; never re-hit network
│   ├── cli.py                   # Typer + Rich  (THIN)
│   └── mcp_server.py            # FastMCP over stdio  (THIN)
└── tests/
    ├── fixtures/                # known-real refs, fabricated refs, dead URLs, drifted pages
    ├── test_parse.py
    ├── test_sources.py          # mock HTTP
    ├── test_checks.py
    └── test_engine.py
```

---

## 4. The data model (`models.py`)

Define these as pydantic models. They are the contract between core and both frontends.

- **`Reference`**: `raw: str`, `title: str | None`, `authors: list[str]`, `year: int | None`, `venue: str | None`, `doi: str | None`, `arxiv_id: str | None`, `urls: list[str]`.
- **`Candidate`**: a possible match returned by a source — same fields as Reference plus `source: str` and a `match_score: float`.
- **`CheckResult`**: `name: Literal["existence","url_liveness","relevance"]`, `status: <enum below>`, `confidence: float`, `evidence: dict` (raw bits used to decide), `cost: CheckCost` (tokens/calls/elapsed — keep it, it's cheap to track and useful later).
- **`VerificationReport`**: `reference: Reference`, `checks: list[CheckResult]`, `overall_verdict: <enum>`, `notes: list[str]`.

### Verdict taxonomy (don't use a bare boolean)

Per-reference `overall_verdict`:

- `VERIFIED` — exists, metadata consistent, URLs live (or no URL), content relevant.
- `METADATA_MISMATCH` — paper exists but ≥1 field disagrees (the subtle LLM-corruption case).
- `DEAD_URL` — paper may exist but a cited URL is not 2xx.
- `CONTENT_DRIFT` — URL is live but its content no longer matches the citation (named problem since 2012).
- `NOT_FOUND` — no match in any source; **likely** fabricated. Flag for manual review.
- `UNRESOLVABLE` — couldn't parse the reference well enough to check.

**Critical wording rule:** `NOT_FOUND` must surface to the user as *"could not verify — likely fabricated, needs manual review,"* never *"fake."* Obscure books, non-indexed workshop papers, and brand-new preprints produce real false positives. Minimizing false positives is what makes the tool trustworthy; an over-eager "FAKE" label destroys that.

Status enum for individual checks: `PASS | FAIL | WARN | SKIPPED | ERROR`.

---

## 4b. Parsing (`parse/`)

### Format detection (`parse/detect.py`)

`auto_parse(source)` accepts a file path, a `pathlib.Path`, or a raw string and returns a list of `Reference` objects. Detection order:

1. **File extension** (authoritative when present): `.bib` → bibtex, `.ris` → ris, `.json` → csl_json, `.nbib` → nbib, `.pdf` → pdf_refs.
2. **Content sniffing** (used for `.txt` or raw strings):
   - Lines matching `10\.\d{4,}/\S+` and nothing else → doi_list
   - `@article`, `@inproceedings`, etc. at line start → bibtex
   - Lines starting `TY  -` → ris
   - Lines starting `PMID-` → nbib
   - Starts with `[{` and valid JSON array → csl_json
   - Otherwise → plaintext splitter

### Structured format parsers

- **`bibtex.py`** — `bibtexparser v2`. Handles BibTeX and BibLaTeX entry types. Maps all common fields to `Reference`.
- **`ris.py`** — `rispy`. Handles all RIS tag variants. Covers Zotero, Mendeley, EndNote, Web of Science, and PubMed RIS exports.
- **`csl_json.py`** — `json.load()` + field mapping. Zero extra dependencies.
- **`nbib.py`** — line-by-line tag parser for the `FIELD- value` format PubMed uses. No library needed.
- **`doi_list.py`** — regex scan for bare DOIs (`10.XXXX/...`), one per line. Returns a minimal `Reference(doi=...)` for each; existence check fills in the rest.

### Plaintext splitter (`parse/plaintext.py`)

The most complex parser. Handles raw reference sections pasted from PDFs, copied from papers, or piped from other tools.

**Step 1 — boundary detection** (`split(text) -> list[str]`):

Try splitting strategies in order; use the first that produces ≥2 plausible chunks:

| Strategy | Trigger | How |
|---|---|---|
| Numbered marker | Lines starting `[N]`, `N.`, `(N)`, `N)`, `¹²³…` | Each marker starts a new ref; continuation lines are joined |
| Blank-line blocks | ≥1 blank line between non-empty blocks | Each block is one ref |
| Hanging indent | First line flush-left, continuations indented ≥2 spaces | Detect indent level change |
| Author-year anchor | Line starts with `Surname,` or `Surname F` before a 4-digit year | New ref on each such line |

Post-split cleanup applied to every chunk:
- Rejoin hyphenated line-breaks (`Neu-\nral` → `Neural`)
- Collapse internal newlines and excess whitespace
- Strip leading numeric/symbol markers

**Step 2 — style detection** (`detect_style(chunks) -> Style`):

Sample the first 5 chunks, score each against style signatures:

| Style | Key signature |
|---|---|
| `IEEE` | `[N]` marker; title in `"quotes"`; year near end |
| `APA` | `Author, F. (Year).` pattern; title sentence-case, no quotes |
| `Vancouver` | `N.` marker; `Journal. Year;vol(issue):pages` |
| `MLA` | No marker; title in `"quotes"`; `vol. N (Year)` |
| `Chicago` | Footnote number; title in italics position; `(Publisher, Year)` |
| `UNKNOWN` | No style clears threshold |

**Step 3 — field extraction** (`extract_fields(chunk, style) -> Reference`):

Apply style-specific regex to extract `authors`, `year`, `title`, `venue`, `doi`, `urls`. DOI regex (`10\.\d{4,}/\S+`) and URL regex are always applied regardless of style.

**Step 4 — LLM fallback** (`_llm_extract(chunk) -> Reference`):

Fires when `style == UNKNOWN` or field extraction confidence is low (e.g. title not found, no year). Sends the raw chunk to the LLM with a structured extraction prompt; response is strict JSON mapping to `Reference` fields. Degrades to `Reference(raw=chunk)` if LLM unavailable — the existence check will still attempt a title search on the raw string.

### PDF reference extraction (`parse/pdf_refs.py`)

Locate the reference section (scan for headings like "References", "Bibliography", "Works Cited") and extract its text, then pass to `plaintext.py`. Uses `pdfminer.six` for text extraction (no OCR needed for born-digital PDFs). Optional: `refextract`, `anystyle`, or GROBID for higher-accuracy structured output.

---

## 5. The checks

### 5.1 Existence (`checks/existence.py`)
1. If DOI present → `lookup_doi()` on Crossref then OpenAlex. Exact resolve = strong PASS.
2. Else → `search()` across OpenAlex + Semantic Scholar (+ arXiv if it looks like a preprint).
3. **Domain adapter activation** — before committing to `NOT_FOUND`, check if a domain adapter applies and query it:
   - Activate **PubMed** if venue/journal matches a biomedical pattern (Nature, Lancet, NEJM, PLoS, Cell, BMJ, etc.) or if the reference contains a PMID.
   - Activate **DBLP** if venue matches a CS conference/journal pattern (NeurIPS, ICML, CVPR, ACL, ICLR, VLDB, SIGMOD, etc.) or arXiv CS category.
   - Always activate both if `--domain pubmed,dblp` is passed explicitly. Never activate if `--no-domain` is set.
4. Score each candidate: fuzzy title match (`rapidfuzz` token-set ratio), author surname overlap, year proximity (±1 tolerable), venue match.
5. Build a per-field consistency report. If best candidate is strong but a field disagrees → `METADATA_MISMATCH`. If nothing clears threshold across all active sources → `NOT_FOUND`.

### 5.2 URL liveness (`checks/url_liveness.py`)
- For each URL: `httpx` with redirects followed, sane timeout, realistic User-Agent.
- Try `HEAD` first; fall back to `GET` if HEAD is rejected (many servers 405 HEAD).
- Classify: `2xx` = PASS; `3xx`-final-`2xx` = PASS+note redirect; `4xx/5xx` = FAIL; timeout = WARN; known bot-protection (Cloudflare 403, LinkedIn/Twitter) = SKIPPED, never report these as dead. **Do not attempt to bypass bot protection or CAPTCHAs.**
- Respect a per-host politeness delay; cache results by URL.

### 5.3 Content relevance (`checks/relevance.py`)
- Pull comparison text: abstract from the source adapter (cheap) or, if needed, fetched page text / OA full text via Unpaywall.
- Ask the LLM to judge alignment between (reference title/topic) and (fetched content) on a small rubric → `RELEVANT | PARTIAL | UNRELATED | CANNOT_DETERMINE` + confidence + one-line rationale.
- Prompt must allow `CANNOT_DETERMINE` (paywalled, JS-only page, no abstract). Treat that as WARN, not FAIL.

---

## 6. The cost cascade (`core/cascade.py`)

Run checks cheapest-first and **stop early** when a confident negative makes later checks pointless. This keeps cost (and energy) concentrated where there's genuine ambiguity.

```
Tier 0  parse                 (local, free)
Tier 1  existence by DOI       (1 authoritative call)        ─┐ if NOT_FOUND and no URL,
Tier 2  existence by search    (few calls, only if no DOI)    │ you can stop — no point
Tier 3  url liveness           (network, no LLM)              │ running the LLM on a
Tier 4  content relevance      (LLM — the only token spend)  ─┘ reference that doesn't exist
```

- SQLite cache (`cache.py`) sits under all tiers: identical DOIs/URLs/titles never re-hit the network across runs.
- Make the LLM tier individually skippable (`--no-llm` / MCP arg) so the tool is fully usable offline-of-LLM for existence+URL only.

---

## 7. LLM layer (`llm/`)

`LLMClient` ABC so the provider is swappable. The engine receives an `LLMClient` instance at construction — the frontend (CLI or MCP server) decides which implementation to inject. Core never touches provider details.

### Primary: MCP Sampling (`llm/mcp_sampling.py`)
When running as an MCP server, use the **MCP sampling capability** — the server sends a `sampling/createMessage` request back to the host (Claude Desktop, Claude Code, or any spec-compliant client) and the host runs the inference using its own Claude connection. No extra API key needed.

Implementation sketch:
```python
# inside mcp_server.py tool handler, the FastMCP context is available
from mcp.server.fastmcp import Context

class MCPSamplingClient(LLMClient):
    def __init__(self, ctx: Context): self._ctx = ctx

    async def complete(self, prompt: str) -> str:
        result = await self._ctx.sample(prompt)   # sampling/createMessage
        return result.text
```

The `relevance.py` check passes the same structured JSON prompt regardless of which client is injected. The MCP sampling client just routes it through the host instead of a direct API call.

If the host client doesn't support sampling, `ctx.sample()` raises — catch it and return `SKIPPED` with a note, same as the no-key path.

### CLI fallback: DeepSeek (`llm/deepseek.py`)
For CLI use (no MCP host available), fall back to DeepSeek via its OpenAI-compatible endpoint. Read key from `DEEPSEEK_API_KEY`; if absent, `relevance` check returns `SKIPPED`. Any OpenAI-compatible endpoint works here — the key and base URL are both configurable. Default model: `deepseek-chat` (cheap, fine for a relevance rubric).

### Shared rules
- Prompt returns **strict JSON only** (no prose, no markdown fences); parse defensively and degrade to `CANNOT_DETERMINE` on parse failure.
- Allow escalation to a reasoning/thinking model for low-confidence relevance calls (configurable, off by default).
- `--no-llm` / MCP arg skips the relevance tier entirely; the tool stays fully usable for existence + URL checks with no LLM at all.

---

## 8. CLI (`cli.py`) — thin

Typer + Rich. Commands:

- `refsift check <file>` — any supported format; auto-detected by extension then content sniff. Pass `-` to read from stdin (`cat refs.txt | refsift check -`). Flags: `--format {table,json,md}`, `--no-llm`, `--no-url`, `--model`, `--mailto`, `--concurrency`, `--cache/--no-cache`, `--domain {pubmed,dblp,all,none}` (default: auto), `--style {ieee,apa,vancouver,mla,chicago,auto}` (override plaintext style detection).
- `refsift check-one "<raw reference string>"` — single ad-hoc reference; string is passed directly to `plaintext.extract_fields()`.
- Output: Rich table for humans (verdict color-coded), `--format json` emits the serialized `VerificationReport` list for piping, `--format md` for dropping into a review.
- Exit code non-zero if any reference is `NOT_FOUND`/`DEAD_URL` (useful in CI / pre-commit).

Each command does: parse → `engine.verify(refs, options)` → serialize. No logic beyond that.

---

## 9. MCP server (`mcp_server.py`) — thin

Use the **official MCP Python SDK** (`mcp[cli]`, which bundles FastMCP): `from mcp.server.fastmcp import FastMCP`. Default transport **stdio** (what Claude Desktop launches). This is the spec-compliant, lowest-friction path; the standalone `fastmcp` package is an alternative if you later hit transport edge cases.

Expose these tools (each is a decorated function that calls core and returns the serialized report — keep them tiny):

- `verify_reference(reference: str, check_url: bool = True, check_relevance: bool = True) -> dict` — one raw reference string; auto-parsed via `plaintext.extract_fields()`.
- `verify_reference_list(references: list[str] | str, format: str = "auto", ...) -> dict` — many references. `references` can be a list of raw strings or a single text blob in any supported format (BibTeX, RIS, CSL JSON, NBIB, plain numbered/APA/etc. list). `format` overrides auto-detection.
- `check_url_alive(url: str) -> dict` — just the liveness check (handy standalone).

Rules for the MCP layer:
- **stdio hygiene:** never `print()` to stdout (it corrupts the JSON-RPC stream). Log to **stderr** or a file only.
- Return structured dicts (the serialized `VerificationReport`), not pre-formatted strings — let the agent render.
- Tool docstrings are the tool descriptions the agent sees: make them precise about what each returns and that `NOT_FOUND` means "unverified," not "proven fake."
- Reuse the same config object as the CLI.
- **LLM injection:** instantiate `MCPSamplingClient(ctx)` inside each tool handler using the FastMCP request context, then pass it to `engine.verify()`. This is the only place sampling wiring lives — core stays clean.
- Declare the `sampling` capability when constructing the FastMCP app so the host knows to offer it:
  ```python
  mcp = FastMCP("refsift", capabilities={"sampling": {}})
  ```
- If `ctx.sample()` raises (host doesn't support sampling), catch and degrade to `relevance = SKIPPED`.

### Claude Desktop wiring (put in README)

```json
{
  "mcpServers": {
    "refsift": {
      "command": "uvx",
      "args": ["refsift-mcp"],
      "env": { "REFSIFT_MAILTO": "you@example.com" }
    }
  }
}
```

No LLM API key required — content relevance is handled via MCP sampling, routed back through the host (Claude Desktop). `DEEPSEEK_API_KEY` is only needed when running the CLI standalone.
(Expose a console-script entry point `refsift-mcp` in `pyproject.toml` that runs `mcp_server:main`. Document the `uv`/`pip install -e .` dev path too.)

---

## 10. Packaging (`pyproject.toml`)

- pip-installable, `requires-python = ">=3.10"` (MCP SDK floor).
- Two entry points: `refsift = refsift.cli:app` and `refsift-mcp = refsift.mcp_server:main`.
- Deps: `httpx`, `pydantic>=2`, `typer`, `rich`, `rapidfuzz`, `bibtexparser`, `rispy`, `pdfminer.six`, `mcp[cli]`, `platformdirs` (cache location).
- Optional extra `[pdf]`: `refextract`/`anystyle` wrapper or GROBID client for higher-accuracy PDF structured extraction (beyond the baseline `pdfminer.six` text extraction).
- Optional extra `[cli-llm]`: `openai` — for DeepSeek and any OpenAI-compatible endpoint; only needed for CLI relevance checks.
- Optional extra `[domain]`: no additional deps (PubMed and DBLP both use plain HTTP/JSON via `httpx`); the extra exists as an install marker and to document intent. Installing `refsift[domain]` signals that domain adapters are enabled by default rather than auto-detected only.
- Dev extra: `pytest`, `pytest-asyncio`, `respx` (mock httpx), `ruff`.

---

## 11. Build order (milestones for Claude Code)

Build and test each milestone before the next. Each ends with something runnable.

- **M0 — skeleton.** Repo, `pyproject.toml`, `models.py` (Reference + verdict enums + VerificationReport), `config.py`, empty engine returning a stub report. `refsift check-one` prints the stub. CI + ruff + one trivial test.
- **M1 — existence, one source.** OpenAlex adapter + DOI lookup + BibTeX parser + fuzzy matching + existence check. `refsift check file.bib` produces real `VERIFIED`/`METADATA_MISMATCH`/`NOT_FOUND` verdicts. This is the minimum viable tool.
- **M2 — full parsing + more sources + URLs + cache.** All format parsers (RIS, CSL JSON, NBIB, DOI list, plaintext splitter with style detection and LLM fallback, PDF text extraction). `detect.py` dispatcher. Crossref + Semantic Scholar + arXiv + PubMed + DBLP adapters. `url_liveness` check. SQLite cache. Stdin (`-`) support. `--style` override flag. Async concurrency. After M2, `refsift check -` with a pasted reference section of any common style works end-to-end.
- **M3 — relevance + cascade.** LLM layer (DeepSeek for CLI), `relevance` check, the tiered cascade with early-exit, `--no-llm` path. All three checks combine in one pass.
- **M4 — MCP server.** Wrap the M3 engine in FastMCP over stdio, add the three tools, declare the `sampling` capability, inject `MCPSamplingClient` per tool call, wire + test in Claude Desktop. Verify content relevance works with no API key set. Higher-accuracy PDF extraction (refextract/GROBID) as an optional extra.

A reference is `DONE` only when both `refsift check` (CLI) and the MCP `verify_reference` tool return identical verdicts for the same input — that equivalence is the proof the "one tool, two frontends" rule held.

---

## 12. Test fixtures to create early (`tests/fixtures/`)

Hand-build a small labeled set so checks are verifiable, not vibes:
- 5 known-real references (with DOIs) → expect `VERIFIED`.
- 5 plausibly-fabricated references (real-looking title, no such paper) → expect `NOT_FOUND`.
- 5 real papers with one corrupted field (wrong year/author) → expect `METADATA_MISMATCH`.
- 5 references with URLs: 2 live, 2 dead (404), 1 redirected.
- 2 live URLs whose content is unrelated to the citation → expect `CONTENT_DRIFT`.
- 2 real biomedical papers (PubMed-indexed, not in OpenAlex core) → verify PubMed adapter finds them when core sources return nothing.
- 2 real CS papers (DBLP-indexed conference papers, e.g. old VLDB/SIGMOD proceedings) → verify DBLP adapter finds them when core sources return nothing.
- 1 raw reference section per style (IEEE, APA, Vancouver, MLA) as `.txt` fixtures → verify splitter produces the correct number of chunks and style detection matches.
- 1 PDF-copy-paste fixture with hyphenated line-breaks and mid-reference newlines → verify cleanup produces clean chunks.
- 1 RIS file and 1 CSL JSON file (Zotero exports) → verify format parsers round-trip to `Reference` correctly.
- 1 raw NBIB export from PubMed → verify nbib parser extracts PMID, title, authors, journal correctly.

---

## 13. Guardrails (state these in `CLAUDE.md` too)

- Never label a reference "fake"/"fraudulent" — only "could not verify / needs review."
- Never bypass CAPTCHA or bot-protection to force a 2xx; classify as `SKIPPED`.
- Never hardcode API keys; read from env; degrade gracefully when absent. When running as MCP server, no LLM key is needed — use MCP sampling instead.
- Core stays frontend-agnostic. MCP stdout stays clean (stderr/file logging only).
- Always send `mailto` to OpenAlex/Crossref; respect rate limits and cache aggressively.
- Report counts honestly: surface how many references were checked, skipped, and errored — don't silently drop.
