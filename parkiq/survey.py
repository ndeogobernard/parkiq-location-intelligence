"""Field rate survey support (ADR-0023, ADR-0054): sample selection, template, field sheet, map.

The off-street rate surface is built from survey observations only. Round 1 records posted rates
for every daypart at a stratified sample of paid facilities, observed from the public
right-of-way (signs, the payment app's rate screen) or read from the operator's website.

``select_sample`` ranks the facilities in each stratum — known paid (``fee_flag``) first, then a
named operator, then capacity — and picks greedily with a minimum spacing, garages first up to
the stratum's garage quota; the next picks become backups. Deterministic (ties by facility_id).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from parkiq import units

TEMPLATE_COLUMNS = [
    "facility_id", "osm_ids", "parcel_id", "name", "operator", "type", "lat", "lon", "area",
    "visit_date", "visit_time", "observer", "source",  # sign | app rate screen | operator website
    "rate_hour", "rate_daily", "rate_early_bird", "early_bird_rule", "rate_evening_flat",
    "evening_starts", "rate_weekend_daily", "rate_event", "rate_monthly", "max_stay",
    "hours_posted", "payment_app", "app_zone", "capacity_counted", "photo_ref", "notes",
]  # fmt: skip
SOURCE_VALUES = ["sign", "app rate screen", "operator website"]


def _score(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["_paid"] = f["fee_flag"].fillna(False).astype(bool).astype(int)
    f["_op"] = f["operator"].notna().astype(int)
    f["_cap"] = (
        pd.to_numeric(f["capacity_stated"], errors="coerce")
        .fillna(pd.to_numeric(f["capacity_est"], errors="coerce"))
        .fillna(0)
    )
    return f.sort_values(["_paid", "_op", "_cap", "facility_id"],
                         ascending=[False, False, False, True])  # fmt: skip


def _why(r: pd.Series) -> str:
    bits = []
    if r["_paid"]:
        bits.append("tagged paid (fee=yes)")
    else:
        bits.append("UNVERIFIED as paid (no fee tag)")
    if r["_op"]:
        bits.append(f"operator {r['operator']}")
    bits.append(f"{int(r['_cap'])} stalls ({r['capacity_source'] or 'unknown'})")
    return "; ".join(bits)


def select_sample(
    fac: gpd.GeoDataFrame,
    strata: list[dict[str, Any]],
    spacing_m: float,
    backups: int,
    exclude: list[dict[str, str]] | None = None,
) -> pd.DataFrame:
    """Round sample + backups per stratum (see module docstring).

    ``exclude`` rules ({field, pattern, reason}) remove facilities from every pool. A stratum's
    ``manual`` entries ({facility_id, operator, source, why}) are added to its sample first, even
    outside its areas; they count toward ``n``.
    """
    crs = fac.crs
    gap = units.m_to_crs(spacing_m, crs)
    rows: list[dict[str, Any]] = []
    keep = pd.Series(True, index=fac.index)
    for rule in exclude or []:
        col = fac[rule["field"]]
        keep &= ~(col.notna() & col.astype(str).str.contains(rule["pattern"], case=False))
    fac = fac[keep]
    for s in strata:
        pool = _score(fac[fac["submarket"].isin(s["areas"]) & (fac["type"] != "OnStreet")])
        picked: list[Any] = []
        chosen: list[Any] = []
        manual = {m["facility_id"]: m for m in s.get("manual", [])}
        if manual:
            extra = _score(fac[fac["facility_id"].isin(list(manual))])
            pool = pd.concat([extra, pool[~pool.index.isin(extra.index)]])
            for i, r in extra.iterrows():
                chosen.append(i)
                picked.append(r.geometry)

        def take(
            cands: pd.DataFrame, limit: int, chosen: list[Any] = chosen, picked: list[Any] = picked
        ) -> None:
            for i, r in cands.iterrows():
                if len(chosen) >= limit:
                    return
                if i in chosen or any(r.geometry.distance(t) < gap for t in picked):
                    continue
                chosen.append(i)
                picked.append(r.geometry)

        take(pool[pool["type"] == "Garage"], s.get("garages", 0))  # garage quota first
        take(pool[pool["type"] != "Garage"], s["n"])  # then the rest of the sample
        take(pool, s["n"] + backups)  # backups: next best of any type
        for k, i in enumerate(chosen):
            r = pool.loc[i]
            m = manual.get(r["facility_id"])
            ll = gpd.GeoSeries([r.geometry], crs=crs).to_crs(4326).iloc[0]
            rows.append({
                "role": "sample" if k < s["n"] else "backup",
                "rank": k + 1 if k < s["n"] else k + 1 - s["n"],
                "stratum": s["label"], "area": r["submarket"], "facility_id": r["facility_id"],
                "name": r["name"], "operator": m["operator"] if m else r["operator"],
                "type": r["type"], "lat": round(ll.y, 6), "lon": round(ll.x, 6),
                "why_selected": f"MANUAL: {m['why']}" if m else _why(r),
                "source_expected": m["source"] if m else "sign / app rate screen",
                "osm_ids": r["source_ids"],
            })  # fmt: skip
    return pd.DataFrame(rows)


def load_strata(path: Path) -> dict[str, Any]:
    """Read the survey strata YAML."""
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def write_template(path: Path) -> None:
    """Blank CSV with the survey columns."""
    pd.DataFrame(columns=TEMPLATE_COLUMNS).to_csv(path, index=False)


def field_sheet_pdf(path: Path, market: str, round_no: int) -> None:
    """One printable page: instructions + one facility block to fill by hand."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8.5, 11))
    ax = fig.add_axes((0.06, 0.04, 0.88, 0.92))
    ax.axis("off")
    y = 1.0

    def line(txt: str, size: float = 9, bold: bool = False, dy: float = 0.024) -> None:
        nonlocal y
        ax.text(0, y, txt, fontsize=size, fontweight="bold" if bold else "normal", va="top",
                transform=ax.transAxes)  # fmt: skip
        y -= dy

    line(f"ParkIQ field rate survey — {market} — round {round_no}", 13, True, 0.034)
    line("Record POSTED rates for every period. Public right-of-way only: do not enter gated or")
    line("private areas, do not pay, do not photograph people or plates. One sheet per facility.")
    line("source = sign | app rate screen | operator website (write which one for each value).",
         dy=0.034)  # fmt: skip
    fields = [
        ("Facility ID / name", "Operator"), ("Type (surface / garage)", "Area"),
        ("Date", "Time"), ("Observer", "Source (sign / app / website)"),
        ("Hourly rate", "Max stay"), ("Daily (all day)", "Early bird rate + rule"),
        ("Evening flat rate", "Evening starts at"), ("Weekend daily", "Event rate"),
        ("Monthly", "Hours posted"), ("Payment app", "App zone #"),
        ("Stalls counted (approx.)", "Photo ref (sign only)"),
    ]  # fmt: skip
    for a, b in fields:
        for x0, lab in ((0.0, a), (0.52, b)):
            ax.text(x0, y, lab, fontsize=8.5, va="top", transform=ax.transAxes)
            ax.plot([x0, x0 + 0.46], [y - 0.034, y - 0.034], color="black", lw=0.6,
                    transform=ax.transAxes)  # fmt: skip
        y -= 0.052
    ax.text(0, y, "Notes (rates by vehicle size, validation, signage conflicts):", fontsize=8.5,
            va="top", transform=ax.transAxes)  # fmt: skip
    for k in range(4):
        yy = y - 0.04 - k * 0.035
        ax.plot([0, 0.98], [yy, yy], color="black", lw=0.6, transform=ax.transAxes)
    note = "Enter results in round1_observations.csv (same columns as survey_template.csv)."
    ax.text(0, 0.0, note, fontsize=7.5, color="#555555", transform=ax.transAxes)
    fig.savefig(path)
    plt.close(fig)


def sample_map_pdf(
    path: Path,
    sample: pd.DataFrame,
    subs: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame | None,
    title: str,
) -> None:
    """Navigation map: survey areas, sample (numbered) and backups; OSM credit."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = gpd.GeoDataFrame(sample, geometry=gpd.points_from_xy(sample.lon, sample.lat), crs=4326)
    s = s.to_crs(subs.crs)
    fig, ax = plt.subplots(figsize=(11, 8.5))
    subs.boundary.plot(ax=ax, color="#555555", lw=0.8)
    for _, r in subs.iterrows():
        c = r.geometry.representative_point()
        ax.text(c.x, c.y, r["name"], fontsize=7, color="#555555", ha="center")
    if roads is not None and len(roads):
        roads.plot(ax=ax, color="#cccccc", lw=0.4, zorder=0)
    b = s[s.role == "backup"]
    ax.scatter(b.geometry.x, b.geometry.y, s=12, facecolor="white", edgecolor="#1f78b4", lw=0.8,
               zorder=3, label="backup")  # fmt: skip
    m = s[s.role == "sample"].reset_index(drop=True)
    colors = np.where(m["type"] == "Garage", "#e31a1c", "#1f78b4")
    ax.scatter(m.geometry.x, m.geometry.y, s=30, c=colors, zorder=4)
    for k, r in m.iterrows():
        ax.annotate(str(k + 1), (r.geometry.x, r.geometry.y), xytext=(3, 3),
                    textcoords="offset points", fontsize=7, zorder=5)  # fmt: skip
    ax.scatter([], [], c="#1f78b4", s=30, label="sample: surface")
    ax.scatter([], [], c="#e31a1c", s=30, label="sample: garage")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title(title, fontsize=11)
    ax.set_axis_off()
    ax.text(0.0, -0.02, "Parking facilities, streets: © OpenStreetMap contributors (ODbL); areas: "
            "City of Columbus open data; Zone A/B derived from City Code Map 2 [VERIFY].",
            fontsize=7, transform=ax.transAxes)  # fmt: skip
    fig.savefig(path)
    plt.close(fig)
