"""Private partner documents: memo template keys have sources; checklist rules."""

from __future__ import annotations

import re
from types import SimpleNamespace

from parkiq import portfolio, report

# keys memo_numbers() provides (each with a source); the trace table is built from them
MEMO_KEYS = {
    "market_name", "run_id", "analysis_month", "stalls_min", "stalls_max", "parcels", "hexes",
    "sources_loaded", "qa_checks", "qa_errors", "sql_checks", "sql_failed", "anchors",
    "demand_wd_day", "demand_wd_eve", "demand_we_day", "demand_we_eve", "attendance_factor",
    "mapped_facilities", "metered_faces", "estimated_parcels", "estimated_stalls", "paid_hexes",
    "paid_zones", "paid_zones_50", "context_zones", "within_reach", "candidates", "cand_pass",
    "cand_review", "assemblies", "existing_only", "zone_a", "owner_flagged", "top10_east",
    "largest_zone_name", "largest_zone_gap", "largest_zone_candidates", "top10_table",
    "benchmark_table", "sources_table", "parameters_table",
}  # fmt: skip


def test_every_memo_placeholder_has_a_source() -> None:
    used = set(portfolio.PLACEHOLDER.findall(report.TEMPLATE.read_text(encoding="utf-8")))
    assert used - {"trace_table"} <= MEMO_KEYS
    src = (report.REPO / "parkiq" / "report.py").read_text(encoding="utf-8")
    for key in MEMO_KEYS:  # each key is set in memo_numbers() with a (value, source) pair
        assert re.search(rf'n\[(f"demand_{{dp}}"|"{key}")\]', src), key


def test_memo_template_marks_finance_as_m6() -> None:
    text = report.TEMPLATE.read_text(encoding="utf-8")
    assert text.count("[M6]") >= 5 and chr(0x2014) not in text


def test_checklist_rules() -> None:
    c = SimpleNamespace(
        zoning_code="DD", zoning_screen="Prohibited", existing_lot_flag=True, zone_a_flag=True,
        screen_reason="zoning: near Zone A/B boundary", owner_feasibility=float("nan"),
        flood_flag=False, arterial_flag=True, assembled_count=3,
    )  # fmt: skip
    items = report.checklist(c)
    text = " | ".join(items)
    assert "legal nonconforming status" in text and "Zone A" in text and "Assembly of 3" in text
    assert "arterial" in text and "Owner:" not in text  # NaN owner flag is not a string
