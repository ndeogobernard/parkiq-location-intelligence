"""Walk-shed allocation of point quantities to hexes (ADR-0013 / plan D-08).

Each source point's value is split across the hexes whose centroid lies within the largest walk
band (default 8 min) in proportion to the decay weight of the hex's band; weights are renormalized
per source, so the allocation conserves the total. Travel time = network time between the nearest
nodes + straight-line snap distances at walking speed. A source with no hex centroid inside its
shed (isolated) goes wholly to the hex that contains it. Used for supply (M3) and demand (M4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from scipy import sparse
from scipy.sparse import csgraph
from scipy.spatial import cKDTree

from parkiq import units

log = logging.getLogger(__name__)

BATCH = 32  # sources per Dijkstra batch (memory: BATCH × nodes floats), not a parameter


@dataclass
class WalkGraph:
    """Compact walk graph for many-source shortest paths."""

    csr: sparse.csr_matrix
    xy: np.ndarray  # node coordinates (analysis CRS)
    tree: cKDTree
    min_per_unit: float  # walk minutes per CRS unit of straight-line distance

    @classmethod
    def from_layers(
        cls, nodes: gpd.GeoDataFrame, edges: gpd.GeoDataFrame, crs: CRS, speed_m_s: float
    ) -> WalkGraph:
        """Build from WalkNodes/WalkEdges (weights = ``walk_minutes``, undirected, min weight)."""
        ids = nodes["node_id"].astype(str).to_numpy()
        index = pd.Series(np.arange(len(ids)), index=ids)
        u = index.reindex(edges["u"].astype(str)).to_numpy()
        v = index.reindex(edges["v"].astype(str)).to_numpy()
        ok = ~(np.isnan(u) | np.isnan(v))
        w = edges["walk_minutes"].to_numpy(dtype=float)[ok]
        u, v = u[ok].astype(int), v[ok].astype(int)
        n = len(ids)
        # parallel edges and both directions: keep the shortest time per node pair
        df = pd.DataFrame({"a": np.r_[u, v], "b": np.r_[v, u], "w": np.r_[w, w]})
        df = df.groupby(["a", "b"], as_index=False)["w"].min()
        m = sparse.csr_matrix((df["w"], (df["a"], df["b"])), shape=(n, n))
        xy = np.c_[nodes.geometry.x.to_numpy(), nodes.geometry.y.to_numpy()]
        per_unit = units.crs_unit_to_m(crs) / speed_m_s / 60.0
        return cls(m, xy, cKDTree(xy), per_unit)

    def snap(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nearest node index and snap time (minutes) for each point."""
        d, i = self.tree.query(pts)
        return i, d * self.min_per_unit


def band_weight(minutes: np.ndarray, bands: list[float], weights: dict[float, float]) -> np.ndarray:
    """Decay weight of the band each travel time falls in (0 beyond the last band)."""
    out = np.zeros_like(minutes, dtype=float)
    lower = -np.inf
    for b in sorted(bands):
        sel = (minutes > lower) & (minutes <= b)
        out[sel] = weights[b]
        lower = b
    return out


def allocate_matrix(
    points: gpd.GeoDataFrame,
    values: np.ndarray,
    hexes: gpd.GeoDataFrame,
    graph: WalkGraph,
    bands: list[float],
    weights: dict[float, float],
    keep_weights: bool = False,
) -> tuple[pd.DataFrame, dict[str, int], pd.DataFrame | None]:
    """Allocate several value columns (n points × k) with one walk-shed computation per point.

    Returns:
        (hex_id × k totals, stats, per-source weights ``src, hex_id, w`` if ``keep_weights``),
        ``src`` is the row position in ``points``; weights sum to 1 per allocated source.
    """
    vals2 = np.nan_to_num(np.asarray(values, dtype=float))
    if vals2.ndim == 1:
        vals2 = vals2[:, None]
    keep = vals2.sum(axis=1) > 0
    src_pos = np.flatnonzero(keep)
    pts = points.iloc[src_pos]
    vals = vals2[keep]
    cent = hexes.geometry.centroid
    hex_xy = np.c_[cent.x.to_numpy(), cent.y.to_numpy()]
    hex_node, hex_snap = graph.snap(hex_xy)
    src_xy = np.c_[pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy()]
    src_node, src_snap = graph.snap(src_xy)
    limit = max(bands)
    total = np.zeros((len(hexes), vals.shape[1]))
    isolated = outside = 0
    reach = limit / graph.min_per_unit  # candidate centroids within straight-line reach
    hex_tree = cKDTree(hex_xy)
    wrows: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for start in range(0, len(vals), BATCH):
        sl = slice(start, start + BATCH)
        dist = csgraph.dijkstra(
            graph.csr, directed=False, indices=src_node[sl], limit=limit, min_only=False
        )
        for k, j in enumerate(range(start, min(start + BATCH, len(vals)))):
            cand = np.array(hex_tree.query_ball_point(src_xy[j], reach), dtype=int)
            if len(cand):
                t = dist[k, hex_node[cand]] + src_snap[j] + hex_snap[cand]
                w = band_weight(t, bands, weights)
            else:
                w = np.zeros(0)
            if w.sum() > 0:
                nz = w > 0
                cand, w = cand[nz], w[nz] / w.sum()
            else:
                isolated += 1
                own = hexes.index.get_indexer(
                    gpd.sjoin(
                        gpd.GeoDataFrame(geometry=[pts.geometry.iloc[j]], crs=pts.crs),
                        hexes[["geometry"]],
                        predicate="within",
                    )["index_right"]
                )
                if not len(own):
                    outside += 1
                    continue
                cand, w = own[:1], np.array([1.0])
            total[cand] += np.outer(w, vals[j])
            if keep_weights:
                wrows.append((np.full(len(cand), src_pos[j]), cand, w))
    out = pd.DataFrame(total, index=hexes["hex_id"].to_numpy())
    stats = {
        "sources": len(vals),
        "isolated_to_own_hex": isolated - outside,
        "outside_grid_dropped": outside,
    }
    log.info("allocation: %s; conserved %.1f of %.1f", stats, total.sum(), vals.sum())
    wdf = None
    if keep_weights and wrows:
        hid = hexes["hex_id"].to_numpy()
        wdf = pd.DataFrame(
            {
                "src": np.concatenate([r[0] for r in wrows]),
                "hex_id": hid[np.concatenate([r[1] for r in wrows])],
                "w": np.concatenate([r[2] for r in wrows]),
            }
        )
    return out, stats, wdf


def allocate(
    points: gpd.GeoDataFrame,
    values: np.ndarray,
    hexes: gpd.GeoDataFrame,
    graph: WalkGraph,
    bands: list[float],
    weights: dict[float, float],
) -> tuple[pd.Series, dict[str, int]]:
    """Allocate one value column; returns (value per hex_id, stats). See :func:`allocate_matrix`."""
    out, stats, _ = allocate_matrix(points, values, hexes, graph, bands, weights)
    return out[0], stats
