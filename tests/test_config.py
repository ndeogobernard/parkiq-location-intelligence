"""Config validation: good/bad markets, unknown keys, units, weights, step gating."""

from __future__ import annotations

from pathlib import Path

import pytest

from parkiq.config import (
    ConfigError,
    load_config,
    missing_for_step,
    parameter_report,
    verify_items,
)
from tests.conftest import FIXTURE_DIR, FIXTURE_YAML


def test_fixture_loads(fixture_cfg) -> None:  # type: ignore[no-untyped-def]
    assert fixture_cfg.slug == "fixture"
    assert fixture_cfg.crs.to_epsg() == 32617
    # relative paths resolve against the market file
    assert Path(fixture_cfg.sources["S01"].path).is_absolute()  # type: ignore[arg-type]
    assert Path(fixture_cfg.sources["S01"].options["cama_path"]).exists()
    assert Path(fixture_cfg.market.network.graph_path).exists()  # type: ignore[arg-type]


def test_market_overrides_finance_and_ranking(fixture_cfg) -> None:  # type: ignore[no-untyped-def]
    assert fixture_cfg.finance.capture_share == 0.5  # market value
    assert fixture_cfg.finance.construction_cost_per_stall_usd == 6500  # shared default
    assert fixture_cfg.ranking.shortlist_size == 5  # ADR-0017 market wins


@pytest.mark.parametrize(
    "edit, fragment",
    [
        ({"market.bogus_key": 1}, "bogus_key"),  # unknown key
        ({"site.min_parcel_sqft": 300000}, "min_parcel_sqft must be <"),
        ({"market.units": "ft"}, "units"),  # CRS is metres
        ({"market.analysis_crs": "EPSG:4326"}, "not projected"),
        ({"demand.decay_weights": {3: 1.0, 5: 0.6}}, "decay_weights"),
        ({"demand.dayparts": ["wd_day", "wd_eve"]}, "dayparts"),
        ({"finance.not_a_param": 1}, "unknown finance keys"),
        ({"sources.S99": {"path": "x"}}, "S99"),
        ({"ranking": {"financial_weight": 0.6, "suitability_weight": 0.3}}, "sum to 1.00"),
        ({"market.focus_submarkets": ["Downtown"]}, "submarkets_source"),
    ],
)
def test_bad_configs_rejected(variant, edit, fragment) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ConfigError, match=fragment):
        load_config(variant(edit))


def test_weights_must_sum_to_one(tmp_path: Path) -> None:
    import shutil

    cdir = tmp_path / "configs"
    shutil.copytree(Path(__file__).parents[1] / "configs", cdir)
    w = (cdir / "weights.yaml").read_text(encoding="utf-8").replace("C01: 0.18", "C01: 0.19", 1)
    (cdir / "weights.yaml").write_text(w, encoding="utf-8")
    with pytest.raises(ConfigError, match=r"Balanced weights sum to 1.010000"):
        load_config(FIXTURE_YAML, cdir)


def test_decide_values_block_steps(variant) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config(
        variant({"finance.capture_share": None, "demand.transit_adjustment.peak_window": None})
    )
    assert "finance.capture_share" in missing_for_step(cfg, "finance")
    assert "market.demand.transit_adjustment.peak_window" in missing_for_step(cfg, "demand")
    assert missing_for_step(cfg, "setup") == []


def test_shared_defaults_keep_decide_null(fixture_cfg) -> None:  # type: ignore[no-untyped-def]
    # criteria C04 weights are DECIDE in the shared config — never defaulted in code
    assert missing_for_step(fixture_cfg, "criteria") == ["criteria.c04_daypart_weights"]


def test_verify_items_and_parameter_report(fixture_cfg) -> None:  # type: ignore[no-untyped-def]
    items = dict(verify_items(fixture_cfg))
    assert "rates.office" in items
    assert "finance.construction_cost_per_stall_usd" in items
    assert "sources.S00" not in items  # custom boundary: TIGER unused
    rows = parameter_report(fixture_cfg)
    assert not [r for r in rows if r["status"] == "UNTAGGED"]


def test_untagged_numeric_is_reported(variant) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config(variant({"provenance.site.max_slope_pct": ...}))
    untagged = {r["parameter"] for r in parameter_report(cfg) if r["status"] == "UNTAGGED"}
    assert "max_slope_pct" in untagged


def test_franklin_template_validates() -> None:
    p = Path(__file__).parents[1] / "markets" / "franklin_oh.yaml"
    if not p.exists():
        pytest.skip("franklin_oh.yaml not present")
    cfg = load_config(p)
    assert cfg.crs.to_epsg() == 3735 and cfg.market.market.units == "ft"


def test_fixture_dir_labelled_synthetic() -> None:
    text = FIXTURE_YAML.read_text(encoding="utf-8")
    assert "SYNTHETIC — NOT REAL DATA" in text
    assert (FIXTURE_DIR / "README.md").exists()


def test_market_sets_c04_weights(variant) -> None:  # type: ignore[no-untyped-def]
    w = {"wd_day": 0.4, "wd_eve": 0.3, "we_day": 0.15, "we_eve": 0.15, "event": 0.0}
    cfg = load_config(variant({"c04_daypart_weights": w}))
    assert cfg.criteria.c04_daypart_weights == w
    assert missing_for_step(cfg, "criteria") == []
    with pytest.raises(ConfigError, match="c04_daypart_weights sum"):
        load_config(variant({"c04_daypart_weights": {**w, "wd_day": 0.5}}))
