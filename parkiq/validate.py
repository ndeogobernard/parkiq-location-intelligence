"""M8 validation: observed lot occupancy vs the model, error metrics, calibration factors.

Observed counts (round-2 field survey) are compared with the model at each lot's hexagon:
the model's demand ÷ effective supply (``gap_ratio``) is the predicted occupancy of the parking
within a short walk, capped at ``OCC_CAP``. Per time of week the report gives mean absolute
error, bias, RMSE, the share of lots within ±15 points and the rank correlation; the calibration
factor is the median of observed ÷ predicted, which multiplies modeled demand for that time of
week. Factors go to ``markets/<slug>.calibration.yaml`` only when asked (ADR-0043), and the
uncalibrated results are always reported alongside.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from parkiq.config import DAYPARTS

OCC_CAP = 1.2  # predicted occupancy above this is "overflowing"; not a parameter
WITHIN = 0.15  # "close" = within 15 occupancy points
LABELS = {
    "weekday day": "wd_day",
    "weekday evening": "wd_eve",
    "weekend day": "we_day",
    "weekend evening": "we_eve",
    "event": "event",
    "event night": "event",
    "event day": "event",
}
REQUIRED = ("lot_no", "date", "time_of_week", "occupied", "total_marked")


class ObservedDataError(ValueError):
    """The observed-counts file is not usable."""


def load_observed(path: Path, sample: pd.DataFrame | None = None) -> pd.DataFrame:
    """Read ``round2_observations.csv``; normalize the time of week; attach lot ids.

    Columns: lot_no, date, time_of_week (daypart code or plain label), start_time, occupied,
    total_marked, posted_rate, full_flag, notes. Rows with occupied > total_marked are errors.
    """
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ObservedDataError(f"{path.name}: missing columns {missing}")
    tw = df["time_of_week"].astype(str).str.strip().str.lower()
    df["daypart"] = tw.map(lambda v: v if v in DAYPARTS else LABELS.get(v))
    bad = df[df["daypart"].isna()]
    if len(bad):
        raise ObservedDataError(
            f"{path.name}: unknown time_of_week {sorted(set(bad['time_of_week']))}"
        )
    for c in ("occupied", "total_marked"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df[
        (df["occupied"] < 0) | (df["total_marked"] <= 0) | (df["occupied"] > df["total_marked"])
    ]
    if len(bad):
        raise ObservedDataError(
            f"{path.name}: {len(bad)} rows with impossible counts (lot_no {sorted(bad['lot_no'])})"
        )
    df["observed_occ"] = df["occupied"] / df["total_marked"]
    if sample is not None:
        df = df.merge(sample[["lot_no", "facility_id"]], on="lot_no", how="left")
    return df


def compare(observed: pd.DataFrame, model: pd.DataFrame) -> pd.DataFrame:
    """Lot × time-of-week table: mean observed occupancy and the model's predicted occupancy.

    ``model`` has columns lot_no, daypart, model_ratio (demand ÷ effective supply at the lot's hex).
    """
    obs = observed.groupby(["lot_no", "daypart"], as_index=False).agg(
        observed_occ=("observed_occ", "mean"), counts=("observed_occ", "size")
    )
    t = obs.merge(model, on=["lot_no", "daypart"], how="left")
    t["predicted_occ"] = t["model_ratio"].clip(lower=0, upper=OCC_CAP)
    t["error"] = t["predicted_occ"] - t["observed_occ"]
    return t


def metrics(t: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Error metrics per time of week (and overall)."""
    out: dict[str, dict[str, Any]] = {}
    groups = [("all", t), *((dp, g) for dp, g in t.groupby("daypart"))]
    for key, g in groups:
        g = g.dropna(subset=["predicted_occ", "observed_occ"])
        if not len(g):
            continue
        e = g["error"].to_numpy(dtype=float)
        rho = (
            float(g["predicted_occ"].rank().corr(g["observed_occ"].rank()))
            if len(g) >= 3 and g["predicted_occ"].nunique() > 1 and g["observed_occ"].nunique() > 1
            else None
        )
        out[str(key)] = {
            "lots": int(g["lot_no"].nunique()),
            "mae": round(float(np.mean(np.abs(e))), 4),
            "bias": round(float(np.mean(e)), 4),
            "rmse": round(float(np.sqrt(np.mean(e**2))), 4),
            "within_15_points": round(float(np.mean(np.abs(e) <= WITHIN)), 4),
            "rank_correlation": None if rho is None else round(rho, 4),
        }
    return out


def calibration_factors(t: pd.DataFrame, min_lots: int = 5) -> dict[str, float | None]:
    """Median observed ÷ predicted per time of week; None with fewer than ``min_lots`` lots."""
    out: dict[str, float | None] = {}
    for dp in DAYPARTS:
        g = t[(t["daypart"] == dp) & (t["predicted_occ"] > 0)].dropna(subset=["observed_occ"])
        out[dp] = (
            round(float((g["observed_occ"] / g["predicted_occ"]).median()), 4)
            if g["lot_no"].nunique() >= min_lots
            else None
        )
    return out


def write_calibration(
    path: Path, factors: dict[str, float | None], run_id: str, n_lots: int
) -> None:
    """Per-market calibration file (ADR-0043): demand multipliers by time of week."""
    import yaml

    doc = {
        "calibration": {"demand_factor": {k: v for k, v in factors.items() if v is not None}},
        "provenance": {
            "calibration.demand_factor": {
                "status": "SET",
                "source": f"parkiq validate, run {run_id}: median observed / predicted "
                f"occupancy at {n_lots} surveyed lots",
            }
        },
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def model_at_lots(gpkg: Path, sample: pd.DataFrame) -> pd.DataFrame:
    """Model demand ÷ effective supply at each sampled lot's hexagon, per time of week."""
    import geopandas as gpd
    import pyogrio

    fac = pyogrio.read_dataframe(gpkg, layer="SupplyFacilities", columns=["facility_id"])
    fac = fac[fac["facility_id"].isin(sample["facility_id"])]
    hexes = pyogrio.read_dataframe(gpkg, layer="HexGrid", columns=["hex_id"])
    pt = fac.assign(geometry=fac.geometry.representative_point())
    j = gpd.sjoin(pt, hexes, predicate="within", how="left")[["facility_id", "hex_id"]]
    gap = pyogrio.read_dataframe(gpkg, layer="Hex_Gap_Daypart", read_geometry=False)
    m = sample[["lot_no", "facility_id"]].merge(j, on="facility_id", how="left")
    m = m.merge(gap[["hex_id", "daypart", "gap_ratio"]], on="hex_id", how="left")
    return m.rename(columns={"gap_ratio": "model_ratio"})[["lot_no", "daypart", "model_ratio"]]


def run(gpkg: Path, observed_csv: Path, sample_csv: Path, out_dir: Path) -> dict[str, Any]:
    """Load, compare, measure; write validation_report.json and validation_lots.csv."""
    sample = pd.read_csv(sample_csv)
    obs = load_observed(observed_csv, sample)
    t = compare(obs, model_at_lots(gpkg, sample))
    rep = {
        "observations": len(obs),
        "lots": int(obs["lot_no"].nunique()),
        "metrics_uncalibrated": metrics(t),
        "calibration_factors": calibration_factors(t),
    }
    t.to_csv(out_dir / "validation_lots.csv", index=False)
    (out_dir / "validation_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
