"""S09 — GTFS schedule → TransitStops with peak departures and headway (manual §6.3).

For the ``options.service_date`` (YYYYMMDD, a representative weekday you choose), active services
are resolved from ``calendar.txt`` + ``calendar_dates.txt`` exceptions. Departures per stop are
counted within ``demand.transit_adjustment.peak_window`` [start, end); headway =
window minutes ÷ departures. ``high_frequency_flag`` = headway ≤
``high_frequency_headway_max_min``. Any of those settings null → the dependent fields are null
and a note is logged (the demand step requires them).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.base import IngestError, SourceAdapter, Standardized, points_from_xy, to_analysis

if TYPE_CHECKING:
    from parkiq.runner import RunContext

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _read(z: zipfile.ZipFile, name: str, required: bool = True) -> pd.DataFrame | None:
    names = {n.split("/")[-1]: n for n in z.namelist()}
    if name not in names:
        if required:
            raise IngestError(f"GTFS feed has no {name}")
        return None
    return pd.read_csv(io.BytesIO(z.read(names[name])), dtype=str)


def to_minutes(hhmmss: str) -> float:
    """GTFS time (may exceed 24:00:00) → minutes after midnight."""
    h, m, *s = str(hhmmss).strip().split(":")
    return int(h) * 60 + int(m) + (int(s[0]) / 60 if s else 0)


def active_services(cal: pd.DataFrame | None, dates: pd.DataFrame | None, day: str) -> set[str]:
    """Service IDs running on ``day`` (YYYYMMDD) per calendar + calendar_dates exceptions."""
    d = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    wd = WEEKDAYS[d.weekday()]
    out: set[str] = set()
    if cal is not None and len(cal):
        c = cal[(cal["start_date"] <= day) & (cal["end_date"] >= day) & (cal[wd] == "1")]
        out |= set(c["service_id"])
    if dates is not None and len(dates):
        dd = dates[dates["date"] == day]
        out |= set(dd[dd["exception_type"] == "1"]["service_id"])
        out -= set(dd[dd["exception_type"] == "2"]["service_id"])
    return out


class GtfsAdapter(SourceAdapter):
    """GTFS → TransitStops."""

    source_id = "S09"
    downstream_effect = "no transit adjustment (demand factor near high-frequency stops)"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        path = raw if not isinstance(raw, list) else raw[0]
        ta = ctx.cfg.market.demand.transit_adjustment
        day = self.entry.options.get("service_date")
        notes: list[str] = []
        with zipfile.ZipFile(path) as z:
            stops = _read(z, "stops.txt")
            trips = _read(z, "trips.txt")
            st = _read(z, "stop_times.txt")
            cal = _read(z, "calendar.txt", required=False)
            cdates = _read(z, "calendar_dates.txt", required=False)
        assert stops is not None and trips is not None and st is not None
        if "location_type" in stops.columns:
            stops = stops[stops["location_type"].fillna("0").isin(["0", ""])]
        st = st.merge(trips[["trip_id", "route_id", "service_id"]], on="trip_id", how="left")
        routes = st.groupby("stop_id")["route_id"].nunique().rename("route_count")
        deps = pd.Series(dtype="float64", name="peak_departures")
        if day and ta.peak_window:
            svc = active_services(cal, cdates, str(day))
            lo, hi = (to_minutes(t + ":00") for t in ta.peak_window)
            t = st[st["service_id"].isin(svc)].copy()
            t["dep_min"] = t["departure_time"].fillna(t["arrival_time"]).map(to_minutes)
            t = t[(t["dep_min"] >= lo) & (t["dep_min"] < hi)]
            deps = t.groupby("stop_id").size().rename("peak_departures")
            window = hi - lo
            notes.append(f"service_date {day}: {len(svc)} services; window {ta.peak_window}")
        else:
            window = None
            notes.append(
                "peak_departures/headway not computed: set sources.S09.options."
                "service_date and demand.transit_adjustment.peak_window"
            )
        s = stops.merge(routes, left_on="stop_id", right_index=True, how="left")
        s = s.merge(deps, left_on="stop_id", right_index=True, how="left")
        if window is not None:
            s["peak_departures"] = s["peak_departures"].fillna(0)
            s["peak_headway_min"] = window / s["peak_departures"].where(s["peak_departures"] > 0)
        else:
            s["peak_headway_min"] = None
        thr = ta.high_frequency_headway_max_min
        if thr is not None and window is not None:
            s["high_frequency_flag"] = s["peak_headway_min"].le(thr)
        else:
            s["high_frequency_flag"] = None
            if thr is None:
                notes.append("high_frequency_flag null: high_frequency_headway_max_min is DECIDE")
        pts = points_from_xy(s, "stop_lon", "stop_lat")
        a, native, transf = to_analysis(pts, ctx)
        out = (
            gpd.GeoDataFrame(
                {
                    "stop_id": a["stop_id"].astype(str),
                    "stop_name": a.get("stop_name"),
                    "route_count": a["route_count"].fillna(0).astype(int),
                    "peak_departures": a.get("peak_departures"),
                    "peak_headway_min": a["peak_headway_min"],
                    "high_frequency_flag": a["high_frequency_flag"],
                },
                geometry=a.geometry,
                crs=a.crs,
            )
            .sort_values("stop_id")
            .reset_index(drop=True)
        )
        return Standardized("Raw_GTFS_Stops", pts, {"TransitStops": out}, native, transf, notes)
