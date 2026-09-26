"""Map standard (ADR-0076): every map must carry the required elements, or finish() refuses."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from matplotlib.patches import Patch
from pyproj import CRS
from shapely.geometry import box

from parkiq.maps import MapSpec, MapStandardError, finish, locator, new_map, north_arrow, scale_bar

FT = CRS.from_epsg(3735)
CTX = gpd.GeoDataFrame(geometry=[box(0, 0, 100000, 80000)], crs=FT)


def _spec(**kw: object) -> MapSpec:
    base: dict[str, object] = dict(
        title="Test map", subtitle="Measure, weekday day, test area",
        how_to_read="Darker is more.", sources=["OSM parking (2026-09)"], uses_osm=True,
        units="stalls", market_extent=tuple(CTX.total_bounds),
    )  # fmt: skip
    base.update(kw)
    return MapSpec(**base)  # type: ignore[arg-type]


def _draw(spec: MapSpec, *, legend: bool = True, bar: bool = True, arrow: bool = True,
          view: tuple[float, float, float, float] | None = None, loc: bool = False,
          out: Path) -> Path:  # fmt: skip
    fig, ax = new_map(spec)
    CTX.plot(ax=ax, color="#dddddd")
    if view:
        ax.set_xlim(view[0], view[2])
        ax.set_ylim(view[1], view[3])
    if bar:
        scale_bar(ax, 5280, "1 mi")
    if arrow:
        north_arrow(ax)
    if loc and view:
        locator(fig, CTX, view)
    handles = [Patch(color="#08519c", label="high")] if legend else []
    return finish(fig, ax, handles, "Supply", out, view=view)


def test_complete_map_passes_and_records_elements(tmp_path: Path) -> None:
    out = _draw(_spec(), out=tmp_path / "ok.png")
    side = json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))["elements"]
    for k in ("title", "subtitle", "legend", "how_to_read", "scale_bar", "north_arrow",
              "sources", "brand_date", "preliminary", "osm_credit"):  # fmt: skip
        assert side[k], k
    assert out.exists()


@pytest.mark.parametrize("missing", ["legend", "bar", "arrow"])
def test_missing_element_is_refused(tmp_path: Path, missing: str) -> None:
    kw = {"legend": missing != "legend", "bar": missing != "bar", "arrow": missing != "arrow"}
    with pytest.raises(MapStandardError):
        _draw(_spec(), out=tmp_path / "x.png", **kw)
    assert not (tmp_path / "x.png").exists()


def test_sources_need_vintages(tmp_path: Path) -> None:
    with pytest.raises(MapStandardError, match="vintage"):
        _draw(_spec(sources=["OSM parking"]), out=tmp_path / "x.png")


def test_zoomed_map_needs_locator(tmp_path: Path) -> None:
    view = (0.0, 0.0, 20000.0, 16000.0)
    with pytest.raises(MapStandardError, match="locator"):
        _draw(_spec(), view=view, out=tmp_path / "x.png")
    assert _draw(_spec(), view=view, loc=True, out=tmp_path / "y.png").exists()


def test_public_map_rejects_parcel_ids(tmp_path: Path) -> None:
    with pytest.raises(MapStandardError, match="public_clean"):
        _draw(_spec(public=True, how_to_read="Lot 010-012345 is shown."), out=tmp_path / "x.png")
