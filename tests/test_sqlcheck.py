"""SQL validation (ADR-0088): generated checks catch domain, null, duplicate and orphan rows.

A tiny SYNTHETIC SQLite file with GeoPackage-style contents is enough: the checks only read tables.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from parkiq import sqlcheck
from parkiq.schema import Schema

SCHEMA = Schema.load(Path(__file__).resolve().parents[1] / "schema" / "schema.yaml")


def _db(tmp: Path) -> Path:
    p = tmp / "t.gpkg"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE gpkg_contents (table_name TEXT)")
    con.executemany("INSERT INTO gpkg_contents VALUES (?)", [("Parcels",), ("CandidateParcels",)])
    con.execute(
        "CREATE TABLE Parcels (parcel_id TEXT, land_use_class TEXT, source_id TEXT, "
        "run_id TEXT, load_ts TEXT)"
    )
    con.executemany(
        "INSERT INTO Parcels VALUES (?, ?, ?, ?, ?)",
        [
            ("P1", "Vacant", "S01", "r", "t"),
            ("P2", "Spaceport", "S01", "r", "t"),  # not in dm_LandUseClass
            ("P2", "Commercial", None, "r", "t"),  # duplicate id, null source_id
        ],
    )
    con.execute(
        "CREATE TABLE CandidateParcels (parcel_id TEXT, member_parcel_ids TEXT, "
        "screen_status TEXT, source_id TEXT, run_id TEXT, load_ts TEXT)"
    )
    con.executemany(
        "INSERT INTO CandidateParcels VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("P1", None, "Pass", "DERIVED", "r", "t"),
            ("P9", None, "Review", "DERIVED", "r", "t"),  # orphan: no parcel P9
            ("ASM:P1", "P1;P7", "Review", "DERIVED", "r", "t"),  # assembly with unknown member P7
        ],
    )
    con.commit()
    con.close()
    return p


def test_sql_checks_catch_violations(tmp_path: Path) -> None:
    checks = sqlcheck.run(_db(tmp_path), SCHEMA, tmp_path)
    failed = {(c.kind, c.table, c.name): c.count for c in checks if not c.passed}
    assert failed[("domain", "Parcels", "land_use_class in dm_LandUseClass")] == 1
    assert failed[("unique", "Parcels", "parcel_id unique")] == 1
    assert failed[("required", "Parcels", "source_id not null")] == 1
    orphans = {k[2]: v for k, v in failed.items() if k[0] == "orphans"}
    assert (
        orphans["Parcels_CandidateParcels: CandidateParcels.parcel_id in Parcels"] == 1
    )  # P9 only
    assert orphans["Parcels_CandidateParcels: CandidateParcels.member_parcel_ids in Parcels"] == 1
    assert (tmp_path / "sql_checks.sql").read_text(encoding="utf-8").count("SELECT COUNT(*)") >= 5


def test_clean_rows_pass(tmp_path: Path) -> None:
    p = _db(tmp_path)
    con = sqlite3.connect(p)
    con.execute("DELETE FROM Parcels WHERE parcel_id = 'P2'")
    con.execute("INSERT INTO Parcels VALUES ('P7', 'Vacant', 'S01', 'r', 't')")
    con.execute("DELETE FROM CandidateParcels WHERE parcel_id = 'P9'")
    con.commit()
    con.close()
    assert all(c.passed for c in sqlcheck.run(p, SCHEMA, tmp_path))
