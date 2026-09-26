"""Project text rules (ADR-0083): no em dash in tracked text; ParkIQ cards show only live links."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_text", REPO / "scripts" / "check_text.py")
assert _spec and _spec.loader
check_text = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_text)


def test_no_em_dash_in_tracked_text_files() -> None:
    assert check_text.tracked_violations(REPO) == []


def test_site_rules_flag_parkiq_cards_only(tmp_path: Path) -> None:
    em = chr(0x2014)
    html = (
        '<article class="project-card"><img src="assets/parkiq/a.jpg"/>'
        f'<h3 class="card-title">ParkIQ A</h3><span>Demo {em} coming soon</span></article>'
        '<article class="project-card"><h3 class="card-title">Other</h3>'
        f"<span>Report {em} coming soon</span></article>"
    )
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    out = check_text.site_violations(tmp_path)
    assert out == ["ndeogo card 'ParkIQ A': em dash", "ndeogo card 'ParkIQ A': 'coming soon' item"]
