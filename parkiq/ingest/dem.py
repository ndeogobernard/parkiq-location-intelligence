"""S18 — USGS 3DEP DEM (used by SetupMarket for Slope_pct).

Fetch order: market ``path`` (one GeoTIFF or a list of tiles) → TNM Access API product search
for the study-area bbox [VERIFY V-23: endpoint and dataset name].
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests

from parkiq import units
from parkiq.ingest.base import HTTP_TIMEOUT_S, IngestError, SourceAdapter, download
from parkiq.store import WGS84

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)


class DemAdapter(SourceAdapter):
    """3DEP 1/3 arc-second DEM tiles."""

    source_id = "S18"
    downstream_effect = "no Slope_pct; slope screen cannot run"

    def fetch(self, ctx: RunContext) -> Any:
        """Local tiles, or tiles found through the TNM Access API and cached."""
        if self.entry.path is not None:
            return super().fetch(ctx)
        study = ctx.store.read_layer("StudyArea").to_crs(WGS84)
        minx, miny, maxx, maxy = study.total_bounds
        params = {
            "datasets": self.entry.options.get("dataset_name"),
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "prodFormats": "GeoTIFF",
            "outputFormat": "JSON",
            "max": 100,
        }
        try:
            r = requests.get(self.entry.url or "", params=params, timeout=HTTP_TIMEOUT_S)
            r.raise_for_status()
            items = r.json().get("items", [])
        except (requests.RequestException, ValueError) as exc:
            raise IngestError(f"S18 TNM product search failed: {exc}") from exc
        # Several dated versions of one tile can be listed; keep the newest per tile title stem.
        latest: dict[str, dict[str, Any]] = {}
        for it in items:
            stem = str(it.get("title", "")).split(" 20")[0]
            if stem not in latest or str(it.get("publicationDate", "")) > str(
                latest[stem].get("publicationDate", "")
            ):
                latest[stem] = it
        if not latest:
            raise IngestError("S18: TNM returned no DEM tiles for the study area bbox")
        paths: list[Path] = []
        for it in latest.values():
            paths.append(download(it["downloadURL"], self.cache_dir(ctx)))
        log.info("S18: %d DEM tiles", len(paths))
        return paths

    @staticmethod
    def z_unit_m(ds: Any) -> float:
        """Metres per elevation unit. 3DEP is metres; honour a ``units`` tag if present."""
        u = (ds.units[0] if getattr(ds, "units", None) else None) or ds.tags().get("units", "")
        u = str(u).lower()
        if u in ("ft", "foot", "feet", "us survey foot", "ftus"):
            return units.M_PER_FT_INTL
        return 1.0
