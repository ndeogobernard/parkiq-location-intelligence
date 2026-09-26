"""Tool 1 BuildSchema (full), schema-diff, ERD and data dictionary — all from ``schema.yaml``.

* :func:`build_schema` creates every feature class and table (empty) in a GeoPackage, writes the
  coded/range domains as GeoPackage schema-extension constraints (``gpkg_data_columns`` +
  ``gpkg_data_column_constraints``; GDAL/QGIS read them as field domains), and records the
  relationship classes and subtypes in ``_ParkIQ_Relationships`` / ``_ParkIQ_Subtypes``.
* :func:`schema_diff` compares a GeoPackage with ``schema.yaml`` and lists every difference.
* :func:`erd_drawio`, :func:`erd_png` and :func:`data_dictionary` generate ``docs/ERD.*`` and
  ``docs/DataDictionary.md``; the docs are never edited by hand.

Relationship classes are not a GeoPackage concept ArcGIS understands; they become real
relationship classes in the file-geodatabase export (M7) (ADR-0060).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS

from parkiq.schema import FieldDef, LayerDef, Schema

WGS84 = CRS.from_epsg(4326)
RELATIONSHIPS_TABLE = "_ParkIQ_Relationships"
SUBTYPES_TABLE = "_ParkIQ_Subtypes"
DATASET_ORDER = ("Reference", "Cadastral", "Demand", "Supply", "Analysis", "Results")

# GeoPackage column types GDAL may use for each schema type.
_COMPAT = {
    "TEXT": {"TEXT"},
    "JSON": {"TEXT", "JSON"},
    "INTEGER": {"INTEGER", "MEDIUMINT", "SMALLINT", "TINYINT", "INT"},
    "BOOLEAN": {"BOOLEAN", "INTEGER", "MEDIUMINT", "SMALLINT", "TINYINT", "INT"},
    "REAL": {"REAL", "DOUBLE", "FLOAT"},
    "DATETIME": {"DATETIME", "TEXT", "DATE"},
}

_DDL = (
    """CREATE TABLE IF NOT EXISTS gpkg_extensions (table_name TEXT, column_name TEXT,
    extension_name TEXT NOT NULL, definition TEXT NOT NULL, scope TEXT NOT NULL,
    CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name))""",
    """CREATE TABLE IF NOT EXISTS gpkg_data_columns (table_name TEXT NOT NULL,
    column_name TEXT NOT NULL, name TEXT, title TEXT, description TEXT, mime_type TEXT,
    constraint_name TEXT, CONSTRAINT pk_gdc PRIMARY KEY (table_name, column_name),
    CONSTRAINT gdc_tn UNIQUE (table_name, name))""",
    """CREATE TABLE IF NOT EXISTS gpkg_data_column_constraints (constraint_name TEXT NOT NULL,
    constraint_type TEXT NOT NULL, value TEXT, min NUMERIC, min_is_inclusive BOOLEAN,
    max NUMERIC, max_is_inclusive BOOLEAN, description TEXT,
    CONSTRAINT gdcc_ntv UNIQUE (constraint_name, constraint_type, value))""",
)
_EXT = "http://www.geopackage.org/spec/#extension_schema"


# --------------------------------------------------------------------------- BuildSchema


def layer_fields(schema: Schema, ldef: LayerDef) -> list[FieldDef]:
    """Lineage + own fields for feature classes; own fields only for attribute tables."""
    if ldef.is_table:
        return list(ldef.fields)
    return list(schema.lineage) + list(ldef.fields)


def _empty_column(f: FieldDef) -> pd.Series:
    if f.type in ("INTEGER", "BOOLEAN"):
        return pd.Series([], dtype="Int64")
    if f.type == "REAL":
        return pd.Series([], dtype="float64")
    if f.type == "DATETIME":
        return pd.Series([], dtype="datetime64[ns, UTC]")
    return pd.Series([], dtype="object")


def layer_crs(ldef: LayerDef, analysis_crs: CRS) -> CRS | None:
    """CRS a layer must be stored in (None for attribute tables)."""
    if not ldef.is_spatial:
        return None
    return WGS84 if ldef.crs == "wgs84" else analysis_crs


def create_empty(gpkg: Path, schema: Schema, ldef: LayerDef, analysis_crs: CRS) -> None:
    """Create one empty layer/table with the schema's columns and types."""
    cols = {f.name: _empty_column(f) for f in layer_fields(schema, ldef)}
    df = pd.DataFrame(cols)
    if ldef.is_spatial:
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.GeoSeries([], crs=layer_crs(ldef, analysis_crs)), crs=None
        )
        gtype = "Unknown" if ldef.geometry in ("Geometry", None) else ldef.geometry
        pyogrio.write_dataframe(gdf, gpkg, layer=ldef.name, driver="GPKG", geometry_type=gtype)
    else:
        pyogrio.write_dataframe(df, gpkg, layer=ldef.name, driver="GPKG")


def _existing(gpkg: Path) -> set[str]:
    if not gpkg.exists():
        return set()
    return {str(r[0]) for r in pyogrio.list_layers(gpkg)}


def apply_constraints(gpkg: Path, schema: Schema, names: list[str] | None = None) -> None:
    """(Re)write domain constraints and column descriptions for the given layers (default all).

    Idempotent; called after every write because GDAL drops a table's ``gpkg_data_columns``
    rows when it replaces the table.
    """
    present = _existing(gpkg)
    targets = [n for n in (names or list(schema.layers)) if n in present and n in schema.layers]
    with closing(sqlite3.connect(gpkg)) as con, con:
        for ddl in _DDL:
            con.execute(ddl)
        for t in ("gpkg_data_columns", "gpkg_data_column_constraints"):
            con.execute(
                "INSERT OR IGNORE INTO gpkg_extensions VALUES (?, NULL, 'gpkg_schema', ?,"
                " 'read-write')",
                (t, _EXT),
            )
        for dname, dom in schema.domains.items():
            con.execute(
                "DELETE FROM gpkg_data_column_constraints WHERE constraint_name = ?", (dname,)
            )
            if dom["type"] == "coded":
                con.executemany(
                    "INSERT INTO gpkg_data_column_constraints (constraint_name, constraint_type,"
                    " value, description) VALUES (?, 'enum', ?, ?)",
                    [(dname, str(v), str(v)) for v in dom["values"]],
                )
            else:
                con.execute(
                    "INSERT INTO gpkg_data_column_constraints (constraint_name, constraint_type,"
                    " min, min_is_inclusive, max, max_is_inclusive, description)"
                    " VALUES (?, 'range', ?, 1, ?, 1, ?)",
                    (dname, dom["min"], dom["max"], f"{dom['min']}–{dom['max']}"),
                )
        for name in targets:
            ldef = schema.layers[name]
            con.execute("DELETE FROM gpkg_data_columns WHERE table_name = ?", (name,))
            con.executemany(
                "INSERT INTO gpkg_data_columns (table_name, column_name, name, title, description,"
                " constraint_name) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (name, f.name, f.name, f.name, f.desc or None, f.domain)
                    for f in layer_fields(schema, ldef)
                ],
            )


def relationships_frame(schema: Schema) -> pd.DataFrame:
    """Relationship classes as a table."""
    cols = ["name", "origin", "destination", "cardinality", "origin_key", "destination_key", "note"]
    return pd.DataFrame(
        [{c: r.get(c) for c in cols} for r in schema.relationships], columns=cols
    ).astype("object")


def subtypes_frame(schema: Schema) -> pd.DataFrame:
    """Subtype definitions (layer, field, domain, code)."""
    rows = []
    for ldef in schema.layers.values():
        if not ldef.subtype_field:
            continue
        f = next(x for x in ldef.fields if x.name == ldef.subtype_field)
        values = schema.domains[f.domain]["values"] if f.domain else []
        rows += [
            {
                "layer": ldef.name,
                "subtype_field": f.name,
                "domain": f.domain,
                "code": i,
                "subtype": v,
            }
            for i, v in enumerate(values, start=1)
        ]
    return pd.DataFrame(rows, columns=["layer", "subtype_field", "domain", "code", "subtype"])


def build_schema(
    gpkg: Path, schema: Schema, analysis_crs: CRS, overwrite: bool = False
) -> dict[str, int]:
    """Create every schema layer/table that is missing (or all, with ``overwrite``).

    Existing layers holding data are left untouched unless ``overwrite`` is set.

    Returns:
        Counts: ``created``, ``existing``, ``relationships``, ``subtypes``.
    """
    gpkg = Path(gpkg)
    gpkg.parent.mkdir(parents=True, exist_ok=True)
    if not gpkg.exists() and not overwrite:
        # new GeoPackage: copy a per-schema/CRS template (creating 60 layers takes seconds)
        shutil.copyfile(_template(schema, analysis_crs), gpkg)
        n = len(schema.layers)
        return {
            "created": n,
            "existing": 0,
            "relationships": len(schema.relationships),
            "subtypes": len(subtypes_frame(schema)),
        }
    have = _existing(gpkg)
    created = 0
    for ldef in schema.layers.values():
        if ldef.name in have and not overwrite:
            continue
        create_empty(gpkg, schema, ldef, analysis_crs)
        created += 1
    rel = relationships_frame(schema)
    sub = subtypes_frame(schema)
    pyogrio.write_dataframe(rel, gpkg, layer=RELATIONSHIPS_TABLE, driver="GPKG")
    pyogrio.write_dataframe(sub.astype("object"), gpkg, layer=SUBTYPES_TABLE, driver="GPKG")
    apply_constraints(gpkg, schema)
    return {
        "created": created,
        "existing": len(schema.layers) - created,
        "relationships": len(rel),
        "subtypes": len(sub),
    }


def _template(schema: Schema, analysis_crs: CRS) -> Path:
    """Empty GeoPackage for this schema file + CRS, built once in the temp directory."""
    src = schema.path.read_bytes() if schema.path else schema.version.encode()
    key = hashlib.sha1(src + analysis_crs.to_wkt().encode()).hexdigest()[:16]
    tpl = Path(tempfile.gettempdir()) / "parkiq_schema_templates" / f"{key}.gpkg"
    if not tpl.exists():
        tpl.parent.mkdir(parents=True, exist_ok=True)
        tmp = tpl.with_name(f"{key}.{os.getpid()}.building.gpkg")
        tmp.unlink(missing_ok=True)
        build_schema(tmp, schema, analysis_crs, overwrite=True)
        os.replace(tmp, tpl)
    return tpl


# --------------------------------------------------------------------------- schema-diff


def schema_diff(gpkg: Path, schema: Schema, analysis_crs: CRS) -> list[str]:
    """Every difference between a GeoPackage and ``schema.yaml`` (empty list = conforms).

    Checks: layer present; geometry type and CRS; every schema column present with a
    compatible type; no extra columns (raw layers exempt); domain constraints attached and
    their values; relationship and subtype tables.
    """
    gpkg = Path(gpkg)
    if not gpkg.exists():
        return [f"{gpkg}: file not found"]
    out: list[str] = []
    have = _existing(gpkg)
    with closing(sqlite3.connect(gpkg)) as con, con:
        geom = {
            r[0]: (r[1], r[2], r[3])
            for r in con.execute(
                "SELECT table_name, column_name, geometry_type_name, srs_id"
                " FROM gpkg_geometry_columns"
            )
        }
        try:
            dcols = {
                (r[0], r[1]): r[2]
                for r in con.execute(
                    "SELECT table_name, column_name, constraint_name FROM gpkg_data_columns"
                )
            }
            cons: dict[str, set[str]] = {}
            ranges: dict[str, tuple[float, float]] = {}
            for name, ctype, value, mn, mx in con.execute(
                "SELECT constraint_name, constraint_type, value, min, max"
                " FROM gpkg_data_column_constraints"
            ):
                if ctype == "enum":
                    cons.setdefault(name, set()).add(value)
                elif ctype == "range":
                    ranges[name] = (float(mn), float(mx))
        except sqlite3.OperationalError:
            dcols, cons, ranges = {}, {}, {}
            out.append("GeoPackage schema extension tables missing (no domain constraints)")
        for dname, dom in schema.domains.items():
            if dom["type"] == "coded" and cons.get(dname) != {str(v) for v in dom["values"]}:
                out.append(f"domain {dname}: constraint values differ or missing")
            if dom["type"] == "range" and ranges.get(dname) != (
                float(dom["min"]),
                float(dom["max"]),
            ):
                out.append(f"domain {dname}: range constraint differs or missing")
        for ldef in schema.layers.values():
            n = ldef.name
            if n not in have:
                out.append(f"{n}: missing")
                continue
            if ldef.is_spatial:
                g = geom.get(n)
                if g is None:
                    out.append(f"{n}: not registered as a feature table")
                else:
                    want = "GEOMETRY" if ldef.geometry == "Geometry" else str(ldef.geometry).upper()
                    if g[1].upper() != want:
                        out.append(f"{n}: geometry {g[1]} != {want}")
                    crs = layer_crs(ldef, analysis_crs)
                    epsg = crs.to_epsg() if crs else None
                    if epsg and g[2] != epsg:
                        out.append(f"{n}: srs_id {g[2]} != EPSG:{epsg}")
            info = {
                r[1]: str(r[2]).upper().split("(")[0]
                for r in con.execute(f'PRAGMA table_info("{n}")')
            }
            geom_col = geom[n][0] if n in geom else None
            fields = layer_fields(schema, ldef)
            for f in fields:
                if f.name not in info:
                    out.append(f"{n}.{f.name}: column missing")
                elif info[f.name] not in _COMPAT[f.type]:
                    out.append(f"{n}.{f.name}: type {info[f.name]} not compatible with {f.type}")
                if f.domain and dcols.get((n, f.name)) != f.domain:
                    out.append(f"{n}.{f.name}: domain constraint {f.domain} not attached")
            if not ldef.raw:
                known = {f.name for f in fields} | {"fid", geom_col}
                extra = sorted(c for c in info if c not in known)
                if extra:
                    out.append(f"{n}: extra columns {extra}")
        for tname, frame in (
            (RELATIONSHIPS_TABLE, relationships_frame(schema)),
            (SUBTYPES_TABLE, subtypes_frame(schema)),
        ):
            if tname not in have:
                out.append(f"{tname}: missing")
                continue
            cnt = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            if cnt != len(frame):
                out.append(f"{tname}: {cnt} rows != {len(frame)} in schema.yaml")
    return out


# --------------------------------------------------------------------------- docs


def _grouped(schema: Schema) -> list[tuple[str, list[LayerDef]]]:
    groups: dict[str, list[LayerDef]] = {}
    for ldef in schema.layers.values():
        if ldef.raw:
            continue
        key = ldef.feature_dataset or "Tables"
        groups.setdefault(key, []).append(ldef)
    order = [*DATASET_ORDER, "Tables"]
    return [(k, groups[k]) for k in order if k in groups]


def _keys(schema: Schema) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    pk = {(ldef.name, f.name) for ldef in schema.layers.values() for f in ldef.fields if f.unique}
    fk = {
        (r["destination"], r["destination_key"])
        for r in schema.relationships
        if r["destination"] != "*"
    }
    return pk, fk


def _geom_label(ldef: LayerDef) -> str:
    return str(ldef.geometry) if ldef.is_spatial else "table"


def data_dictionary(schema: Schema) -> str:
    """Markdown data dictionary generated from ``schema.yaml``."""
    lines: list[str] = [
        "# ParkIQ data dictionary",
        "",
        f"Generated from `schema/schema.yaml` (version {schema.version}) by "
        "`parkiq schema-docs`. Do not edit by hand.",
        "",
        "Every feature class also carries the lineage fields "
        + ", ".join(f"`{f.name}` ({f.type}, {f.desc})" for f in schema.lineage)
        + ". Feature classes are stored in the market's analysis CRS; `Raw_*` snapshots in "
        "EPSG:4326. BOOLEAN is stored as 0/1, JSON as text.",
        "",
        "## Domains",
        "",
        "| Domain | Type | Values |",
        "|---|---|---|",
    ]
    for dname, dom in schema.domains.items():
        vals = (
            ", ".join(map(str, dom["values"]))
            if dom["type"] == "coded"
            else f"{dom['min']} – {dom['max']}"
        )
        lines.append(f"| `{dname}` | {dom['type']} | {vals} |")
    for group, layers in _grouped(schema):
        title = f"Feature dataset `{group}`" if group != "Tables" else "Standalone tables"
        lines += ["", f"## {title}"]
        for ldef in layers:
            crs = {"analysis": "analysis CRS", "wgs84": "EPSG:4326", "none": "—"}[ldef.crs]
            lines += ["", f"### `{ldef.name}`", "", ldef.desc or "", ""]
            lines.append(f"Geometry: {_geom_label(ldef)} · CRS: {crs}")
            if ldef.subtype_field:
                lines.append(f" · Subtypes by `{ldef.subtype_field}`")
            lines += [
                "",
                "| Field | Type | Null | Unique | Domain | Description |",
                "|---|---|---|---|---|---|",
            ]
            for f in ldef.fields:
                lines.append(
                    f"| `{f.name}` | {f.type} | {'yes' if f.nullable else 'no'} | "
                    f"{'yes' if f.unique else ''} | {f'`{f.domain}`' if f.domain else ''} | "
                    f"{f.desc} |"
                )
    lines += [
        "",
        "## Rasters",
        "",
        "| Raster | Dataset | File | Units | Description |",
        "|---|---|---|---|---|",
    ]
    for name, r in schema.rasters.items():
        lines.append(
            f"| `{name}` | {r.get('feature_dataset', '')} | `{r.get('file', '')}` | "
            f"{r.get('units', '')} | {r.get('desc', '')} |"
        )
    raw = [n for n, ldef in schema.layers.items() if ldef.raw]
    lines += [
        "",
        "## Raw snapshots",
        "",
        "Immutable, EPSG:4326, source attributes as delivered: "
        + ", ".join(f"`{n}`" for n in raw)
        + ".",
    ]
    lines += [
        "",
        "## Relationship classes",
        "",
        "| Name | Origin | Destination | Cardinality | Keys | Note |",
        "|---|---|---|---|---|---|",
    ]
    for r in schema.relationships:
        dest = "every source-derived feature class" if r["destination"] == "*" else r["destination"]
        lines.append(
            f"| {r['name']} | `{r['origin']}` | {dest} | {r['cardinality']} | "
            f"`{r['origin_key']}` → `{r['destination_key']}` | {r.get('note', '') or ''} |"
        )
    lines += ["", "## Rules", ""]
    for kind, rules in schema.rules.items():
        for rule in rules:
            what = rule.get("field", "")
            lines.append(
                f"- {kind}: `{rule['layer']}`{('.' + what) if what else ''} — {rule['rule']}"
                + (f" (tolerance {rule['tolerance_ft']} ft)" if "tolerance_ft" in rule else "")
            )
    return "\n".join(lines) + "\n"


# ERD layout: one column per feature dataset.
_W, _ROW, _HEAD, _GAP_X, _GAP_Y = 250, 18, 26, 50, 30


def erd_layout(schema: Schema) -> dict[str, tuple[int, int, int, int]]:
    """Box (x, y, w, h) per entity: columns by feature dataset, tables last."""
    boxes: dict[str, tuple[int, int, int, int]] = {}
    x = 20
    for _group, layers in _grouped(schema):
        y = 60
        col_bottom_limit = 2600
        for ldef in layers:
            h = _HEAD + _ROW * max(1, len(ldef.fields))
            if y + h > col_bottom_limit:
                x += _W + _GAP_X
                y = 60
            boxes[ldef.name] = (x, y, _W, h)
            y += h + _GAP_Y
        x += _W + _GAP_X
    return boxes


def _field_label(schema: Schema, ldef: LayerDef, f: FieldDef) -> str:
    pk, fk = _keys(schema)
    tag = "PK " if (ldef.name, f.name) in pk else ("FK " if (ldef.name, f.name) in fk else "")
    dom = f" [{f.domain}]" if f.domain else ""
    return f"{tag}{f.name}: {f.type}{dom}"


def erd_drawio(schema: Schema) -> str:
    """draw.io (mxGraph) XML ERD generated from ``schema.yaml``."""
    boxes = erd_layout(schema)
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    title = (
        f"ParkIQ data model v{schema.version} — generated from schema/schema.yaml. "
        "All feature classes also carry source_id, run_id, load_ts. Raw_* snapshots omitted."
    )
    cells.append(
        f'<mxCell id="title" value="{escape(title)}" style="text;fontSize=14;fontStyle=1;'
        'align=left;" vertex="1" parent="1"><mxGeometry x="20" y="10" width="1400" height="30"'
        ' as="geometry"/></mxCell>'
    )
    colors = {
        "Reference": "#dae8fc",
        "Cadastral": "#d5e8d4",
        "Demand": "#fff2cc",
        "Supply": "#ffe6cc",
        "Analysis": "#f8cecc",
        "Results": "#e1d5e7",
    }
    for name, (x, y, w, h) in boxes.items():
        ldef = schema.layers[name]
        fill = colors.get(ldef.feature_dataset or "", "#f5f5f5")
        fds = f", {ldef.feature_dataset}" if ldef.feature_dataset else ""
        head = f"{name} ({_geom_label(ldef)}{fds})"
        cells.append(
            f'<mxCell id="{name}" value="{escape(head)}" style="swimlane;fontStyle=1;'
            f"childLayout=stackLayout;horizontal=1;startSize={_HEAD};fillColor={fill};"
            'horizontalStack=0;resizeParent=1;collapsible=0;html=0;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        for i, f in enumerate(ldef.fields):
            cells.append(
                f'<mxCell id="{name}.{f.name}" value="{escape(_field_label(schema, ldef, f))}" '
                'style="text;align=left;verticalAlign=middle;spacingLeft=4;fontSize=10;html=0;" '
                f'vertex="1" parent="{name}"><mxGeometry y="{_HEAD + i * _ROW}" width="{w}" '
                f'height="{_ROW}" as="geometry"/></mxCell>'
            )
    ends = {"1:1": ("ERmandOne", "ERmandOne"), "1:M": ("ERmandOne", "ERmany")}
    for r in schema.relationships:
        if r["destination"] == "*":
            continue
        s, t = ends.get(r["cardinality"], ("none", "none"))
        cells.append(
            f'<mxCell id="rel.{r["name"]}" value="{escape(r["cardinality"])}" '
            f'style="edgeStyle=entityRelationEdgeStyle;startArrow={s};endArrow={t};'
            'fontSize=9;html=0;" edge="1" parent="1" '
            f'source="{r["origin"]}" target="{r["destination"]}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    body = "".join(cells)
    return (
        '<mxfile host="parkiq" type="device"><diagram name="ParkIQ ERD" id="erd">'
        '<mxGraphModel dx="1600" dy="1200" grid="1" gridSize="10" guides="1" page="0">'
        f"<root>{body}</root></mxGraphModel></diagram></mxfile>\n"
    )


def erd_png(schema: Schema, path: Path) -> Path:
    """Render the same layout as a PNG with matplotlib."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    boxes = erd_layout(schema)
    maxx = max(x + w for x, _, w, _ in boxes.values()) + 20
    maxy = max(y + h for _, y, _, h in boxes.values()) + 20
    fig = plt.figure(figsize=(maxx / 100, maxy / 100), dpi=110)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, maxx)
    ax.set_ylim(maxy, 0)
    ax.axis("off")
    colors = {
        "Reference": "#dae8fc",
        "Cadastral": "#d5e8d4",
        "Demand": "#fff2cc",
        "Supply": "#ffe6cc",
        "Analysis": "#f8cecc",
        "Results": "#e1d5e7",
    }
    ax.text(
        20,
        30,
        f"ParkIQ data model v{schema.version} — generated from schema/schema.yaml "
        "(all feature classes also carry source_id, run_id, load_ts; Raw_* omitted)",
        fontsize=11,
        fontweight="bold",
        va="center",
    )
    for r in schema.relationships:
        if r["destination"] == "*":
            continue
        ox, oy, ow, _oh = boxes[r["origin"]]
        dx, dy, dw, _dh = boxes[r["destination"]]
        x0 = ox + ow if dx > ox else ox
        x1 = dx if dx > ox else dx + dw
        if dx == ox:
            x0, x1 = ox + ow, dx + dw
        ax.plot([x0, x1], [oy + _HEAD / 2, dy + _HEAD / 2], color="#555555", lw=0.8, zorder=0)
        ax.text(
            (x0 + x1) / 2,
            (oy + dy) / 2 + _HEAD / 2,
            r["cardinality"],
            fontsize=7,
            color="#333333",
            ha="center",
            backgroundcolor="white",
        )
    for name, (x, y, w, h) in boxes.items():
        ldef = schema.layers[name]
        fill = colors.get(ldef.feature_dataset or "", "#f5f5f5")
        ax.add_patch(Rectangle((x, y), w, h, facecolor="white", edgecolor="#333333", lw=0.8))
        ax.add_patch(Rectangle((x, y), w, _HEAD, facecolor=fill, edgecolor="#333333", lw=0.8))
        ax.text(
            x + 4,
            y + _HEAD / 2,
            f"{name} ({_geom_label(ldef)})",
            fontsize=8,
            fontweight="bold",
            va="center",
        )
        for i, f in enumerate(ldef.fields):
            ax.text(
                x + 4,
                y + _HEAD + i * _ROW + _ROW / 2,
                _field_label(schema, ldef, f),
                fontsize=6.5,
                va="center",
                family="monospace",
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def write_docs(schema: Schema, docs_dir: Path) -> dict[str, Path]:
    """Write ERD.drawio, ERD.png and DataDictionary.md into ``docs_dir``."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "drawio": docs_dir / "ERD.drawio",
        "png": docs_dir / "ERD.png",
        "dictionary": docs_dir / "DataDictionary.md",
    }
    out["drawio"].write_text(erd_drawio(schema), encoding="utf-8")
    out["dictionary"].write_text(data_dictionary(schema), encoding="utf-8")
    erd_png(schema, out["png"])
    return out


def describe(schema: Schema) -> dict[str, Any]:
    """Counts for logs/tests."""
    return {
        "feature_classes": sum(1 for x in schema.layers.values() if x.is_spatial and not x.raw),
        "raw_layers": sum(1 for x in schema.layers.values() if x.raw),
        "tables": sum(1 for x in schema.layers.values() if x.is_table),
        "domains": len(schema.domains),
        "relationships": len(schema.relationships),
    }
