"""Portfolio reports: Markdown source → HTML → PDF, numbers pulled from run outputs (ADR-0077).

A report source (``docs/portfolio/<slug>.md``) uses ``{{key}}`` placeholders; :func:`key_numbers`
computes every value from the run GeoPackage and ``schema.yaml``, nothing is typed by hand, and a
placeholder without a value stops the build. The HTML is printed to PDF by a headless Chromium
browser (Edge/Chrome), matching the site's existing ``<slug>-documentation.md.pdf`` files, with a
running header, page numbers and repo/site links added by CSS.
"""

from __future__ import annotations

import html
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

import markdown
import pandas as pd
import pyogrio

from parkiq.schema import Schema
from parkiq.schema_build import describe, schema_diff

REPO_URL = "https://github.com/ndeogobernard/parkiq-location-intelligence"
SITE_URL = "https://ndeogobernard.github.io/ndeogo/"
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def _fmt(v: float | int) -> str:
    return f"{round(v):,}"


def key_numbers(run_dir: Path, schema: Schema, crs: Any) -> dict[str, str]:
    """Every number a report may quote, computed from the run and the schema."""
    gpkg = next(run_dir.glob("ParkIQ_*.gpkg"))
    d = describe(schema)
    n_fields = sum(len(x.fields) for x in schema.layers.values() if not x.raw)
    reg = pyogrio.read_dataframe(gpkg, layer="DataSourceRegistry", read_geometry=False)
    qa = pyogrio.read_dataframe(gpkg, layer="QAQC_Log", read_geometry=False)
    with closing(sqlite3.connect(gpkg)) as con:
        written = con.execute('SELECT COUNT(*) FROM "_ParkIQ_Layers"').fetchone()[0]
        parcels = con.execute('SELECT COUNT(*) FROM "Parcels"').fetchone()[0]
        hexes = con.execute('SELECT COUNT(*) FROM "HexGrid"').fetchone()[0]
    diffs = schema_diff(gpkg, schema, crs)
    return {
        "feature_classes": _fmt(d["feature_classes"]),
        "tables": _fmt(d["tables"]),
        "raw_layers": _fmt(d["raw_layers"]),
        "domains": _fmt(d["domains"]),
        "relationships": _fmt(d["relationships"]),
        "schema_fields": _fmt(n_fields),
        "schema_version": schema.version,
        "layers_in_run": _fmt(written),
        "schema_diff": "0 differences" if not diffs else f"{len(diffs)} differences",
        "sources_loaded": _fmt(int((reg["status"] == "loaded").sum())),
        "sources_not_configured": _fmt(int((reg["status"] == "not configured").sum())),
        "qa_checks": _fmt(len(qa)),
        "qa_errors_failed": _fmt(
            int(((~qa["passed"].astype(bool)) & (qa["severity"] == "error")).sum())
        ),
        "parcels": _fmt(parcels),
        "hexes": _fmt(hexes),
        "run_id": run_dir.name,
        "report_date": date.today().isoformat(),
        "repo_url": REPO_URL,
        "site_url": SITE_URL,
        "sources_table": sources_table(reg),
    }


EM = chr(0x2014)  # em dash: not allowed in project text (ADR-0083)


def plain(v: object) -> str:
    """Registry text written before ADR-0083 may hold em dashes: rewrite them as commas."""
    return str(v).replace(f" {EM} ", ", ").replace(EM, ", ")


def sources_table(reg: pd.DataFrame) -> str:
    """Markdown table of loaded sources: source, vintage, licence."""
    r = reg[reg["status"] == "loaded"].sort_values("source_id")
    rows = ["| Source | Dataset | Vintage | Licence |", "|---|---|---|---|"]
    for x in r.itertuples():
        lic = str(x.license or "").replace("[VERIFY]", "(to confirm)")
        rows.append(
            f"| {plain(x.provider)} | {plain(x.dataset)} | {plain(x.vintage or 'n/a')} | {plain(lic)} |"
        )
    return "\n".join(rows)


CSS = """
@page { size: Letter; margin: 0.8in 0.75in 0.8in 0.75in;
  @top-left { content: "ParkIQ · %(short)s"; font: 9pt Segoe UI, Arial; color: #666; }
  @top-right { content: "%(draft)s"; font: bold 9pt Segoe UI, Arial; color: #c0392b; }
  @bottom-left { content: "%(links)s"; font: 8pt Segoe UI, Arial; color: #666; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 9pt Segoe UI, Arial; color: #666; } }
body { font: 10.5pt/1.45 "Segoe UI", Arial, sans-serif; color: #222; }
h1 { font-size: 22pt; margin: 0 0 4pt; } h1 + p { font-size: 12pt; color: #444; margin-top: 0; }
h2 { font-size: 14pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; margin-top: 16pt; }
.keybox { border: 1px solid #9ecae1; background: #f1f7fc; padding: 8pt 12pt; margin: 10pt 0; }
.keybox table { width: 100%%; border-collapse: collapse; } .keybox td { padding: 2pt 6pt; }
.keybox td.n { font-weight: bold; font-size: 13pt; color: #08519c; text-align: right; width: 22%%; }
table { border-collapse: collapse; font-size: 9pt; } th, td { border-bottom: 1px solid #ddd; padding: 3pt 5pt; text-align: left; }
figure { margin: 8pt 0; page-break-inside: avoid; text-align: center; } figure img { max-width: 100%%; max-height: 4.3in; }
figcaption { font-size: 9pt; color: #555; margin-top: 3pt; text-align: left; }
.sources table { font-size: 7.5pt; } .sources td, .sources th { padding: 1.5pt 4pt; }
code { font-size: 9pt; background: #f4f4f4; padding: 0 2pt; }
"""


def render(
    source: Path, out_pdf: Path, values: dict[str, str], short_title: str, draft: bool = True
) -> Path:
    """Fill placeholders, convert to HTML and print to PDF."""
    text = source.read_text(encoding="utf-8")
    missing = sorted({m for m in PLACEHOLDER.findall(text) if m not in values})
    if missing:
        raise KeyError(f"{source.name}: no value for placeholders {missing}")
    text = PLACEHOLDER.sub(lambda m: values[m.group(1)], text)
    if EM in text:
        raise ValueError(f"{source.name}: em dash in report text (ADR-0083)")
    body = markdown.markdown(text, extensions=["tables", "md_in_html", "attr_list"])
    base = source.parent.resolve()
    body = re.sub(
        r'src="(?!https?:|file:)([^"]+)"', lambda m: f'src="{(base / m.group(1)).as_uri()}"', body
    )
    links = f"{REPO_URL}  ·  {SITE_URL}"
    css = CSS % {"short": short_title, "draft": "DRAFT" if draft else "", "links": links}
    page = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(source.stem)}"
        f"-documentation.md</title><style>{css}</style></head><body>{body}</body></html>"
    )
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.unlink(missing_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(page, encoding="utf-8")
    browser = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge")
    if browser is None:
        raise FileNotFoundError("no headless Edge/Chrome found to print the PDF")
    with (
        tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof
    ):  # isolated profile: no hand-off to a running browser
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--user-data-dir={prof}",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_pdf.resolve()}",
                html_path.resolve().as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        # the launcher can exit before its child finishes writing: wait for a stable file
        last = -1
        for _ in range(120):
            size = out_pdf.stat().st_size if out_pdf.exists() else -1
            if size > 0 and size == last:
                break
            last = size
            time.sleep(0.5)
    if not out_pdf.exists():
        raise RuntimeError(f"browser did not write {out_pdf}")
    return out_pdf
