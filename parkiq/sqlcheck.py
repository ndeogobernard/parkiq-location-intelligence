"""SQL validation of a run GeoPackage (SQLite), generated from ``schema.yaml`` (ADR-0088).

The pipeline validates every write in Python (``schema.conform``); this module checks the
finished GeoPackage independently, in SQL, so any tool that edits it (ArcGIS Pro, QGIS, a script)
can be re-checked:

* **domain**: coded fields hold only their domain's values; range fields stay in range
* **required**: non-nullable fields have no NULLs
* **unique**: unique keys have no duplicates
* **orphans**: every relationship key in a destination table exists in its origin table
* **signature queries** (SCOPE Appendix D, `docs/queries/`): the hot-zone query must return
  exactly the hexagons the gap step qualified; the shortlist query runs once SiteFinancials
  has rows (M6)

Every generated statement is written to ``sql_checks.sql`` in the run folder with its result, so
the checks can be rerun by hand in any SQLite client.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from parkiq.schema import Schema
from parkiq.schema_build import layer_fields

QUERIES = Path(__file__).resolve().parents[1] / "docs" / "queries"


@dataclass
class SqlCheck:
    """One SQL check: the statement returns the number of violating rows."""

    kind: str
    table: str
    name: str
    sql: str
    count: int | None = None
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.count == 0


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(v: object) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})")}


def _rows(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0])


def generate(con: sqlite3.Connection, schema: Schema) -> list[SqlCheck]:
    """Checks for every schema layer/table present with rows in the GeoPackage."""
    have = _tables(con)
    out: list[SqlCheck] = []
    for name, ldef in schema.layers.items():
        if name not in have or ldef.raw or _rows(con, name) == 0:
            continue
        cols = _columns(con, name)
        t = _q(name)
        for f in layer_fields(schema, ldef):
            if f.name not in cols:
                continue
            c = _q(f.name)
            if f.domain:
                d = schema.domains[f.domain]
                if d["type"] == "coded":
                    values = ", ".join(_lit(v) for v in d["values"])
                    sql = (
                        f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c} NOT IN ({values})"
                    )
                else:
                    sql = f"SELECT COUNT(*) FROM {t} WHERE {c} < {d['min']} OR {c} > {d['max']}"
                out.append(SqlCheck("domain", name, f"{f.name} in {f.domain}", sql))
            if not f.nullable:
                sql = f"SELECT COUNT(*) FROM {t} WHERE {c} IS NULL"
                out.append(SqlCheck("required", name, f"{f.name} not null", sql))
            if f.unique:
                sql = (
                    f"SELECT COUNT(*) FROM (SELECT {c} FROM {t} WHERE {c} IS NOT NULL "
                    f"GROUP BY {c} HAVING COUNT(*) > 1)"
                )
                out.append(SqlCheck("unique", name, f"{f.name} unique", sql))
    for r in schema.relationships:
        o, d = r["origin"], r["destination"]
        if o not in have or d not in have or d == "*" or _rows(con, d) == 0:
            continue
        ok, dk = _q(r["origin_key"]), _q(r["destination_key"])
        if r["origin_key"] not in _columns(con, o) or r["destination_key"] not in _columns(con, d):
            continue
        prefix, members = r.get("assembly_prefix"), r.get("members_field")
        skip = f" AND {dk} NOT LIKE {_lit(prefix + '%')}" if prefix else ""
        sql = (
            f"SELECT COUNT(*) FROM {_q(d)} WHERE {dk} IS NOT NULL{skip} "
            f"AND {dk} NOT IN (SELECT {ok} FROM {_q(o)} WHERE {ok} IS NOT NULL)"
        )
        out.append(SqlCheck("orphans", d, f"{r['name']}: {d}.{r['destination_key']} in {o}", sql))
        if members and members in _columns(con, d):
            m = _q(members)
            sql = (  # split the ';'-joined member ids and look each one up
                f"WITH RECURSIVE split(id, rest) AS (SELECT '', {m} || ';' FROM {_q(d)} "
                f"WHERE {m} IS NOT NULL UNION ALL SELECT substr(rest, 1, instr(rest, ';') - 1), "
                f"substr(rest, instr(rest, ';') + 1) FROM split WHERE rest <> '') "
                f"SELECT COUNT(*) FROM split WHERE id <> '' "
                f"AND id NOT IN (SELECT {ok} FROM {_q(o)} WHERE {ok} IS NOT NULL)"
            )
            out.append(SqlCheck("orphans", d, f"{r['name']}: {d}.{members} in {o}", sql))
    return out


def signature_checks(con: sqlite3.Connection, run_dir: Path | None) -> list[SqlCheck]:
    """SCOPE Appendix D queries: consistency with the pipeline's own results."""
    out: list[SqlCheck] = []
    have = _tables(con)
    hot = (QUERIES / "hot_zone_hexes.sql").read_text(encoding="utf-8").strip().rstrip(";")
    if "Hex_Gap_Daypart" in have and _rows(con, "Hex_Gap_Daypart"):
        n_sql = int(con.execute(f"SELECT COUNT(*) FROM ({hot})").fetchone()[0])
        rep = {}
        if run_dir is not None and (run_dir / "gap_report.json").exists():
            rep = json.loads((run_dir / "gap_report.json").read_text(encoding="utf-8"))
        expected = rep.get("hexes_qualifying")
        chk = SqlCheck("signature", "Hex_Gap_Daypart", "Appendix D hot-zone hexes = gap step", hot)
        chk.count = abs(n_sql - int(expected)) if expected is not None else 0
        chk.note = f"SQL {n_sql:,} hexes; gap step {expected if expected is not None else 'n/a'}"
        out.append(chk)
    short = (QUERIES / "shortlist_returns.sql").read_text(encoding="utf-8").strip().rstrip(";")
    if "SiteFinancials" in have and _rows(con, "SiteFinancials"):
        run_id = run_dir.name if run_dir else ""
        rows = con.execute(short, {"run_id": run_id}).fetchall()
        chk = SqlCheck("signature", "SiteFinancials", "Appendix D shortlist query runs", short, 0)
        chk.note = f"{len(rows)} rows"
        out.append(chk)
    else:
        out.append(
            SqlCheck(
                "signature",
                "SiteFinancials",
                "Appendix D shortlist query",
                short,
                0,
                "not run: SiteFinancials has no rows until M6",
            )
        )
    return out


def run(gpkg: Path, schema: Schema, run_dir: Path | None = None) -> list[SqlCheck]:
    """Run every check; write sql_checks.sql and sql_check_report.json next to the GeoPackage."""
    with closing(sqlite3.connect(gpkg)) as con:
        checks = generate(con, schema)
        for c in checks:
            c.count = int(con.execute(c.sql).fetchone()[0])
        checks += signature_checks(con, run_dir)
    folder = run_dir or gpkg.parent
    lines = [
        f"-- ParkIQ SQL validation of {gpkg.name} (SQLite). Each statement counts violating rows.",
        "",
    ]
    for c in checks:
        lines += [
            f"-- [{c.kind}] {c.table}: {c.name} -> {c.count} {c.note}".rstrip(),
            c.sql + ";",
            "",
        ]
    (folder / "sql_checks.sql").write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "checks": len(checks),
        "failed": [f"{c.kind} {c.table}: {c.name} ({c.count})" for c in checks if not c.passed],
        "by_kind": {
            k: sum(1 for c in checks if c.kind == k) for k in dict.fromkeys(c.kind for c in checks)
        },
        "notes": [f"{c.name}: {c.note}" for c in checks if c.note],
    }
    (folder / "sql_check_report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return checks
