"""Paged query of an ArcGIS REST MapServer/FeatureServer layer clipped to a bbox.

Used by S13 (state DOT AADT), S14 (FEMA NFHL) and city open-data layers (M2). Standard ArcGIS
REST ``/query`` parameters; each service's exact layer URL is [VERIFY] per market.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import requests

from parkiq.ingest.base import HTTP_TIMEOUT_S, IngestError

log = logging.getLogger(__name__)


def query_to_geojson(
    layer_url: str,
    bbox_4326: Sequence[float],
    out: Path,
    where: str = "1=1",
    page_size: int = 1000,
) -> Path:
    """Download all features intersecting ``bbox_4326`` as one GeoJSON file (cached).

    Args:
        layer_url: ``.../MapServer/<n>`` or ``.../FeatureServer/<n>``.
        bbox_4326: (minx, miny, maxx, maxy) in EPSG:4326.
        out: Output GeoJSON path (returned as-is if it already exists).
        where: SQL filter.
        page_size: Records per request (server max may be lower; paging continues either way).

    Returns:
        Path to the GeoJSON.
    """
    if out.exists() and out.stat().st_size > 0:
        return out
    feats: list[dict[str, object]] = []
    offset = 0
    minx, miny, maxx, maxy = bbox_4326
    while True:
        params: dict[str, str | int] = {
            "where": where,
            "outFields": "*",
            "f": "geojson",
            "outSR": 4326,
            "inSR": 4326,
            "geometry": f"{minx},{miny},{maxx},{maxy}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "resultOffset": offset,
            "resultRecordCount": page_size,
            "returnGeometry": "true",
        }
        try:
            r = requests.get(
                layer_url.rstrip("/") + "/query", params=params, timeout=HTTP_TIMEOUT_S
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise IngestError(f"ArcGIS REST query failed: {layer_url}: {exc}") from exc
        if "error" in data:
            raise IngestError(f"ArcGIS REST error from {layer_url}: {data['error']}")
        batch = data.get("features", [])
        feats.extend(batch)
        exceeded = data.get("exceededTransferLimit") or data.get("properties", {}).get(
            "exceededTransferLimit"
        )
        if not batch or (not exceeded and len(batch) < page_size):
            break
        offset += len(batch)
    log.info("ArcGIS REST %s: %d features", layer_url, len(feats))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return out
