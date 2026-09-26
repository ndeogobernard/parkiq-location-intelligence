"""Adapter contract and shared ingest helpers (docs/ARCHITECTURE.md §4).

Every source adapter:

* has a ``source_id`` and optional ``license_flag`` (key in ``market.data_licenses``);
* ``fetch`` → a local file (market ``path`` override wins; else download ``url`` into the
  per-market cache ``_cache/<source_id>/<vintage>/``);
* ``standardize`` → target-schema frames in the analysis CRS, clipped to StudyArea;
* ``write`` → ``Raw_*`` snapshot (EPSG:4326) + target layer + one ``DataSourceRegistry`` row.

A disabled or unlicensed adapter writes a registry row with status ``not configured``, logs a
WARNING naming the downstream effect, and writes no rows. It never substitutes synthetic data.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import geopandas as gpd
import pandas as pd
import requests
from pyproj import CRS

from parkiq.config import SourceEntry
from parkiq.store import utcnow

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 120  # network timeout, not an analysis parameter
_SECRET_PARAM = re.compile(r"([?&](?:key|api_key|apikey|token|access_token)=)[^&\s'\"]+", re.I)


def redact(text: str) -> str:
    """Mask secret query parameters (``key=…``) in URLs/messages before logging (ADR-0057)."""
    return _SECRET_PARAM.sub(lambda m: m.group(1) + "***", text)


SYNTHETIC_LABEL = "SYNTHETIC: NOT REAL DATA"


class IngestError(RuntimeError):
    """Raised when a source cannot be fetched or standardized."""


@dataclass
class Standardized:
    """Output of an adapter's ``standardize``: raw snapshot + target layers."""

    raw_layer: str | None
    raw: gpd.GeoDataFrame | None
    targets: dict[str, gpd.GeoDataFrame] = field(default_factory=dict)
    native_crs: str | None = None
    transformation: str | None = None
    notes: list[str] = field(default_factory=list)


class SourceAdapter:
    """Base class; subclasses implement :meth:`fetch` and :meth:`standardize`."""

    source_id: ClassVar[str]
    license_flag: ClassVar[str | None] = None
    downstream_effect: ClassVar[str] = ""

    def __init__(self, entry: SourceEntry) -> None:
        self.entry = entry

    # -------------------------------------------------------------- gating
    def is_enabled(self, ctx: RunContext) -> tuple[bool, str]:
        """Return (enabled, reason-if-not)."""
        if not self.entry.enabled:
            return False, "disabled in market config"
        flag = self.entry.license_flag or self.license_flag
        if flag:
            val = getattr(ctx.cfg.market.data_licenses, flag, False)
            if val in (False, "none", None):
                return False, f"license flag data_licenses.{flag} is off"
        if self.entry.path is None and not self.entry.url:
            return False, "no path or url configured"
        return True, ""

    # -------------------------------------------------------------- contract
    def fetch(self, ctx: RunContext) -> Any:
        """Return local input(s): the market ``path`` override, else a cached download."""
        if self.entry.path is not None:
            paths = self.entry.path if isinstance(self.entry.path, list) else [self.entry.path]
            for p in paths:
                if not Path(p).exists():
                    raise IngestError(f"{self.source_id}: path not found: {p}")
            return self.entry.path
        return download(self.render_url(self.entry.url or "", ctx), self.cache_dir(ctx))

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        """Convert fetched input into target-schema frames."""
        raise NotImplementedError

    # -------------------------------------------------------------- helpers
    def cache_dir(self, ctx: RunContext) -> Path:
        """``_cache/<source_id>/<vintage or 'latest'>/``."""
        p = ctx.cache_dir / self.source_id / (self.entry.vintage or "latest")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def render_url(self, template: str, ctx: RunContext, **extra: Any) -> str:
        """Fill ``{year}``, ``{release}``, ``{state_fips}``, ``{state_abbr}`` in a URL template."""
        vals: dict[str, Any] = {"year": self.entry.vintage, "release": self.entry.vintage}
        vals.update(self.entry.options.get("url_params", {}))
        vals.update(ctx.notes.get("url_params", {}))
        vals.update(extra)
        needed = set(re.findall(r"{(\w+)}", template))
        missing = [k for k in needed if vals.get(k) in (None, "")]
        if missing:
            raise IngestError(
                f"{self.source_id}: URL needs {missing}, set sources.{self.source_id}"
                f".vintage or options.url_params in the market config"
            )
        return template.format(**vals)

    def entry_endpoint(self) -> str:
        """Human-readable endpoint for the registry."""
        if self.entry.path is not None:
            return f"local: {self.entry.path}"
        return self.entry.url or ""


def collect(adapter: SourceAdapter, ctx: RunContext) -> Standardized | None:
    """Fetch → standardize one adapter; handle the not-configured path.

    Returns:
        The standardized frames, or None when the source is not configured (registry row and
        WARNING already written). Writing is done by the ingest step so that layers fed by
        several sources (e.g. ``Places``) are written once.
    """
    sid = adapter.source_id
    ok, why = adapter.is_enabled(ctx)
    if not ok:
        msg = f"{sid} {adapter.entry.dataset}: not configured ({why})"
        if adapter.downstream_effect:
            msg += f", effect: {adapter.downstream_effect}"
        log.warning(msg)
        register_source(ctx, sid, adapter.entry, status="not configured", row_count=0, notes=why)
        return None
    raw = adapter.fetch(ctx)
    std = adapter.standardize(raw, ctx)
    if adapter.entry.synthetic:
        std.notes.insert(0, SYNTHETIC_LABEL)
    return std


def register_source(
    ctx: RunContext,
    source_id: str,
    entry: SourceEntry,
    *,
    status: str,
    row_count: int,
    endpoint: str | None = None,
    native_crs: str | None = None,
    transformation: str | None = None,
    notes: str = "",
) -> None:
    """Upsert this run's ``DataSourceRegistry`` row for a source."""
    lic = entry.license
    if entry.synthetic:
        lic = f"{SYNTHETIC_LABEL} ({lic})" if lic else SYNTHETIC_LABEL
    if entry.verify and entry.path is None:
        lic = f"{lic} [VERIFY]"
    row = pd.DataFrame(
        [
            {
                "source_id": source_id,
                "provider": entry.provider,
                "dataset": entry.dataset,
                "endpoint": endpoint or (f"local: {entry.path}" if entry.path else entry.url),
                "vintage": entry.vintage,
                "download_date": utcnow().date().isoformat(),
                "license": lic,
                "native_crs": native_crs,
                "transformation": transformation,
                "row_count": row_count,
                "status": status,
                "notes": notes,
            }
        ]
    )
    ctx.store.write_table("DataSourceRegistry", row, key={"source_id": source_id})


# --------------------------------------------------------------------------- I/O helpers


def download(url: str, dest_dir: Path, filename: str | None = None) -> Path:
    """Download ``url`` into ``dest_dir`` once (cached by filename).

    Args:
        url: HTTP(S) URL.
        dest_dir: Cache directory.
        filename: Override the cached filename.

    Returns:
        Local path.

    Raises:
        IngestError: On HTTP errors.
    """
    name = (
        filename
        or url.split("?")[0].rstrip("/").split("/")[-1]
        or hashlib.sha1(url.encode()).hexdigest()
    )
    out = dest_dir / name
    if out.exists() and out.stat().st_size > 0:
        log.info("cache hit %s", out)
        return out
    log.info("download %s", redact(url))
    tmp = out.with_suffix(out.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=HTTP_TIMEOUT_S) as r:
            r.raise_for_status()
            r.raw.decode_content = True  # undo Content-Encoding (e.g. gzip), raw is not decoded
            with tmp.open("wb") as fh:
                shutil.copyfileobj(r.raw, fh)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise IngestError(redact(f"download failed: {url}: {exc}")) from None
    tmp.replace(out)
    return out


def read_vector(path: str | Path, **kwargs: Any) -> gpd.GeoDataFrame:
    """Read any OGR vector (shp, zip, gpkg, geojson, parquet)."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return gpd.read_parquet(p, **kwargs)
    return gpd.read_file(p, engine="pyogrio", **kwargs)


def points_from_xy(
    df: pd.DataFrame, x: str, y: str, crs: CRS | str = "EPSG:4326"
) -> gpd.GeoDataFrame:
    """Build a point GeoDataFrame from coordinate columns, dropping rows without coordinates."""
    d = df.copy()
    d[x] = pd.to_numeric(d[x], errors="coerce")
    d[y] = pd.to_numeric(d[y], errors="coerce")
    d = d.dropna(subset=[x, y])
    return gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d[x], d[y]), crs=crs)


def study_area(ctx: RunContext) -> gpd.GeoDataFrame:
    """The run's StudyArea polygon (analysis CRS)."""
    return ctx.store.read_layer("StudyArea")


def to_analysis(
    gdf: gpd.GeoDataFrame, ctx: RunContext, clip: bool = True
) -> tuple[gpd.GeoDataFrame, str, str]:
    """Reproject to the analysis CRS, repair geometry, and clip to StudyArea (by intersection).

    Features are kept whole if they intersect the study area (a parcel straddling the edge is
    not cut), matching the manual's "clip" intent for point/polygon inputs without slivers.

    Returns:
        (frame, native CRS string, transformation description)
    """
    if gdf.crs is None:
        raise IngestError("input has no CRS")
    native = CRS.from_user_input(gdf.crs)
    out = gdf.to_crs(ctx.cfg.crs)
    transformation = f"{native.to_string()} -> {ctx.cfg.crs.to_string()} (pyproj default)"
    if native.equals(ctx.cfg.crs):
        transformation = "none"
    out = out[out.geometry.notna() & ~out.geometry.is_empty].copy()
    if out.geometry.has_z.any():  # schema geometries are 2-D (e.g. Auditor parcels are Polygon Z)
        out[out.geometry.name] = out.geometry.force_2d()
    invalid = ~out.geometry.is_valid
    if invalid.any():
        out.loc[invalid, out.geometry.name] = out.loc[invalid].geometry.make_valid()
        log.info("repaired %d invalid geometries", int(invalid.sum()))
    if clip and len(out):
        sa = study_area(ctx).union_all()
        out = out[out.intersects(sa)].copy()
    return out, native.to_string(), transformation


def apply_field_map(
    df: pd.DataFrame, field_map: dict[str, str], required: list[str], source_id: str
) -> pd.DataFrame:
    """Rename source columns to target names using ``{target: source}``; check required ones."""
    missing_src = [src for tgt, src in field_map.items() if src not in df.columns]
    if missing_src:
        raise IngestError(
            f"{source_id}: field_map refers to columns not in the file: "
            f"{missing_src}. Available: {list(df.columns)[:40]}"
        )
    out = df.rename(columns={src: tgt for tgt, src in field_map.items()})
    lacking = [c for c in required if c not in out.columns]
    if lacking:
        raise IngestError(
            f"{source_id}: required target fields not mapped: {lacking} "
            f"(set sources.{source_id}.field_map in the market config)"
        )
    return out
