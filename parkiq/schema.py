"""Schema model (``schema/schema.yaml``) and write-time validation.

M1 scope: load the schema, validate/coerce frames against it, and write the config tables.
M2 adds the full BuildSchema (empty layers, GeoPackage schema-extension constraints, related
tables), schema-diff, ERD and data-dictionary generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

TYPES = {"TEXT", "INTEGER", "REAL", "DATETIME", "BOOLEAN", "JSON"}


class SchemaError(ValueError):
    """Raised when data does not conform to schema.yaml."""


@dataclass(frozen=True)
class FieldDef:
    """One field definition."""

    name: str
    type: str
    nullable: bool = True
    unique: bool = False
    domain: str | None = None


@dataclass(frozen=True)
class LayerDef:
    """One layer/table definition."""

    name: str
    fields: tuple[FieldDef, ...]
    geometry: str | None = None
    crs: str = "none"  # analysis | wgs84 | none
    feature_dataset: str | None = None
    raw: bool = False

    @property
    def is_spatial(self) -> bool:
        """True for feature classes."""
        return self.geometry is not None


@dataclass
class Schema:
    """Parsed schema.yaml."""

    version: str
    lineage: tuple[FieldDef, ...]
    domains: dict[str, dict[str, Any]]
    layers: dict[str, LayerDef] = field(default_factory=dict)
    rasters: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> Schema:
        """Load and sanity-check ``schema.yaml``.

        Args:
            path: Path to the schema file.

        Returns:
            Parsed schema.

        Raises:
            SchemaError: On unknown types or dangling domain references.
        """
        p = Path(path)
        d = yaml.safe_load(p.read_text(encoding="utf-8"))

        def _fields(spec: dict[str, Any]) -> tuple[FieldDef, ...]:
            out = []
            for name, f in spec.items():
                if f["type"] not in TYPES:
                    raise SchemaError(f"{name}: unknown type {f['type']}")
                if f.get("domain") and f["domain"] not in d["domains"]:
                    raise SchemaError(f"{name}: unknown domain {f['domain']}")
                out.append(
                    FieldDef(
                        name,
                        f["type"],
                        f.get("nullable", True),
                        f.get("unique", False),
                        f.get("domain"),
                    )
                )
            return tuple(out)

        lineage = _fields(d["lineage_fields"])
        layers: dict[str, LayerDef] = {}
        for name, spec in d.get("layers", {}).items():
            layers[name] = LayerDef(
                name,
                _fields(spec.get("fields", {})),
                spec["geometry"],
                spec.get("crs", "analysis"),
                spec.get("feature_dataset"),
            )
        for name, spec in d.get("tables", {}).items():
            layers[name] = LayerDef(name, _fields(spec.get("fields", {})), None, "none")
        raw = d.get("raw_layers", {})
        for name in raw.get("names", []):
            layers[name] = LayerDef(name, (), "Geometry", raw.get("crs", "wgs84"), "Raw", raw=True)
        return cls(str(d["version"]), lineage, d["domains"], layers, d.get("rasters", {}), p)

    def layer(self, name: str) -> LayerDef:
        """Return a layer definition or raise."""
        if name not in self.layers:
            raise SchemaError(f"Layer {name!r} is not in schema.yaml")
        return self.layers[name]

    def domain_ok(self, domain: str, value: Any) -> bool:
        """True if ``value`` satisfies the named domain (nulls always pass)."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return True
        dom = self.domains[domain]
        if dom["type"] == "coded":
            return value in dom["values"]
        return bool(dom["min"] <= float(value) <= dom["max"])


def conform(df: pd.DataFrame, ldef: LayerDef, schema: Schema, spatial: bool) -> pd.DataFrame:
    """Validate and coerce a frame to its schema definition.

    Adds missing nullable schema fields as nulls, orders schema fields first, coerces types and
    checks nullability, uniqueness and domains. Extra columns are allowed only on raw layers.

    Args:
        df: Frame to write (GeoDataFrame for spatial layers). Must already have lineage fields.
        ldef: Target layer definition.
        schema: Loaded schema (for domains).
        spatial: Whether the frame carries geometry.

    Returns:
        A conformed copy.

    Raises:
        SchemaError: Listing every violation found.
    """
    out = df.copy()
    errs: list[str] = []
    fields = list(schema.lineage) + ([] if ldef.raw else list(ldef.fields))
    geom_col = out.geometry.name if spatial else None
    if not ldef.raw:
        allowed = {f.name for f in fields} | ({geom_col} if geom_col else set())
        extra = [c for c in out.columns if c not in allowed]
        if extra:
            errs.append(f"columns not in schema: {extra}")
    for f in fields:
        if f.name not in out.columns:
            if not f.nullable:
                errs.append(f"missing non-nullable field {f.name}")
                continue
            out[f.name] = None
        col = out[f.name]
        if f.type == "INTEGER":
            out[f.name] = pd.to_numeric(col, errors="coerce").astype("Int64")
        elif f.type == "REAL":
            out[f.name] = pd.to_numeric(col, errors="coerce").astype("float64")
        elif f.type == "BOOLEAN":
            out[f.name] = col.map(
                lambda v: (
                    None if v is None or (isinstance(v, float) and pd.isna(v)) else int(bool(v))
                )
            ).astype("Int64")
        elif f.type == "DATETIME":
            out[f.name] = pd.to_datetime(col, utc=True)
        else:  # TEXT / JSON
            out[f.name] = col.map(
                lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            ).astype("object")
        if not f.nullable and out[f.name].isna().any():
            errs.append(f"{f.name}: {int(out[f.name].isna().sum())} null values (non-nullable)")
        if f.unique and out[f.name].dropna().duplicated().any():
            errs.append(
                f"{f.name}: {int(out[f.name].dropna().duplicated().sum())} duplicate values"
            )
        if f.domain:
            bad = out[f.name][~out[f.name].map(lambda v, d=f.domain: schema.domain_ok(d, v))]
            if len(bad):
                errs.append(
                    f"{f.name}: {len(bad)} values outside {f.domain}: "
                    f"{sorted(map(str, set(bad)))[:5]}"
                )
    if errs:
        raise SchemaError(f"{ldef.name}: " + "; ".join(errs))
    order = [f.name for f in fields if f.name in out.columns]
    rest = [c for c in out.columns if c not in order and c != geom_col]
    cols = order + rest + ([geom_col] if geom_col else [])
    return out[cols]
