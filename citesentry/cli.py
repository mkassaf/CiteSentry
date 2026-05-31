from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from citesentry.models import Verdict, VerificationReport

app = typer.Typer(name="citesentry", help="Citation verification: existence, URL liveness, relevance.")
console = Console()
err_console = Console(stderr=True)

_VERDICT_STYLES = {
    Verdict.VERIFIED: "green",
    Verdict.METADATA_MISMATCH: "yellow",
    Verdict.DEAD_URL: "red",
    Verdict.CONTENT_DRIFT: "magenta",
    Verdict.NOT_FOUND: "bold red",
    Verdict.UNRESOLVABLE: "dim",
}


def _build_sources():
    from citesentry.sources.crossref import CrossrefAdapter
    from citesentry.sources.openalex import OpenAlexAdapter
    from citesentry.sources.semantic_scholar import SemanticScholarAdapter
    from citesentry.sources.arxiv import ArXivAdapter

    return [CrossrefAdapter(), OpenAlexAdapter(), SemanticScholarAdapter(), ArXivAdapter()]


def _make_options(
    no_llm: bool,
    no_url: bool,
    mailto: str | None,
    concurrency: int,
    no_cache: bool,
    domain: str,
    model: str | None,
):
    from citesentry.core.cascade import VerifyOptions
    from citesentry.config import get_settings

    if mailto:
        settings = get_settings()
        settings.mailto = mailto

    llm_client = None
    if not no_llm:
        from citesentry.llm.deepseek import make_deepseek_client
        llm_client = make_deepseek_client()

    return VerifyOptions(
        check_url=not no_url,
        check_relevance=not no_llm,
        use_cache=not no_cache,
        sources=_build_sources(),
        llm_client=llm_client,
        concurrency=concurrency,
        domain_mode=domain,
    )


def _render_table(reports: list[VerificationReport]) -> None:
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Title / Raw", max_width=50, overflow="fold")
    table.add_column("Verdict", min_width=20)
    table.add_column("Notes", max_width=50, overflow="fold")

    for r in reports:
        title = r.reference.title or r.reference.raw[:60] or "(unknown)"
        verdict_label = r.verdict_display()
        style = _VERDICT_STYLES.get(r.overall_verdict, "")
        notes = "; ".join(r.notes[:2]) if r.notes else ""
        table.add_row(title, f"[{style}]{verdict_label}[/{style}]", notes)

    console.print(table)

    total = len(reports)
    bad = sum(
        1 for r in reports
        if r.overall_verdict in (Verdict.NOT_FOUND, Verdict.DEAD_URL, Verdict.METADATA_MISMATCH, Verdict.CONTENT_DRIFT)
    )
    verified = sum(1 for r in reports if r.overall_verdict == Verdict.VERIFIED)
    console.print(
        f"\n[bold]Total:[/bold] {total}  "
        f"[green]Verified: {verified}[/green]  "
        f"[red]Issues: {bad}[/red]  "
        f"[dim]Other: {total - verified - bad}[/dim]"
    )


def _render_md(reports: list[VerificationReport]) -> str:
    lines = ["# Reference Verification Report", ""]
    for r in reports:
        title = r.reference.title or r.reference.raw[:60] or "(unknown)"
        lines.append(f"## {title}")
        lines.append(f"**Verdict:** {r.verdict_display()}")
        if r.reference.doi:
            lines.append(f"**DOI:** {r.reference.doi}")
        if r.notes:
            lines.append("**Notes:**")
            for n in r.notes:
                lines.append(f"- {n}")
        for c in r.checks:
            lines.append(f"- `{c.name}`: {c.status.value} (confidence={c.confidence:.2f})")
        lines.append("")
    return "\n".join(lines)


@app.command("check")
def check_cmd(
    file: str = typer.Argument(..., help="Reference file or '-' for stdin"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, md"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM relevance check"),
    no_url: bool = typer.Option(False, "--no-url", help="Skip URL liveness check"),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model"),
    mailto: Optional[str] = typer.Option(None, "--mailto", help="Email for API politeness"),
    concurrency: int = typer.Option(8, "--concurrency", "-c", help="Max concurrent checks"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable SQLite cache"),
    domain: str = typer.Option("auto", "--domain", help="Domain adapters: auto, pubmed, dblp, all, none"),
    style: Optional[str] = typer.Option(None, "--style", help="Override plaintext style detection"),
):
    """Verify references from a file or stdin."""
    if file == "-":
        text = sys.stdin.read()
        from citesentry.parse.detect import _sniff_and_parse as parse
        refs = parse(text)
    else:
        from citesentry.parse.detect import auto_parse
        refs = auto_parse(Path(file))

    if not refs:
        err_console.print("[yellow]No references found in input.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[dim]Parsed {len(refs)} reference(s). Checking...[/dim]")

    opts = _make_options(no_llm, no_url, mailto, concurrency, no_cache, domain, model)
    from citesentry.core.engine import verify_many
    reports = asyncio.run(verify_many(refs, opts))

    if format == "json":
        print(json.dumps([r.model_dump(mode="json") for r in reports], indent=2))
    elif format == "md":
        print(_render_md(reports))
    else:
        _render_table(reports)

    bad_verdicts = {Verdict.NOT_FOUND, Verdict.DEAD_URL}
    if any(r.overall_verdict in bad_verdicts for r in reports):
        raise typer.Exit(1)


@app.command("check-one")
def check_one_cmd(
    reference: str = typer.Argument(..., help="Raw reference string"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, md"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    no_url: bool = typer.Option(False, "--no-url"),
    mailto: Optional[str] = typer.Option(None, "--mailto"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    domain: str = typer.Option("auto", "--domain"),
):
    """Verify a single raw reference string."""
    from citesentry.parse.plaintext import extract_fields, detect_style, Style

    ref = extract_fields(reference, Style.UNKNOWN)

    opts = _make_options(no_llm, no_url, mailto, 1, no_cache, domain, None)
    from citesentry.core.engine import verify_one
    report = asyncio.run(verify_one(ref, opts))

    if format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    elif format == "md":
        print(_render_md([report]))
    else:
        _render_table([report])

    if report.overall_verdict in {Verdict.NOT_FOUND, Verdict.DEAD_URL}:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
