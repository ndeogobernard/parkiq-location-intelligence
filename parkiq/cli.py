"""``parkiq`` command line.

Argument parsing only — all logic lives in the library (docs/ENGINEERING.md).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Annotated

import typer

from parkiq.config import STEP_REQUIREMENTS, ConfigError, load_config, missing_for_step
from parkiq.config import parameter_report as _param_report
from parkiq.config import unused_items as _unused_items
from parkiq.config import verify_items as _verify_items

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ParkIQ — surface-lot site selection and underwriting.",
)

MarketOpt = Annotated[
    Path, typer.Option("--market", "-m", help="markets/<slug>.yaml", exists=True, dir_okay=False)
]


def _load(market: Path, config_dir: Path | None):  # type: ignore[no-untyped-def]
    try:
        return load_config(market, config_dir)
    except ConfigError as exc:
        typer.secho("CONFIG ERROR\n" + str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


@app.command("check-config")
def check_config(
    market: MarketOpt,
    config_dir: Annotated[Path | None, typer.Option(help="configs/ directory")] = None,
    report: Annotated[Path | None, typer.Option(help="write the parameter report CSV here")] = None,
) -> None:
    """Validate a market config; show step readiness, open [VERIFY] items and untagged values."""
    cfg = _load(market, config_dir)
    typer.secho(
        f"OK: {cfg.market.market.name} ({cfg.slug}) — {cfg.crs.to_string()}, "
        f"units {cfg.market.market.units}",
        fg=typer.colors.GREEN,
    )
    typer.echo("\nStep readiness (null DECIDE values block a step):")
    for step in STEP_REQUIREMENTS:
        miss = missing_for_step(cfg, step)
        mark = "ready  " if not miss else "BLOCKED"
        typer.echo(f"  {mark} {step:<12}" + (f" needs: {', '.join(miss)}" if miss else ""))
    ver = _verify_items(cfg)
    typer.echo(f"\n[VERIFY] items still open: {len(ver)}")
    for k, why in ver:
        typer.echo(f"  - {k}: {why}")
    unused = _unused_items(cfg)
    if unused:
        typer.echo(f"\nNot used in this market ({len(unused)}):")
        for k, why in unused:
            typer.echo(f"  - {k}: {why}")
    rows = _param_report(cfg)
    untagged = [r for r in rows if r["status"] == "UNTAGGED"]
    if untagged:
        typer.secho(
            f"\nWARNING: {len(untagged)} numeric parameters have no provenance entry:",
            fg=typer.colors.YELLOW,
        )
        for r in untagged:
            typer.echo(f"  - {r['group']}.{r['parameter']} = {r['value']}")
    if cfg.fallbacks:
        typer.echo("\nFallbacks in use: " + "; ".join(cfg.fallbacks))
    if report:
        with report.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["group", "parameter", "value", "status", "source"])
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        **r,
                        "value": json.dumps(r["value"])
                        if isinstance(r["value"], list | dict)
                        else r["value"],
                    }
                )
        typer.echo(f"\nParameter report written: {report}")


@app.command()
def run(
    market: MarketOpt,
    steps: Annotated[
        str, typer.Option(help="'all' or comma list, e.g. schema,setup,ingest")
    ] = "all",
    run_id: Annotated[str | None, typer.Option("--run-id", help="resume/continue this run")] = None,
    sources: Annotated[str | None, typer.Option(help="ingest only these ids, e.g. S01,S04")] = None,
    force: Annotated[bool, typer.Option(help="re-run steps even if inputs are unchanged")] = False,
    out: Annotated[Path | None, typer.Option(help="output root (default ./outputs)")] = None,
    config_dir: Annotated[Path | None, typer.Option(help="configs/ directory")] = None,
) -> None:
    """Run pipeline steps for a market."""
    from parkiq.runner import StepBlocked, StepNotImplemented, open_run, resolve_steps, run_steps

    cfg = _load(market, config_dir)
    try:
        names = resolve_steps(steps)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    src = [s.strip() for s in sources.split(",")] if sources else None
    ctx = open_run(cfg, run_id=run_id, out=out, force=force, source_filter=src)
    typer.echo(f"run_id: {ctx.run_id}\nfolder: {ctx.run_dir}")
    try:
        results = run_steps(ctx, names, stop_at_unimplemented=(steps.strip() == "all"))
    except (StepBlocked, StepNotImplemented) as exc:
        typer.secho(f"BLOCKED: {exc}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(3) from exc
    except Exception as exc:
        typer.secho(f"FAILED: {exc}\nlog: {ctx.log_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    for name, r in results.items():
        status = "skipped (unchanged)" if r.get("skipped") else r["status"]
        typer.echo(f"  {name:<12} {status}")
    typer.echo(f"log: {ctx.log_path}")


def _schema(schema_path: Path | None):  # type: ignore[no-untyped-def]
    from parkiq.schema import Schema

    return Schema.load(schema_path or Path(__file__).parents[1] / "schema" / "schema.yaml")


SchemaOpt = Annotated[Path | None, typer.Option("--schema", help="schema.yaml (default: repo)")]


@app.command("build-schema")
def build_schema_cmd(
    market: MarketOpt,
    out: Annotated[Path, typer.Option(help="GeoPackage to create/complete")],
    overwrite: Annotated[bool, typer.Option(help="recreate layers that already exist")] = False,
    schema: SchemaOpt = None,
    config_dir: Annotated[Path | None, typer.Option(help="configs/ directory")] = None,
) -> None:
    """Tool 1 BuildSchema: create every layer, domain and relationship on a GeoPackage."""
    from parkiq.schema_build import build_schema

    cfg = _load(market, config_dir)
    res = build_schema(out, _schema(schema), cfg.crs, overwrite=overwrite)
    typer.echo(f"{out}: {res}")


@app.command("schema-diff")
def schema_diff_cmd(
    market: MarketOpt,
    gpkg: Annotated[Path, typer.Option(help="GeoPackage to compare", exists=True)],
    schema: SchemaOpt = None,
    config_dir: Annotated[Path | None, typer.Option(help="configs/ directory")] = None,
) -> None:
    """Compare a GeoPackage with schema.yaml; exit 1 if they differ."""
    from parkiq.schema_build import schema_diff

    cfg = _load(market, config_dir)
    diffs = schema_diff(gpkg, _schema(schema), cfg.crs)
    if not diffs:
        typer.secho(f"{gpkg}: conforms to schema.yaml", fg=typer.colors.GREEN)
        return
    typer.secho(f"{gpkg}: {len(diffs)} differences", fg=typer.colors.RED)
    for d in diffs:
        typer.echo(f"  - {d}")
    raise typer.Exit(1)


@app.command("schema-docs")
def schema_docs_cmd(
    out: Annotated[Path, typer.Option(help="docs directory")] = Path("docs"),
    schema: SchemaOpt = None,
) -> None:
    """Generate ERD.drawio, ERD.png and DataDictionary.md from schema.yaml."""
    from parkiq.schema_build import write_docs

    for kind, path in write_docs(_schema(schema), out).items():
        typer.echo(f"{kind}: {path}")


@app.command("survey-package")
def survey_package_cmd(
    market: MarketOpt,
    run_id: Annotated[str, typer.Option("--run-id", help="run with SupplyFacilities")],
    strata: Annotated[Path, typer.Option(help="survey strata YAML", exists=True)],
    out: Annotated[Path | None, typer.Option(help="output folder (default: strata folder)")] = None,
    config_dir: Annotated[Path | None, typer.Option(help="configs/ directory")] = None,
) -> None:
    """Field rate survey package: sample + backups CSV, blank template, field sheet, map (PDF)."""
    from parkiq import survey
    from parkiq.runner import open_run

    cfg = _load(market, config_dir)
    ctx = open_run(cfg, run_id=run_id)
    spec = survey.load_strata(strata)
    fac = ctx.store.read_layer("SupplyFacilities")
    sample = survey.select_sample(
        fac, spec["strata"], float(spec["min_spacing_m"]), int(spec["backups_per_area"])
    )
    folder = out or strata.parent
    rnd = int(spec["round"])
    sample.to_csv(folder / f"round{rnd}_sample.csv", index=False)
    survey.write_template(folder / "survey_template.csv")
    survey.field_sheet_pdf(folder / "field_sheet.pdf", cfg.market.market.name, rnd)
    subs = ctx.store.read_layer("Submarkets")
    edges = ctx.store.read_layer("WalkEdges", columns=["highway"])
    subs["geometry"] = subs.geometry.make_valid()
    area = subs.union_all().buffer(2000)
    roads = edges[edges.intersects(area)]
    survey.sample_map_pdf(
        folder / f"round{rnd}_sample_map.pdf", sample, subs, roads,
        f"{cfg.market.market.name} — field rate survey round {rnd} (run {run_id})",
    )  # fmt: skip
    n = sample.groupby(["stratum", "role"]).size().unstack(fill_value=0)
    typer.echo(n.to_string())
    typer.echo(f"written to {folder}")


@app.command()
def validate(
    run_id: Annotated[str, typer.Option("--run-id")],
    observed: Annotated[Path, typer.Option(help="observed lots CSV")],
) -> None:
    """Pilot back-test (tool 15). Scheduled for M8."""
    typer.secho(
        "validate is scheduled for M8 (needs the pilot back-test data)", fg=typer.colors.YELLOW
    )
    raise typer.Exit(3)


@app.command()
def package(
    run_id: Annotated[str, typer.Option("--run-id")],
    gdb: Annotated[bool, typer.Option("--gdb")] = False,
    public: Annotated[
        bool,
        typer.Option(
            "--public",
            help="redact parcel IDs, owners and addresses and round financials (ADR-0055)",
        ),
    ] = False,
) -> None:
    """Export the investment package (tool 16). Scheduled for M7."""
    typer.secho("package is scheduled for M7", fg=typer.colors.YELLOW)
    raise typer.Exit(3)


@app.command()
def compare(run: Annotated[list[str], typer.Option("--run")]) -> None:
    """Diff two runs (tool 17). Scheduled for M8."""
    typer.secho("compare is scheduled for M8", fg=typer.colors.YELLOW)
    raise typer.Exit(3)


def main() -> None:  # pragma: no cover
    """Entry point for ``python -m parkiq.cli``."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
