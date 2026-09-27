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
    assert "ndeogo card 'ParkIQ A': em dash" in out
    assert "ndeogo card 'ParkIQ A': 'coming soon' item" in out
    assert not any("'Other'" in o for o in out)  # non-ParkIQ cards are not checked


def test_card_structure_rules() -> None:
    gh = '<a class="card-link" href="g">GitHub</a>'
    rep = '<span class="card-link" aria-disabled="true">Report</span>'
    sm = '<span class="card-link" aria-disabled="true">StoryMap</span>'
    long = "A" * 161
    out = check_text.card_structure("C", f'<p class="card-desc">{long}</p>{gh}{rep}{sm}')
    assert any("161 > 160" in o for o in out)
    two = f'<p class="card-desc">First sentence here. Second one.</p>{gh}{rep}{sm}'
    assert any("more than one sentence" in o for o in check_text.card_structure("C", two))
    ok = f'<p class="card-desc">ParkIQ · Franklin County, OH</p>{gh}{rep}{sm}'
    assert check_text.card_structure("C", ok) == []
    wrong_order = f'<p class="card-desc">One.</p>{gh}{sm}{rep}'
    assert any("links" in o for o in check_text.card_structure("C", wrong_order))
    missing = f'<p class="card-desc">One.</p>{gh}{rep}'
    assert any("links" in o for o in check_text.card_structure("C", missing))
    live = '<span class="card-link" aria-disabled="true">Live Map</span>'
    assert (
        check_text.card_structure("Explorer", f'<p class="card-desc">One.</p>{gh}{rep}{live}') == []
    )
    no_aria = f'<p class="card-desc">One.</p>{gh}<span class="card-link">Report</span>{sm}'
    assert any("aria-disabled" in o for o in check_text.card_structure("C", no_aria))
