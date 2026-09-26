"""Shared map layout and the ParkIQ map standard (SCOPE §7, §10; ADR-0076).

Every map, portfolio image, report figure, M1–M15 map or review draft, is made with
:func:`new_map` and finished with :func:`finish`, which adds and then **checks** the required
elements. ``finish`` raises :class:`MapStandardError` (and writes nothing) if any is missing:

* title, and a subtitle saying what is shown (measure, time of week, area)
* a legend for every symbol and colour, with units
* a 1–2 sentence "how to read this map" note
* a scale bar and a north arrow
* data sources with vintages, and "© OpenStreetMap contributors" when OSM data is used
* "ParkIQ" and the map date
* on maps of results that can still change (demand, gap, hot zones, candidates, scores): a plain
  "Analysis as of <Month YYYY>" line in the sources area; data maps (supply, zoning, network)
  carry no status line. No map carries a "PRELIMINARY" label.
* a locator inset when the view is zoomed in below the market extent
* no parcel IDs or owner names on anything public (text scan)
* no em dash (U+2014) and no "PRELIMINARY" in any map text (project text rules)

A JSON sidecar next to each image records the elements present, for audit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Text

OSM_CREDIT = "© OpenStreetMap contributors"
EM = chr(0x2014)  # em dash (project text rules)
REQUIRED = (
    "title",
    "subtitle",
    "legend",
    "how_to_read",
    "scale_bar",
    "north_arrow",
    "sources",
    "brand_date",
    "status_line",
    "locator",
    "osm_credit",
    "public_clean",
    "text_rules",
)
PARCEL_ID = re.compile(r"\b\d{3}-\d{6}(-\d{2})?\b")  # Franklin Auditor parcel-id pattern


class MapStandardError(ValueError):
    """A map is missing a required element."""


@dataclass
class MapSpec:
    """What a map must say about itself."""

    title: str
    subtitle: str  # measure, time of week, area
    how_to_read: str  # 1–2 sentences
    sources: list[str]  # each "name (vintage)"
    uses_osm: bool
    result: bool = False  # True for results that can still change → "Analysis as of <Month YYYY>"
    public: bool = False
    map_date: str = field(default_factory=lambda: date.today().isoformat())
    market_extent: tuple[float, float, float, float] | None = None  # for the locator rule
    units: str = ""  # legend units (required when the legend shows a measure)


@dataclass
class _State:
    spec: MapSpec
    elements: dict[str, Any] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)


def new_map(spec: MapSpec, figsize: tuple[float, float] = (16, 10)) -> tuple[Figure, Axes]:
    """Figure with a map axes on the left 70 % and a margin for the legend/notes on the right."""
    fig = plt.figure(figsize=figsize, dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0.02, 0.10, 0.66, 0.76))
    ax.set_axis_off()
    fig._parkiq = _State(spec)  # type: ignore[attr-defined]
    return fig, ax


def _state(fig: Figure) -> _State:
    st = getattr(fig, "_parkiq", None)
    if st is None:
        raise MapStandardError("figure was not created with parkiq.maps.new_map")
    return st  # type: ignore[no-any-return]


def _text(fig: Figure, x: float, y: float, s: str, key: str | None = None, **kw: Any) -> Artist:
    st = _state(fig)
    st.texts.append(s)
    art = fig.text(x, y, s, **kw)
    if key:
        st.elements[key] = s
    return art


def scale_bar(ax: Axes, length_ft: float, label: str) -> None:
    """Scale bar (analysis CRS in feet) at the lower left of the map axes."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    bx, by = x0 + 0.03 * (x1 - x0), y0 + 0.04 * (y1 - y0)
    ax.plot([bx, bx + length_ft], [by, by], color="#222222", lw=3, solid_capstyle="butt")
    ax.text(bx + length_ft / 2, by + 0.015 * (y1 - y0), label, ha="center", fontsize=9)
    _state(ax.figure).elements["scale_bar"] = label  # type: ignore[arg-type]


def north_arrow(ax: Axes) -> None:
    """North arrow at the lower right of the map axes (projected CRS, north up)."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x, y = x1 - 0.04 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    ax.annotate(
        "N",
        xy=(x, y + 0.08 * (y1 - y0)),
        xytext=(x, y),
        ha="center",
        fontsize=11,
        fontweight="bold",
        arrowprops={"arrowstyle": "-|>", "color": "#222222", "lw": 1.5},
    )
    _state(ax.figure).elements["north_arrow"] = True  # type: ignore[arg-type]


def locator(fig: Figure, context: Any, view: tuple[float, float, float, float]) -> None:
    """Locator inset: market outline (GeoSeries/GeoDataFrame) with the view rectangle."""
    from matplotlib.patches import Rectangle

    ins = fig.add_axes((0.70, 0.10, 0.12, 0.16))
    context.boundary.plot(ax=ins, color="#555555", lw=0.6)
    x0, y0, x1, y1 = view
    ins.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#d62728", lw=1.2))
    ins.set_axis_off()
    ins.set_title("Locator", fontsize=8)
    _state(fig).elements["locator"] = True


def finish(
    fig: Figure,
    ax: Axes,
    legend_handles: list[Any],
    legend_title: str,
    out: Path,
    view: tuple[float, float, float, float] | None = None,
) -> Path:
    """Add title, subtitle, legend, note, sources, brand/date, stamp; check; save; sidecar."""
    st = _state(fig)
    sp = st.spec
    _text(fig, 0.02, 0.95, sp.title, "title", fontsize=20, fontweight="bold")
    _text(fig, 0.02, 0.905, sp.subtitle, "subtitle", fontsize=12, color="#333333")
    if legend_handles:
        title = f"{legend_title} ({sp.units})" if sp.units else legend_title
        fig.legend(
            handles=legend_handles,
            loc="upper left",
            bbox_to_anchor=(0.70, 0.86),
            frameon=False,
            fontsize=10,
            title=title,
            title_fontsize=10,
        )
        st.elements["legend"] = title
        st.texts.append(title)
    _text(
        fig,
        0.70,
        0.42,
        "How to read this map: " + sp.how_to_read,
        "how_to_read",
        fontsize=10,
        va="top",
        wrap=True,
        color="#222222",
    )
    src = "Sources: " + "; ".join(sp.sources)
    if sp.uses_osm and OSM_CREDIT not in src:
        src += f". {OSM_CREDIT}"
    if sp.result:
        d = date.fromisoformat(sp.map_date)
        status = f"Analysis as of {d.strftime('%B %Y')}"
        src += f". {status}"
        st.elements["status_line"] = status
    else:
        st.elements["status_line"] = "n/a (data map)"
    _text(fig, 0.02, 0.035, src, "sources", fontsize=7.5, color="#555555", wrap=True)
    if OSM_CREDIT in src:
        st.elements["osm_credit"] = True
    elif not sp.uses_osm:
        st.elements["osm_credit"] = "n/a"
    _text(
        fig,
        0.98,
        0.012,
        f"ParkIQ · map date {sp.map_date}",
        "brand_date",
        fontsize=8,
        ha="right",
        color="#555555",
    )
    # locator rule: zoomed below the market extent needs an inset
    if view is not None and sp.market_extent is not None:
        mx0, my0, mx1, my1 = sp.market_extent
        vx0, vy0, vx1, vy1 = view
        zoomed = (vx1 - vx0) * (vy1 - vy0) < 0.8 * (mx1 - mx0) * (my1 - my0)
        if not zoomed:
            st.elements.setdefault("locator", "n/a (full extent)")
    elif view is None:
        st.elements.setdefault("locator", "n/a (full extent)")
    # public: no parcel ids / owner field names in any text
    bad = [t for t in st.texts if PARCEL_ID.search(t) or re.search(r"(?i)\bowner\b", t)]
    st.elements["public_clean"] = not bad if sp.public else "n/a (not public)"
    legend_text = [t.get_text() for t in fig.findobj(Text) if isinstance(t, Text)]
    rule_bad = [t for t in st.texts + legend_text if EM in str(t) or "PRELIMINARY" in str(t)]
    st.elements["text_rules"] = not rule_bad
    check(fig)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        fig.savefig(out, dpi=100, pil_kwargs={"quality": 85})
    else:
        fig.savefig(out, dpi=100)
    out.with_suffix(out.suffix + ".json").write_text(
        json.dumps({"map": out.name, "elements": st.elements}, indent=1, default=str),
        encoding="utf-8",
    )
    plt.close(fig)
    return out


def check(fig: Figure) -> None:
    """Raise :class:`MapStandardError` listing every missing element."""
    st = _state(fig)
    missing = [k for k in REQUIRED if not st.elements.get(k)]
    if st.spec.public and st.elements.get("public_clean") is False:
        missing.append("public_clean (parcel id or owner text found)")
    if st.spec.uses_osm and st.elements.get("osm_credit") is not True:
        missing.append("osm_credit")
    if st.elements.get("text_rules") is False:
        missing.append("text_rules (em dash or PRELIMINARY in map text)")
    if not st.spec.sources or any("(" not in s for s in st.spec.sources):
        missing.append("sources with vintages ('name (vintage)')")
    if missing:
        plt.close(fig)
        raise MapStandardError("map standard: missing " + ", ".join(sorted(set(missing))))
