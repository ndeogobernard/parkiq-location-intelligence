"""S01 fallback — county assessor/auditor parcels (+ CAMA attributes). Used when Regrid is not
licensed (SCOPE §14). Field names differ by county, so everything is mapped in the market config:

.. code-block:: yaml

    sources:
      S01:
        path: data/parcels.shp            # polygons
        field_map: {parcel_id: PARCELID, owner: OWNERNME1, ...}   # target: source column
        options:
          cama_path: data/cama.csv        # optional attribute table
          cama_join: {parcels: PARCELID, cama: PARCEL_ID}
          cama_field_map: {assessed_land_value: LAND_VAL, ...}
          land_use_crosswalk_path: data/xwalk.csv  # county_code,land_use_class[,...]
          owner_rules: [{pattern: "\\b(CITY|COUNTY|STATE)\\b", owner_type: Public}, ...]

Unmatched land-use codes → ``Other`` (counted); no crosswalk → ``land_use_class`` null + warning.
Owners matching no rule → ``Unknown``. Rules are regular expressions, case-insensitive, first wins.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd

from parkiq import units
from parkiq.ingest.base import (
    IngestError,
    SourceAdapter,
    Standardized,
    apply_field_map,
    read_vector,
    to_analysis,
)

if TYPE_CHECKING:
    from parkiq.runner import RunContext

log = logging.getLogger(__name__)

TARGET_FIELDS = [
    "parcel_id",
    "apn",
    "address",
    "owner",
    "land_use_code",
    "zoning_code",
    "assessed_land_value",
    "assessed_improvement_value",
    "year_built",
]
LAND_USE_CLASSES = {
    "Vacant",
    "SurfaceParking",
    "Commercial",
    "Industrial",
    "Residential",
    "MixedUse",
    "Institutional",
    "Other",
}


def _read_table(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(path, dtype=str)
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    return pd.DataFrame(read_vector(path, read_geometry=False)).astype(str)


def classify_owner(owner: Any, rules: list[dict[str, str]]) -> str:
    """Apply ordered regex rules to an owner name; ``Unknown`` when none match."""
    if owner is None or (isinstance(owner, float) and np.isnan(owner)) or not str(owner).strip():
        return "Unknown"
    for r in rules:
        if re.search(r["pattern"], str(owner), flags=re.IGNORECASE):
            return r["owner_type"]
    return "Unknown"


def improvement_ratio(land: pd.Series, impr: pd.Series) -> pd.Series:
    """``improvement / land``; null where land is null or 0 (SCOPE §4.5 NULLIF)."""
    land = pd.to_numeric(land, errors="coerce")
    impr = pd.to_numeric(impr, errors="coerce")
    return (impr / land.where(land != 0)).astype("float64")


class CountyParcelsAdapter(SourceAdapter):
    """County parcels + CAMA."""

    source_id = "S01"
    downstream_effect = "no Parcels — candidate screen, land cost and finance cannot run"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        """Map fields, join CAMA, compute lot_sqft / ratio, classify land use and owner."""
        opts = self.entry.options
        parcels = read_vector(raw if not isinstance(raw, list) else raw[0])
        notes: list[str] = []
        if opts.get("cama_path"):
            join = opts.get("cama_join") or {}
            if set(join) != {"parcels", "cama"}:
                raise IngestError("S01 options.cama_join must be {parcels: <col>, cama: <col>}")
            cama = _read_table(Path(opts["cama_path"]))
            cfm = opts.get("cama_field_map", {})
            cama = apply_field_map(cama, cfm, [], "S01 CAMA")
            keep = [join["cama"], *cfm.keys()]
            dup = int(cama[join["cama"]].duplicated().sum())
            if dup:
                notes.append(f"CAMA had {dup} duplicate keys; first row kept")
            cama = cama[keep].drop_duplicates(join["cama"])
            parcels[join["parcels"]] = parcels[join["parcels"]].astype(str)
            parcels = parcels.merge(
                cama,
                left_on=join["parcels"],
                right_on=join["cama"],
                how="left",
                suffixes=("", "_cama"),
            )
            notes.append(f"CAMA joined: {int(parcels[join['cama']].notna().sum())}/{len(parcels)}")
        raw_snapshot = parcels.copy()
        p = apply_field_map(parcels, self.entry.field_map, ["parcel_id"], "S01")
        p, native, transf = to_analysis(p, ctx)
        p["parcel_id"] = p["parcel_id"].astype(str)
        # Multipart duplicates of one parcel id → dissolve (attributes: first)
        dups = int(p["parcel_id"].duplicated().sum())
        if dups:
            cols = [c for c in TARGET_FIELDS if c in p.columns]
            p = p.dissolve(by="parcel_id", aggfunc="first", as_index=False)[[*cols, "geometry"]]
            notes.append(f"dissolved {dups} duplicate parcel_id parts")
        out = gpd.GeoDataFrame(
            {c: p[c] if c in p.columns else None for c in TARGET_FIELDS},
            geometry=p.geometry,
            crs=p.crs,
        )
        out["lot_sqft"] = out.geometry.area.map(lambda a: units.crs_area_to_sqft(a, ctx.cfg.crs))
        out["improvement_value_ratio"] = improvement_ratio(
            out["assessed_land_value"], out["assessed_improvement_value"]
        )
        # land use
        xw_path = opts.get("land_use_crosswalk_path")
        if xw_path:
            xw = pd.read_csv(xw_path, dtype=str)
            if not {"county_code", "land_use_class"} <= set(xw.columns):
                raise IngestError(
                    "land_use_crosswalk_path needs columns county_code, land_use_class"
                )
            bad = set(xw["land_use_class"]) - LAND_USE_CLASSES
            if bad:
                raise IngestError(
                    f"land_use_crosswalk_path has classes outside dm_LandUseClass: {bad}"
                )
            m = dict(zip(xw["county_code"].str.strip(), xw["land_use_class"], strict=True))
            codes = out["land_use_code"].astype(str).str.strip()
            out["land_use_class"] = codes.map(m)
            unmatched = int(out["land_use_class"].isna().sum())
            out["land_use_class"] = out["land_use_class"].fillna("Other")
            notes.append(f"land_use_class: {unmatched} parcels with unmatched codes set to Other")
        else:
            out["land_use_class"] = None
            log.warning(
                "S01: no land_use_crosswalk configured — land_use_class left null; the "
                "screen's land-use filter will mark parcels Review"
            )
            notes.append("no land-use crosswalk (land_use_class null)")
        rules = opts.get("owner_rules") or []
        if not rules:
            notes.append("no owner_rules (owner_type Unknown)")
        out["owner_type"] = out["owner"].map(lambda o: classify_owner(o, rules))
        out["zoning_screen"] = None  # M2: zoning table join (S23 / Regrid zoning)
        for c in ("frontage_ft", "shape_index", "corner_flag", "listing_price", "listing_source"):
            out[c] = None  # computed in the screen step (M5) / listings (M2)
        out = out.sort_values("parcel_id").reset_index(drop=True)
        raw4326 = raw_snapshot.to_crs(4326) if raw_snapshot.crs else raw_snapshot
        raw4326 = raw4326[raw4326.geometry.notna()]
        for c in raw4326.columns:
            if c != raw4326.geometry.name and raw4326[c].dtype == object:
                raw4326[c] = raw4326[c].map(
                    lambda v: json.dumps(v) if isinstance(v, list | dict) else v
                )
        return Standardized("Raw_Parcels", raw4326, {"Parcels": out}, native, transf, notes)
