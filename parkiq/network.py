"""Pedestrian network (SCOPE §5.1, §5.6; ADR-0004 = OSMnx + pandana, confirmed 2026-09-24).

M1: build the walk graph and export WalkNodes / WalkEdges with ``walk_minutes``.
M4/M5 add travel-time matrices (pandana) and walk-shed polygons (tool 9).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import networkx as nx
import osmnx as ox

from parkiq import units
from parkiq.store import WGS84

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)


def _listish(v: Any) -> Any:
    """OSMnx stores merged attributes as lists; flatten to a ``;``-joined string."""
    if isinstance(v, list):
        return ";".join(str(x) for x in v)
    return v


def load_or_download_graph(
    ctx: RunContext, study_a: gpd.GeoDataFrame
) -> tuple[nx.MultiDiGraph, str]:
    """Return the unprojected walk graph and a description of where it came from.

    Order: ``network.graph_path`` (local GraphML) → per-market cache → OSMnx download
    (Overpass) for the StudyArea polygon, then cached as GraphML.
    """
    net = ctx.cfg.market.network
    if net.graph_path is not None:
        log.info("loading walk graph from %s", net.graph_path)
        return ox.load_graphml(net.graph_path), f"local: {net.graph_path}"
    poly = study_a.to_crs(WGS84).union_all()
    key = hashlib.sha1(f"{poly.wkb_hex}|{net.network_type}".encode()).hexdigest()[:12]
    cache = ctx.cache_dir / "S08" / f"walk_{key}.graphml"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        log.info("walk graph cache hit %s", cache)
        return ox.load_graphml(cache), f"cache: {cache.name} (OSM via Overpass)"
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(ctx.cache_dir / "osmnx_http")
    log.info("downloading OSM walk network for the study area (this can take several minutes)")
    g = ox.graph_from_polygon(poly, network_type=net.network_type, retain_all=False)
    ox.save_graphml(g, cache)
    return g, f"overpass (network_type={net.network_type}); cached {cache.name}"


def build_walk_network(
    ctx: RunContext, study_a: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, str]]:
    """Build WalkNodes/WalkEdges in the analysis CRS with walk time per edge.

    ``length_m`` is OSMnx's edge ``length`` attribute (metres, great-circle for downloaded
    graphs). ``walk_minutes = length_m / walking_speed_m_s / 60``.

    Returns:
        (nodes, edges, info), info has endpoint / native_crs / transformation / notes.
    """
    g, endpoint = load_or_download_graph(ctx, study_a)
    native = str(g.graph.get("crs", "unknown"))
    gp = ox.project_graph(g, to_crs=ctx.cfg.crs)
    nodes, edges = ox.graph_to_gdfs(gp, nodes=True, edges=True)
    speed = ctx.cfg.market.network.walking_speed_m_s

    nodes = nodes.reset_index()
    ncol = "osmid" if "osmid" in nodes.columns else nodes.columns[0]
    n_out = gpd.GeoDataFrame(
        {
            "node_id": nodes[ncol].astype(str),
            "street_count": nodes["street_count"] if "street_count" in nodes.columns else None,
        },
        geometry=nodes.geometry,
        crs=ctx.cfg.crs,
    )

    e = edges.reset_index()
    if "length" not in e.columns:
        raise ValueError("walk graph edges have no 'length' attribute (metres)")
    e_out = gpd.GeoDataFrame(
        {
            "u": e["u"].astype(str),
            "v": e["v"].astype(str),
            "key": e["key"].astype(int),
            "osmid": e["osmid"].map(_listish).astype(str) if "osmid" in e.columns else None,
            "highway": e["highway"].map(_listish) if "highway" in e.columns else None,
            "name": e["name"].map(_listish) if "name" in e.columns else None,
            "length_m": e["length"].astype(float),
        },
        geometry=e.geometry,
        crs=ctx.cfg.crs,
    )
    e_out["walk_minutes"] = e_out["length_m"].map(lambda m: units.walk_minutes(m, speed))
    n_out = n_out.sort_values("node_id").reset_index(drop=True)
    e_out = e_out.sort_values(["u", "v", "key"]).reset_index(drop=True)
    info = {
        "endpoint": endpoint,
        "native_crs": native,
        "transformation": f"{native} -> {ctx.cfg.crs.to_string()} (osmnx.project_graph)",
        "notes": f"walking speed {speed} m/s",
    }
    return n_out, e_out, info


def graph_from_layers(nodes: gpd.GeoDataFrame, edges: gpd.GeoDataFrame) -> nx.MultiDiGraph:
    """Rebuild a networkx graph (weights ``walk_minutes``) from the stored layers."""
    g = nx.MultiDiGraph()
    for r in nodes.itertuples():
        g.add_node(r.node_id, x=r.geometry.x, y=r.geometry.y)
    for r in edges.itertuples():
        g.add_edge(r.u, r.v, key=int(r.key), length_m=r.length_m, walk_minutes=r.walk_minutes)
    return g


def save_graphml(g: nx.MultiDiGraph, path: Path) -> None:
    """Thin wrapper kept for fixture generation."""
    ox.save_graphml(g, path)
