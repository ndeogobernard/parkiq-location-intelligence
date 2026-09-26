"""S18 — USGS 3DEP DEM (used by SetupMarket for Slope_pct).

Fetch order: market ``path`` (one GeoTIFF or a list of tiles) → ``options.mode``:

* ``imageserver`` (ADR-0056): one ``exportImage`` request to the 3DEP ImageServer for the
  StudyArea extent at ``options.cell_size_m`` in the analysis CRS, saved once in the cache and
  reused by every run (the service limit is ``maxImageWidth``/``Height``; the request fails loudly
  if the extent is too large rather than silently coarsening);
* ``tnm`` (default when no mode is set): TNM Access API product search, full 1° tiles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
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
        if self.entry.options.get("mode") == "imageserver":
            return self._fetch_imageserver(ctx)
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

    def _fetch_imageserver(self, ctx: RunContext) -> Path:
        """Export the study-area extent once from the 3DEP ImageServer (cached)."""
        import rasterio
        from rasterio.transform import from_bounds

        opts = self.entry.options
        url = opts.get("imageserver_url")
        cell_m = opts.get("cell_size_m")
        if not url or not cell_m:
            raise IngestError("S18 imageserver mode needs options.imageserver_url and cell_size_m")
        crs = ctx.cfg.crs
        epsg = crs.to_epsg()
        if epsg is None:
            raise IngestError("S18 imageserver mode needs an EPSG analysis CRS")
        minx, miny, maxx, maxy = ctx.store.read_layer("StudyArea").total_bounds
        cell = units.m_to_crs(float(cell_m), crs)
        w, h = math.ceil((maxx - minx) / cell), math.ceil((maxy - miny) / cell)
        maxx, maxy = minx + w * cell, miny + h * cell  # snap extent to whole cells
        key = hashlib.sha1(f"{epsg}|{minx:.1f}|{miny:.1f}|{w}|{h}|{cell_m}".encode()).hexdigest()[
            :10
        ]
        out = self.cache_dir(ctx) / f"dem_{cell_m}m_{key}.tif"
        if out.exists():
            log.info("S18: cached DEM %s", out.name)
            return out
        info = requests.get(url.rstrip("/"), params={"f": "json"}, timeout=HTTP_TIMEOUT_S).json()
        if w > int(info.get("maxImageWidth", w)) or h > int(info.get("maxImageHeight", h)):
            raise IngestError(
                f"S18: {w}x{h} px exceeds the ImageServer limit "
                f"{info.get('maxImageWidth')}x{info.get('maxImageHeight')}; "
                "tile the request or raise cell_size_m (a config decision)"
            )
        params: dict[str, str | int] = {
            "bbox": f"{minx},{miny},{maxx},{maxy}",
            "bboxSR": epsg,
            "imageSR": epsg,
            "size": f"{w},{h}",
            "format": "tiff",
            "pixelType": "F32",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "json",
        }
        try:
            r = requests.get(
                url.rstrip("/") + "/exportImage", params=params, timeout=HTTP_TIMEOUT_S
            )
            r.raise_for_status()
            meta = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise IngestError(f"S18 ImageServer exportImage failed: {exc}") from exc
        if "href" not in meta:
            raise IngestError(f"S18 ImageServer returned no image: {str(meta)[:300]}")
        raw = download(meta["href"], self.cache_dir(ctx), filename=f"export_{key}.tif")
        with rasterio.open(raw) as src:
            arr = src.read(1)
            nodata = src.nodata
            georef_ok = src.crs is not None and not src.transform.is_identity
            prof = src.profile
        if not georef_ok:  # write georeferencing from the service's reported extent
            ext = meta["extent"]
            prof.update(
                crs=crs.to_wkt(),
                transform=from_bounds(
                    ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"], arr.shape[1], arr.shape[0]
                ),
            )
        prof.update(driver="GTiff", compress="deflate", tiled=True)
        with rasterio.open(out, "w", **prof) as dst:
            dst.write(arr, 1)
            dst.update_tags(units="metre", source=url, cell_size_m=str(cell_m))
        (out.with_suffix(".json")).write_text(
            json.dumps(
                {
                    "request": params,
                    "response_extent": meta.get("extent"),
                    "nodata": nodata,
                    "georef_from_service": georef_ok,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raw.unlink(missing_ok=True)
        log.info("S18: exported %dx%d DEM at %s m -> %s", w, h, cell_m, out.name)
        return out

    @staticmethod
    def z_unit_m(ds: Any) -> float:
        """Metres per elevation unit. 3DEP is metres; honour a ``units`` tag if present."""
        u = (ds.units[0] if getattr(ds, "units", None) else None) or ds.tags().get("units", "")
        u = str(u).lower()
        if u in ("ft", "foot", "feet", "us survey foot", "ftus"):
            return units.M_PER_FT_INTL
        return 1.0
