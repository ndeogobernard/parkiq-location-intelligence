"""M8 validation on SYNTHETIC observed counts (tests only, not field data)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from parkiq.validate import (
    ObservedDataError,
    calibration_factors,
    compare,
    load_observed,
    metrics,
    write_calibration,
)


def _obs(tmp: Path, rows: list[tuple[int, str, int, int]]) -> Path:
    p = tmp / "obs.csv"
    pd.DataFrame(
        [{"lot_no": n, "date": "2026-10-06", "time_of_week": tw, "start_time": "11:00",
          "occupied": o, "total_marked": t} for n, tw, o, t in rows]
    ).to_csv(p, index=False)  # fmt: skip
    return p


def test_load_normalizes_labels_and_rejects_bad_rows(tmp_path: Path) -> None:
    df = load_observed(_obs(tmp_path, [(1, "Weekday day", 50, 100), (2, "wd_eve", 10, 40)]))
    assert list(df["daypart"]) == ["wd_day", "wd_eve"]
    assert df["observed_occ"].tolist() == [0.5, 0.25]
    with pytest.raises(ObservedDataError, match="impossible"):
        load_observed(_obs(tmp_path, [(1, "wd_day", 120, 100)]))
    with pytest.raises(ObservedDataError, match="unknown time_of_week"):
        load_observed(_obs(tmp_path, [(1, "lunchtime", 1, 10)]))


def test_metrics_and_calibration_recover_a_known_bias(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    true = rng.uniform(0.3, 0.9, 8)
    rows = [(i + 1, "wd_day", round(v * 200), 200) for i, v in enumerate(true)]
    obs = load_observed(_obs(tmp_path, rows))
    model = pd.DataFrame(
        {"lot_no": range(1, 9), "daypart": "wd_day", "model_ratio": obs["observed_occ"] / 0.8}
    )
    t = compare(obs, model)  # model over-predicts by 25 %
    m = metrics(t)
    assert m["wd_day"]["bias"] > 0 and m["wd_day"]["rank_correlation"] == pytest.approx(1.0)
    f = calibration_factors(t)
    assert f["wd_day"] == pytest.approx(0.8, abs=0.01)
    assert f["wd_eve"] is None  # fewer than 5 lots
    out = tmp_path / "franklin_oh.calibration.yaml"
    write_calibration(out, f, "RUN", 8)
    text = out.read_text(encoding="utf-8")
    assert "wd_day: 0.8" in text and "wd_eve" not in text
