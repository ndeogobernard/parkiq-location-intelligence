"""Source ingest (tool 3 ``IngestSources``; SCOPE §3, §5.1).

M1 adapters (free sources): S01 county parcels, S02/S03a Overture, S03b/S06 OSM, S04 LODES,
S05 ACS, S09 GTFS, S10 venues, S12a hospitals, S12b IPEDS, S13 AADT, S14 FEMA, S15 EPA.
S00/S08/S18 are consumed by SetupMarket. M2 adds city zoning (S23/S23b/S23c, with the parcel
zoning join) and not-configured stubs for Regrid (S01R) and listings (S07, S16).
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd

from parkiq.ingest.aadt import AadtAdapter
from parkiq.ingest.acs import AcsAdapter
from parkiq.ingest.base import IngestError, SourceAdapter, collect, register_source
from parkiq.ingest.city_open_data import (
    ParkingZonesAdapter,
    ZoningDistrictsAdapter,
    ZoningOverlaysAdapter,
    assign_zoning,
    load_table,
)
from parkiq.ingest.county_parcels import CountyParcelsAdapter
from parkiq.ingest.epa import EpaAdapter
from parkiq.ingest.events import VenuesAdapter
from parkiq.ingest.fema import FemaAdapter
from parkiq.ingest.gtfs import GtfsAdapter
from parkiq.ingest.hospitals import HospitalsAdapter
from parkiq.ingest.ipeds import IpedsAdapter
from parkiq.ingest.listings import LandListingsAdapter, ParkingListingsAdapter
from parkiq.ingest.lodes import LodesAdapter
from parkiq.ingest.osm import OsmParkingAdapter, OsmPoiAdapter
from parkiq.ingest.overture import OvertureBuildingsAdapter, OverturePlacesAdapter
from parkiq.ingest.regrid import RegridParcelsAdapter
from parkiq.runner import RunContext, register
from parkiq.store import WGS84

log = logging.getLogger(__name__)

ADAPTERS: tuple[type[SourceAdapter], ...] = (
    CountyParcelsAdapter,
    OvertureBuildingsAdapter,
    OverturePlacesAdapter,
    OsmPoiAdapter,
    LodesAdapter,
    AcsAdapter,
    OsmParkingAdapter,
    GtfsAdapter,
    VenuesAdapter,
    HospitalsAdapter,
    IpedsAdapter,
    AadtAdapter,
    FemaAdapter,
    EpaAdapter,
    ZoningDistrictsAdapter,
    ZoningOverlaysAdapter,
    ParkingZonesAdapter,
    RegridParcelsAdapter,
    ParkingListingsAdapter,
    LandListingsAdapter,
)
SOURCE_IDS = tuple(a.source_id for a in ADAPTERS)


@register(
    "ingest",
    deps=("setup",),
    reads=("sources", "market.demand.transit_adjustment", "market.data_licenses"),
)
def run_ingest(ctx: RunContext) -> dict[str, Any]:
    """Tool 3 IngestSources: run every (or the selected) adapter and write their layers.

    Layers fed by more than one source (``Places``) are written once with a per-row
    ``source_id``. With ``--sources`` only those adapters run; rows other sources wrote to a
    shared layer earlier in this run are kept.
    """
    wanted = set(ctx.source_filter or SOURCE_IDS)
    unknown = wanted - set(SOURCE_IDS)
    if unknown:
        raise IngestError(f"unknown source ids {sorted(unknown)}; valid: {', '.join(SOURCE_IDS)}")
    targets: dict[str, list[gpd.GeoDataFrame]] = {}
    summary: dict[str, Any] = {}
    for cls in ADAPTERS:
        sid = cls.source_id
        if sid not in wanted:
            continue
        adapter = cls(ctx.cfg.sources[sid])
        log.info("--- ingest %s (%s)", sid, adapter.entry.dataset)
        try:
            std = collect(adapter, ctx)
        except Exception as exc:
            register_source(ctx, sid, adapter.entry, status="failed", row_count=0, notes=str(exc))
            raise
        if std is None:
            summary[sid] = "not configured"
            continue
        if std.raw_layer and std.raw is not None:
            raw = std.raw if std.raw.crs is not None else std.raw.set_crs(WGS84)
            ctx.store.write_layer(std.raw_layer, raw.to_crs(WGS84), sid)
        n = 0
        for layer, gdf in std.targets.items():
            g = gdf.copy()
            g["source_id"] = sid
            targets.setdefault(layer, []).append(g)
            n += len(g)
        register_source(
            ctx,
            sid,
            adapter.entry,
            status="loaded",
            row_count=n,
            endpoint=adapter.entry_endpoint(),
            native_crs=std.native_crs,
            transformation=std.transformation,
            notes="; ".join(std.notes),
        )
        summary[sid] = n
    if "Parcels" in targets:
        summary["zoning"] = _zone_parcels(ctx, targets)
    for layer, frames in targets.items():
        rerun = {str(s) for f in frames for s in f["source_id"].unique()}
        if ctx.source_filter and ctx.store.has(layer):
            prev = ctx.store.read_layer(layer)
            keep = prev[~prev["source_id"].isin(rerun)].drop(columns=["run_id", "load_ts"])
            if len(keep):
                frames = [keep, *frames]
        merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[-1].crs)
        ctx.store.write_layer(layer, merged, None)
    return {"sources": summary}


ZONING_LAYERS = ("ZoningDistricts", "ZoningOverlays", "ParkingZones")


def _zone_parcels(ctx: RunContext, targets: dict[str, list[gpd.GeoDataFrame]]) -> Any:
    """Put zoning code, overlays, parking zone and zoning screen on the Parcels frame (in place).

    Zoning layers come from this ingest (``targets``) or, when not re-ingested, from the run
    GeoPackage. Without a zoning table (S23 ``options.zoning_table_path``) nothing is resolved.
    """
    opts = ctx.cfg.sources["S23"].options if "S23" in ctx.cfg.sources else {}
    table = load_table(opts)
    if table is None:
        log.warning("no zoning table configured (sources.S23.options.zoning_table_path)")
        return "no zoning table"
    written = set(ctx.store.written_layers())
    layers: dict[str, gpd.GeoDataFrame | None] = {}
    for name in ZONING_LAYERS:
        if name in targets:
            layers[name] = gpd.GeoDataFrame(pd.concat(targets[name]), crs=targets[name][-1].crs)
        elif name in written:
            layers[name] = ctx.store.read_layer(name)
        else:
            layers[name] = None
    review_ft = float(
        ctx.cfg.sources["S23c"].options.get("boundary_review_ft", 0)
        if "S23c" in ctx.cfg.sources
        else 0
    )
    frames = targets["Parcels"]
    parcels = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[-1].crs)
    zoned, stats = assign_zoning(
        parcels,
        table,
        layers["ZoningDistricts"],
        layers["ZoningOverlays"],
        layers["ParkingZones"],
        review_ft,
    )
    targets["Parcels"] = [zoned]
    log.info("zoning assigned: %s", stats)
    return stats
