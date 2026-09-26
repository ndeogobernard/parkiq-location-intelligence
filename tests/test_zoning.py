"""Zoning table loader and resolver, against the Franklin draft table and the GIS code list."""

from __future__ import annotations

from pathlib import Path

import pytest

from parkiq.zoning import ZoningTable, ZoningTableError

TABLE = Path(__file__).parents[1] / "markets" / "franklin_oh" / "zoning_screen.csv"
ALIASES = {"RURAL": "R"}
# Every CLASSIFICATION value in the Columbus Base Zoning Districts layer (2026-09-24, 78 values).
# fmt: off
GIS_CODES = [
    "AR1", "AR12", "AR2", "AR3", "AR4", "ARLD", "ARO", "C1", "C2", "C3", "C4", "C5", "CAC",
    "CPD", "DD", "EFD", "EQ", "I", "LAR1", "LAR12", "LAR2", "LAR3", "LAR4", "LARLD", "LARO",
    "LC1", "LC2", "LC3", "LC4", "LC5", "LI", "LM", "LM1", "LM2", "LMHP", "LP1", "LP2", "LR",
    "LR1", "LR2", "LR2F", "LR4", "LRR", "LRRR", "LSR", "LUCRPD", "M", "M1", "M2", "MHD",
    "MHP", "NC", "NE", "NG", "P1", "P2", "PC", "PUD2", "PUD4", "PUD6", "PUD8", "R1", "R2",
    "R2F", "R3", "R4", "RAC", "RR", "RRR", "RURAL", "SR", "TC", "UCR", "UCR-R", "UCRPD",
    "UCT", "UGN-1", "UGN-2",
]
# fmt: on


@pytest.fixture(scope="module")
def table() -> ZoningTable:
    return ZoningTable.load(TABLE, ALIASES)


def test_every_gis_code_matches_a_row(table: ZoningTable) -> None:
    unmatched = [c for c in GIS_CODES if table.match_code("Columbus", c)[0] is None]
    assert unmatched == []


@pytest.mark.parametrize(
    "gis, row, limited",
    [
        ("C4", "C-4", False),
        ("LC4", "C-4", True),
        ("UCR-R", "UCR-R", False),
        ("UCR", "UCR", False),
        ("LRR", "LRR", False),  # a real district, not L + RR
        ("LRRR", "RRR", True),
        ("LR", "R", True),
        ("RURAL", "R", False),
        ("PUD8", "PUD", False),
        ("LUCRPD", "UCRPD", True),
        ("ARO", "AR-O", False),
        ("R2F", "R-2F", False),
    ],
)
def test_code_matching(table: ZoningTable, gis: str, row: str, limited: bool) -> None:
    r, lim = table.match_code("Columbus", gis)
    assert r is not None and r.zoning_code == row and lim is limited


def test_routes(table: ZoningTable) -> None:
    assert table.resolve("Columbus", "C4").route == "Pass"
    assert table.resolve("Columbus", "UCR").route == "Fail"  # High-confidence Prohibited
    c1 = table.resolve("Columbus", "C1")  # Low-confidence Prohibited
    assert (c1.zoning_screen, c1.route) == ("Prohibited", "Review") and "Low" in c1.reason
    assert table.resolve("Columbus", "CPD").route == "Review"
    assert table.resolve("Columbus", "P1").route == "Fail"
    for res in ("R1", "RR", "AR12", "ARLD", "MHP", "RURAL"):  # residential: High -> Fail
        r = table.resolve("Columbus", res)
        assert (r.zoning_screen, r.confidence, r.route) == ("Prohibited", "High", "Fail"), res
    for amb in ("C1", "C2", "EFD", "NG", "TC", "M2", "EQ"):  # ambiguous: Low -> Review
        assert table.resolve("Columbus", amb).route == "Review", amb


def test_limited_overlay_uses_base_and_reviews(table: ZoningTable) -> None:
    r = table.resolve("Columbus", "LC4")
    assert (r.zoning_screen, r.route) == ("ByRight", "Review")
    assert "limitation text applies" in r.reason and "C-4" in r.reason


def test_downtown_parking_zones(table: ZoningTable) -> None:
    dd = table.resolve("Columbus", "DD")  # zone unknown -> Review, not Pass
    assert (dd.zoning_screen, dd.route) == ("Unknown", "Review")
    a = table.resolve("Columbus", "DD", parking_zone="A")
    assert (a.zoning_screen, a.route) == ("Prohibited", "Fail")
    assert table.resolve("Columbus", "DD", parking_zone="B").route == "Pass"
    near = table.resolve("Columbus", "DD", parking_zone="B", near_zone_boundary=True)
    assert near.route == "Review" and "near digitized Zone A/B boundary" in near.reason
    near_a = table.resolve("Columbus", "DD", parking_zone="A", near_zone_boundary=True)
    assert near_a.route == "Review"  # the traced line is approximate: either side may be wrong


def test_overlays(table: ZoningTable) -> None:
    uco = table.resolve("Columbus", "C4", overlays=["overlay:UCO"])
    assert uco.route == "Pass" and "overlay:UCO" in uco.reason
    uni = table.resolve("Columbus", "C4", overlays=["overlay:University/NC"])
    assert uni.route == "Review" and uni.zoning_screen == "Unknown"


def test_other_jurisdictions_review_never_fail(table: ZoningTable) -> None:
    for j in ("Dublin", "Worthington", "Upper Arlington", None):
        r = table.resolve(j, "C-4")
        assert (r.zoning_screen, r.route) == ("Unknown", "Review")


def test_unknown_columbus_code_reviews(table: ZoningTable) -> None:
    r = table.resolve("Columbus", "ZZ9")
    assert r.route == "Review" and "not in table" in r.reason


def test_bad_table_rejected(tmp_path: Path) -> None:
    p = tmp_path / "t.csv"
    p.write_text(
        "jurisdiction,zoning_code,district_name,commercial_parking_use,confidence,"
        "confidence_reason,ordinance_citation,verified_date,notes\n"
        "X,A,a,Maybe,High,r,c,,n\n",
        encoding="utf-8",
    )
    with pytest.raises(ZoningTableError, match="commercial_parking_use"):
        ZoningTable.load(p)
