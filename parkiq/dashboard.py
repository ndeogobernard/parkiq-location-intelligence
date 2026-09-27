"""Offline dashboard: one self-contained Plotly HTML file per run (SCOPE §7; M7 early build).

* **Public** version: parking shortage by hex for each time of week (selector), paid-market hot
  zones, the hot-zone list, demand by source and shortfall by zone. Aggregated results only: no
  parcel ids, owner names or candidate parcels.
* **Private** version adds the ranked candidate sites with a scenario selector, the top-20 table
  and the criteria breakdown of the top 10.

The map is a projected SVG map without web tiles, and plotly.js is embedded, so the file makes no
network requests and opens anywhere. The public web app is an ArcGIS Experience Builder app built
from the hosted layers (docs/webapp); this file is its offline companion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pyogrio

DAYPART_LABEL = {
    "wd_day": "Weekday day",
    "wd_eve": "Weekday evening",
    "we_day": "Weekend day",
    "we_eve": "Weekend evening",
    "event": "Event",
}
CRIT_LABEL = {
    "C01": "Weekday-day shortage",
    "C02": "Evening/weekend shortage",
    "C03": "Event shortage",
    "C04": "Achievable rate",
    "C05": "Competing supply",
    "C06": "Walk to anchors",
    "C07": "Land cost per stall",
    "C08": "Access",
    "C09": "Zoning certainty",
    "C10": "Pipeline risk",
}


def _wgs(g: gpd.GeoDataFrame, tol_m: float = 5.0) -> gpd.GeoDataFrame:
    out = g.copy()
    out["geometry"] = out.geometry.simplify(tol_m * 3.28084)
    return out.to_crs(4326)


def _geojson(g: gpd.GeoDataFrame, key: str) -> dict[str, Any]:
    gj = json.loads(g[[key, "geometry"]].to_json(drop_id=True))
    for f in gj["features"]:
        for ring_set in _rings(f["geometry"]):
            for pt in ring_set:
                pt[0], pt[1] = round(pt[0], 5), round(pt[1], 5)
    return dict(gj)


def _rings(geom: dict[str, Any]) -> list[list[list[float]]]:
    if geom["type"] == "Polygon":
        return list(geom["coordinates"])
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def load(gpkg: Path) -> dict[str, Any]:
    """Everything the dashboard shows, from the run GeoPackage."""
    hexes = pyogrio.read_dataframe(gpkg, layer="HexGrid", columns=["hex_id"])
    gap = pyogrio.read_dataframe(gpkg, layer="Hex_Gap_Daypart", read_geometry=False)
    dem = pyogrio.read_dataframe(gpkg, layer="Hex_Demand_Daypart", read_geometry=False)
    wide = gap.pivot_table(index="hex_id", columns="daypart", values="gap_stalls", aggfunc="sum")
    dwide = dem.pivot_table(
        index="hex_id", columns="daypart", values="demand_stalls", aggfunc="sum"
    )
    keep = dwide.index[(dwide.fillna(0) > 1).any(axis=1)]  # hexes with any modeled demand
    h = hexes[hexes["hex_id"].isin(keep)].merge(
        wide, left_on="hex_id", right_index=True, how="left"
    )
    hz = pyogrio.read_dataframe(gpkg, layer="HotZones")
    anchors = pyogrio.read_dataframe(gpkg, layer="DemandAnchors", read_geometry=False)
    subs = pyogrio.read_dataframe(gpkg, layer="Submarkets")
    subs["geometry"] = subs.geometry.make_valid()
    return {"hexes": h, "zones": hz, "anchors": anchors, "submarkets": subs}


def _map_figure(d: dict[str, Any], cand: gpd.GeoDataFrame | None) -> go.Figure:
    h = _wgs(d["hexes"])
    gj = _geojson(h, "hex_id")
    fig = go.Figure()
    zmax = 500
    zs = {dp: h[dp].fillna(0).clip(-zmax, zmax).round(0).tolist() for dp in DAYPART_LABEL}
    raw = {dp: h[dp].fillna(0).round(0).tolist() for dp in DAYPART_LABEL}
    first = next(iter(DAYPART_LABEL))
    fig.add_trace(
        go.Choropleth(
            geojson=gj,
            featureidkey="properties.hex_id",
            locations=h["hex_id"],
            z=zs[first],
            zmin=-zmax,
            zmax=zmax,
            colorscale="RdBu_r",
            marker_line_width=0,
            colorbar={"title": "Stalls short (+)<br>or spare (-)", "len": 0.6},
            customdata=raw[first],
            hovertemplate="%{customdata:,} stalls<extra></extra>",
            name="Shortage",
        )
    )
    zones = _wgs(d["zones"][d["zones"]["zone_class"].astype(str).str.startswith("paid")])
    for _, z in zones.iterrows():
        for ring in _rings(
            json.loads(gpd.GeoSeries([z.geometry]).to_json())["features"][0]["geometry"]
        ):
            xs, ys = zip(*ring, strict=True)
            fig.add_trace(
                go.Scattergeo(
                    lon=xs,
                    lat=ys,
                    mode="lines",
                    line={"color": "black", "width": 2},
                    hoverinfo="text",
                    text=f"Hot zone: {z.total_gap_stalls:,.0f} stalls short (weekday day)",
                    showlegend=False,
                )
            )
    if cand is not None and len(cand):
        c = cand.to_crs(4326)
        pt = c.geometry.representative_point()
        fig.add_trace(
            go.Scattergeo(
                lon=pt.x,
                lat=pt.y,
                mode="markers+text",
                text=c["rank"].astype(int).astype(str),
                textposition="top center",
                textfont={"size": 9},
                marker={
                    "size": 9,
                    "color": c["composite"],
                    "colorscale": "Blues",
                    "line": {"width": 1, "color": "#222"},
                },
                hovertext=c["label"],
                hoverinfo="text",
                name="Candidate sites",
            )
        )
    buttons = [
        {"label": lab, "method": "restyle", "args": [{"z": [zs[dp]], "customdata": [raw[dp]]}, [0]]}
        for dp, lab in DAYPART_LABEL.items()
    ]
    fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
    fig.update_layout(
        height=640,
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        updatemenus=[
            {"buttons": buttons, "x": 0.01, "y": 0.99, "xanchor": "left", "yanchor": "top"}
        ],
        title={"text": "Parking shortage by time of week", "x": 0.5},
    )
    return fig


def _charts(d: dict[str, Any]) -> tuple[go.Figure, go.Figure, pd.DataFrame]:
    a = d["anchors"]
    rows = []
    for dp, lab in DAYPART_LABEL.items():
        g = a.groupby("category")[f"demand_{dp}"].sum()
        rows += [{"time": lab, "source": k, "stalls": v} for k, v in g.items() if v > 0]
    t = pd.DataFrame(rows)
    f1 = go.Figure()
    for src, g in t.groupby("source"):
        f1.add_trace(go.Bar(x=g["time"], y=g["stalls"], name=str(src)))
    f1.update_layout(
        barmode="stack", title="Parking demand by source (stalls, Franklin County)", height=380
    )
    zones = d["zones"]
    pz = zones[zones["zone_class"].astype(str).str.startswith("paid")].copy()
    pz = pz.sort_values("total_gap_stalls", ascending=False)
    pz["label"] = zone_labels(pz, d)
    f2 = go.Figure(go.Bar(x=pz["label"], y=pz["total_gap_stalls"].round(0), marker_color="#b2182b"))
    f2.update_layout(title="Weekday-day shortfall by paid-market hot zone (stalls)", height=380)
    table = pd.DataFrame(
        {
            "Hot zone": pz["label"],
            "Hexes": pz["zone_size"],
            "Weekday-day shortfall (stalls)": pz["total_gap_stalls"].round(0).astype(int),
            "Short in": pz["dayparts_positive"].map(
                lambda v: ", ".join(
                    DAYPART_LABEL[x] for x in str(v).split(";") if x in DAYPART_LABEL
                )
            ),
            "Place": pz["jurisdictions"],
        }
    )
    return f1, f2, table


def zone_labels(pz: gpd.GeoDataFrame, d: dict[str, Any]) -> list[str]:
    """Plain place names for hot zones: campus anchor, else submarket, else jurisdiction."""
    anchors = d["anchors"].set_index("anchor_id")
    subs = d.get("submarkets")
    out = []
    for _, z in pz.iterrows():
        a = anchors.loc[z.top_anchor_id] if z.top_anchor_id in anchors.index else None
        name = None
        if a is not None and a["category"] in ("University", "Medical") and z.single_anchor_flag:
            name = f"Near {a['name']}"
        if name is None and subs is not None:
            hit = subs[subs.intersects(z.geometry.representative_point())]
            if len(hit):
                name = str(hit["name"].iloc[0])
        if name is None:
            name = str(z.jurisdictions).replace(";", ", ")
        out.append(name)
    seen: dict[str, int] = {}
    uniq = []
    for n in out:
        seen[n] = seen.get(n, 0) + 1
        uniq.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return uniq


def _html_table(df: pd.DataFrame) -> str:
    return str(df.to_html(index=False, border=0, classes="t", float_format=lambda v: f"{v:,.2f}"))


def build(gpkg: Path, out: Path, public: bool = True, analysis_date: str = "") -> Path:
    """Write the dashboard HTML (public: zones and aggregates only)."""
    d = load(gpkg)
    cand = None
    extra = ""
    if not public:
        sc = pyogrio.read_dataframe(gpkg, layer="SiteScores")
        cp = pyogrio.read_dataframe(
            gpkg,
            layer="CandidateParcels",
            read_geometry=False,
            columns=["parcel_id", "address", "stalls", "owner_feasibility", "existing_only_flag"],
        )
        sc = sc.merge(cp, on="parcel_id", how="left")
        figs = []
        for scen, g in sc.groupby("scenario"):
            g = g.sort_values("rank")
            g["label"] = (
                g["rank"].astype(int).astype(str)
                + ". "
                + g["address"].fillna("")
                + " ("
                + g["stalls"].fillna(0).astype(int).astype(str)
                + " stalls)"
            )
            cand = g if scen == "Balanced" else cand
            top = g.head(10)
            f = go.Figure()
            for x, lab in CRIT_LABEL.items():
                w = top[f"{x.lower()}_s"]
                f.add_trace(go.Bar(y=top["label"], x=w, name=lab, orientation="h"))
            f.update_layout(
                barmode="stack",
                title=f"Criteria scores of the top 10, {scen}",
                height=460,
                yaxis={"autorange": "reversed"},
            )
            figs.append(
                (
                    scen,
                    f,
                    g.head(20)[["rank", "address", "stalls", "composite", "owner_feasibility"]],
                )
            )
        extra = "".join(
            f"<h2>{scen} scenario</h2>"
            + f.to_html(full_html=False, include_plotlyjs=False)
            + _html_table(
                t.rename(
                    columns={
                        "rank": "Rank",
                        "address": "Address",
                        "stalls": "Stalls",
                        "composite": "Score",
                        "owner_feasibility": "Owner feasibility",
                    }
                )
            )
            for scen, f, t in figs
        )
    m = _map_figure(d, cand)
    f1, f2, table = _charts(d)
    title = "ParkIQ: Columbus parking shortage" + ("" if public else " (private: candidate sites)")
    how = (
        "Use the menu on the map to change the time of week. Red hexes need more parking than is "
        "counted within a short walk; blue hexes have spare parking. Black outlines are hot zones "
        "where paid parking is nearby and the shortage lasts into the evening."
    )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:14px/1.45 "Segoe UI",Arial,sans-serif;margin:16px;color:#222;max-width:1200px}}
h1{{font-size:22px;margin:0}} .note{{color:#444}} table.t{{border-collapse:collapse;font-size:13px}}
table.t td,table.t th{{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left}}
.src{{font-size:11px;color:#666;margin-top:20px}}</style></head><body>
<h1>{title}</h1><p class="note">{how}</p>
{m.to_html(full_html=False, include_plotlyjs=True)}
<h2>Paid-market hot zones</h2>{_html_table(table)}
{f2.to_html(full_html=False, include_plotlyjs=False)}
{f1.to_html(full_html=False, include_plotlyjs=False)}
{extra}
<p class="src">Sources: LODES WAC (2023); CTPP tract of work (2017-2021); CMS hospitals (2026-Q2);
IPEDS (2024); OSM parking, places and streets (2026-09), © OpenStreetMap contributors; Overture
buildings (2026-09-23.1); Franklin County Auditor parcels (2026-09-23); City of Columbus curb
meters (2026-09). ParkIQ. Analysis as of {analysis_date}.</p></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


__all__ = ["build", "load", "np"]
