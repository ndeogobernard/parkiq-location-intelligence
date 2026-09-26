"""Generate the fixture market, SYNTHETIC: NOT REAL DATA.

A 1.5 × 1.5 km square placed in Lake Erie (UTM 17N) so it cannot be mistaken for a real place.
Every file mimics the *format* of its real source so adapters are exercised end to end, and every
file carries the label "SYNTHETIC: NOT REAL DATA" (column ``note``, GeoJSON ``name``, parquet
metadata, GTFS feed_info, GeoTIFF tag, GraphML graph attribute).

Designed to hit branches, not to look realistic (docs/ARCHITECTURE.md §5). Deterministic (seeded).

Run:  python tests/fixtures/fixture_market/make_fixture.py
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon, box

LABEL = "SYNTHETIC: NOT REAL DATA"
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
UTM = "EPSG:32617"
X0, Y0 = 400_000.0, 4_650_000.0  # grid origin (Lake Erie)
BLOCK = 125.0  # street spacing, m
NGRID = 21  # 21 x 21 street nodes → 2.5 km square
BX0, BY0, BSIZE = 400_500.0, 4_650_500.0, 1_500.0  # market boundary square
ROW = 10.0  # street right-of-way half-width, m
RNG = np.random.default_rng(20260924)
TO_LL = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)
TO_NAD83 = Transformer.from_crs(UTM, "EPSG:4269", always_xy=True)


def ll(x: float, y: float) -> tuple[float, float]:
    return TO_LL.transform(x, y)


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    d = json.loads(gdf.to_crs(4326).to_json(drop_id=True))
    d["name"] = LABEL
    path.write_text(json.dumps(d, indent=1), encoding="utf-8")


def boundary() -> None:
    g = gpd.GeoDataFrame(
        {"name": ["Fixture City"], "note": [LABEL]},
        geometry=[box(BX0, BY0, BX0 + BSIZE, BY0 + BSIZE)],
        crs=UTM,
    )
    write_geojson(g, DATA / "boundary.geojson")


def street_graph() -> None:
    """Walk graph in EPSG:4326 with metre lengths, exactly what OSMnx downloads look like."""
    g = nx.MultiDiGraph(crs="EPSG:4326", note=LABEL)
    nid = lambda i, j: 1_000_000 + i * 100 + j  # noqa: E731
    for i in range(NGRID):
        for j in range(NGRID):
            x, y = X0 + i * BLOCK, Y0 + j * BLOCK
            lon, lat = ll(x, y)
            g.add_node(nid(i, j), x=lon, y=lat, street_count=4)
    arterial_j = NGRID // 2
    eid = 0
    for i in range(NGRID):
        for j in range(NGRID):
            for di, dj in ((1, 0), (0, 1)):
                ii, jj = i + di, j + dj
                if ii >= NGRID or jj >= NGRID:
                    continue
                eid += 1
                hw = "primary" if (dj == 0 and j == arterial_j) else "residential"
                name = "Main St" if hw == "primary" else (f"{i + 1} Ave" if dj else f"{j + 1} St")
                a = LineString(
                    [ll(X0 + i * BLOCK, Y0 + j * BLOCK), ll(X0 + ii * BLOCK, Y0 + jj * BLOCK)]
                )
                for u, v, geom in (
                    (nid(i, j), nid(ii, jj), a),
                    (nid(ii, jj), nid(i, j), LineString(a.coords[::-1])),
                ):
                    g.add_edge(
                        u,
                        v,
                        key=0,
                        osmid=eid,
                        highway=hw,
                        name=name,
                        length=BLOCK,
                        oneway=False,
                        reversed=False,
                        geometry=geom,
                    )
    ox.save_graphml(g, DATA / "walk_graph.graphml")


def dem() -> None:
    """NAD83 geographic DEM ~1/3 arc-second, metres. 1% tilt east + an 8% ramp in the NE block."""
    minx, miny = TO_NAD83.transform(X0 - 200, Y0 - 200)
    maxx, maxy = TO_NAD83.transform(X0 + NGRID * BLOCK + 200, Y0 + NGRID * BLOCK + 200)
    res = 1 / 3 / 3600
    w, h = int((maxx - minx) / res) + 1, int((maxy - miny) / res) + 1
    tr = from_origin(minx, maxy, res, res)
    cols, rows = np.meshgrid(np.arange(w), np.arange(h))
    lon = minx + (cols + 0.5) * res
    lat = maxy - (rows + 0.5) * res
    back = Transformer.from_crs("EPSG:4269", UTM, always_xy=True)
    x, y = back.transform(lon, lat)
    z = 180.0 + 0.01 * (x - X0)
    steep = (x > BX0 + 1250) & (x < BX0 + 1500) & (y > BY0 + 1250) & (y < BY0 + 1500)
    z = np.where(steep, z + 0.08 * (y - (BY0 + 1250)), z).astype("float32")
    with rasterio.open(
        DATA / "dem.tif",
        "w",
        driver="GTiff",
        width=w,
        height=h,
        count=1,
        dtype="float32",
        crs="EPSG:4269",
        transform=tr,
        nodata=-9999.0,
    ) as ds:
        ds.write(z, 1)
        ds.update_tags(note=LABEL, units="metre")


def parcels_and_buildings() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """One or two parcels per block inside the boundary; special cases for screen branches."""
    rows, blds = [], []
    n = 0
    nb = int(BSIZE / BLOCK)
    for bi in range(nb):
        for bj in range(nb):
            x0 = BX0 + bi * BLOCK + ROW
            y0 = BY0 + bj * BLOCK + ROW
            size = BLOCK - 2 * ROW
            split = (bi + bj) % 3 == 0
            parts = (
                [
                    box(x0, y0, x0 + size / 2, y0 + size),
                    box(x0 + size / 2, y0, x0 + size, y0 + size),
                ]
                if split
                else [box(x0, y0, x0 + size, y0 + size)]
            )
            for p in parts:
                n += 1
                pid = f"FX-{n:04d}"
                luc = RNG.choice(
                    ["100", "400", "430", "500", "510", "680", "999"],
                    p=[0.15, 0.2, 0.1, 0.25, 0.1, 0.1, 0.1],
                )
                land = float(RNG.integers(80, 900) * 1000)
                impr = 0.0 if luc in ("100", "430") else float(RNG.integers(10, 3000) * 1000)
                owner = RNG.choice(
                    [
                        "SMITH JOHN",
                        "ACME HOLDINGS LLC",
                        "CITY OF FIXTURE",
                        "FIXTURE UNIVERSITY",
                        "MAPLE PARTNERS INC",
                        "",
                    ]
                )
                rows.append(
                    {
                        "PARCELID": pid,
                        "LUC": luc,
                        "LAND_VAL": land,
                        "BLDG_VAL": impr,
                        "OWNER": owner,
                        "ADDR": f"{n} Fixture Way",
                        "geometry": p,
                    }
                )
                if impr > 0:
                    c = p.centroid
                    s = min(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) * 0.35
                    blds.append(
                        {
                            "id": f"08b{n:012x}",
                            "height": float(RNG.integers(4, 40)),
                            "num_floors": int(RNG.integers(1, 10)),
                            "geometry": box(c.x - s, c.y - s, c.x + s, c.y + s),
                        }
                    )
    # irregular sliver (L-shape) and a duplicate multipart parcel id
    n += 1
    rows.append(
        {
            "PARCELID": f"FX-{n:04d}",
            "LUC": "100",
            "LAND_VAL": 5000.0,
            "BLDG_VAL": 0.0,
            "OWNER": "",
            "ADDR": "sliver",
            "geometry": Polygon(
                [
                    (BX0 + 2, BY0 + 2),
                    (BX0 + 60, BY0 + 2),
                    (BX0 + 60, BY0 + 6),
                    (BX0 + 6, BY0 + 6),
                    (BX0 + 6, BY0 + 60),
                    (BX0 + 2, BY0 + 60),
                ]
            ),
        }
    )
    rows.append(
        {**rows[0], "geometry": box(BX0 + 1, BY0 + 1, BX0 + 2, BY0 + 2)}
    )  # 2nd part of FX-0001
    p = gpd.GeoDataFrame(rows, crs=UTM)
    p["note"] = LABEL
    b = gpd.GeoDataFrame(blds, crs=UTM)
    return p, b


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    boundary()
    street_graph()
    dem()

    parcels, bldgs = parcels_and_buildings()
    parcels[["PARCELID", "note", "geometry"]].to_file(DATA / "parcels.gpkg", engine="pyogrio")
    cama = (
        parcels.drop(columns="geometry")
        .drop_duplicates("PARCELID")
        .rename(columns={"PARCELID": "PARCEL_ID"})
    )
    cama["YRBUILT"] = np.where(cama["BLDG_VAL"] > 0, RNG.integers(1920, 2020, len(cama)), None)
    cama.to_csv(DATA / "cama.csv", index=False)
    pd.DataFrame(
        [
            ("100", "Vacant", "N"),
            ("400", "Commercial", "Y"),
            ("430", "SurfaceParking", "Y"),
            ("500", "Residential", "N"),
            ("510", "Residential", "N"),
            ("680", "Institutional", "N"),
        ],
        columns=["county_code", "land_use_class", "auto_oriented_commercial"],
    ).assign(note=LABEL).to_csv(
        DATA / "landuse_xwalk.csv", index=False
    )  # 999 left unmatched on purpose

    b4326 = bldgs.to_crs(4326)
    b4326["sources"] = None
    b4326.to_parquet(DATA / "overture_buildings.parquet")
    _label_parquet(DATA / "overture_buildings.parquet")

    cats = ["restaurant", "bar", "coffee_shop", "clothing_store", "hotel", "hospital", "college"]
    pl = []
    for k in range(30):
        x, y = BX0 + RNG.uniform(50, 1450), BY0 + RNG.uniform(50, 1450)
        c = cats[k % len(cats)]
        pl.append(
            {
                "id": f"08f{k:013x}",
                "names": {"primary": f"Place {k}"},
                "categories": {"primary": c, "alternate": ["eat_and_drink"]},
                "confidence": round(float(RNG.uniform(0.3, 0.99)), 3),
                "brand": None,
                "geometry": Point(ll(x, y)),
            }
        )
    gpd.GeoDataFrame(pl, crs=4326).to_parquet(DATA / "overture_places.parquet")
    _label_parquet(DATA / "overture_places.parquet")

    poi = []
    kinds = [
        ("amenity", "restaurant"),
        ("amenity", "bar"),
        ("shop", "clothes"),
        ("tourism", "hotel"),
        ("leisure", "stadium"),
        ("amenity", "theatre"),
        ("amenity", "school"),
    ]  # school is not in the tag query → filtered out
    for k in range(21):
        key, val = kinds[k % len(kinds)]
        x, y = BX0 + RNG.uniform(50, 1450), BY0 + RNG.uniform(50, 1450)
        geom = Point(x, y) if key != "leisure" else box(x - 60, y - 40, x + 60, y + 40)
        poi.append(
            {
                "element": "node" if key != "leisure" else "way",
                "id": 5_000 + k,
                "name": f"OSM {val} {k}",
                key: val,
                "rooms": "120" if val == "hotel" else None,
                "capacity": "8000" if val == "stadium" else None,
                "geometry": geom,
            }
        )
    pg = gpd.GeoDataFrame(poi, crs=UTM)
    pg["note"] = LABEL
    write_geojson(pg, DATA / "osm_poi.geojson")

    pk = []
    for k in range(20):
        x, y = BX0 + RNG.uniform(50, 1450), BY0 + RNG.uniform(50, 1450)
        kind = ["surface", "multi-storey", "street_side", "surface"][k % 4]
        geom = box(x - 30, y - 20, x + 30, y + 20) if k % 5 else Point(x, y)
        pk.append(
            {
                "element": "way" if k % 5 else "node",
                "id": 9_000 + k,
                "amenity": "parking",
                "parking": kind,
                "name": f"Lot {k}" if k % 3 else None,
                "capacity": str(int(RNG.integers(20, 400))) if k % 2 else None,
                "fee": "yes" if k % 4 else "no",
                "access": "private" if k % 7 == 0 else "yes",
                "operator": "FixturePark" if k % 2 else None,
                "building:levels": "4" if kind == "multi-storey" else None,
                "geometry": geom,
            }
        )
    kg = gpd.GeoDataFrame(pk, crs=UTM)
    kg["note"] = LABEL
    write_geojson(kg, DATA / "osm_parking.geojson")

    # LODES WAC + crosswalk (5 of 30 blocks fall outside the study area on purpose)
    wac, xw = [], []
    for k in range(30):
        inside = k < 25
        x = BX0 + RNG.uniform(0, 1500) if inside else X0 - 5_000
        y = BY0 + RNG.uniform(0, 1500) if inside else Y0 - 5_000
        geo = f"99999{k:010d}"
        sectors = {f"CNS{i:02d}": int(RNG.integers(0, 60)) for i in range(1, 21)}
        wac.append(
            {
                "w_geocode": geo,
                "C000": sum(sectors.values()),
                **sectors,
                "createdate": "20260101",
                "note": LABEL,
            }
        )
        lon, lat = ll(x, y)
        xw.append(
            {
                "tabblk2020": geo,
                "st": "99",
                "stusps": "ZZ",
                "blklatdd": lat,
                "blklondd": lon,
                "note": LABEL,
            }
        )
    pd.DataFrame(wac).to_csv(DATA / "zz_wac_S000_JT00_2023.csv", index=False)
    pd.DataFrame(xw).to_csv(DATA / "zz_xwalk.csv", index=False)

    # ACS: four block groups (quadrants) + one outside; one sentinel value
    bgs, acs = [], []
    half = (NGRID - 1) * BLOCK / 2
    for q, (qx, qy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
        gid = f"99999000100{q + 1}"
        bgs.append(
            {
                "GEOID": gid,
                "geometry": box(
                    X0 + qx * half, Y0 + qy * half, X0 + (qx + 1) * half, Y0 + (qy + 1) * half
                ),
            }
        )
    bgs.append(
        {"GEOID": "999990002001", "geometry": box(X0 - 9000, Y0 - 9000, X0 - 8000, Y0 - 8000)}
    )
    for b in bgs:
        w = int(RNG.integers(200, 900))
        acs.append(
            {
                "GEOID": b["GEOID"],
                "NAME": LABEL,
                "B01003_001E": int(RNG.integers(500, 3000)),
                "B08301_001E": w,
                "B08301_002E": int(w * RNG.uniform(0.5, 0.9)),
                "B25024_001E": 800,
                "B25024_006E": 50,
                "B25024_007E": 40,
                "B25024_008E": 30,
                "B25024_009E": 20,
                "B25044_001E": 700,
                "B25044_003E": 10,
                "B25044_010E": -666666666 if b["GEOID"].endswith("4") else 60,
            }
        )
    pd.DataFrame(acs).to_csv(DATA / "acs_bg.csv", index=False)
    bg = gpd.GeoDataFrame(bgs, crs=UTM)
    bg["note"] = LABEL
    write_geojson(bg, DATA / "tiger_bg.geojson")

    gtfs()

    def pt(x: float, y: float) -> tuple[float, float]:
        return ll(BX0 + x, BY0 + y)

    lon, lat = pt(700, 800)
    pd.DataFrame(
        [
            {
                "venue_id": "V1",
                "name": "Fixture Arena",
                "lat": lat,
                "lon": lon,
                "seats": 8000,
                "events_per_year": 90,
                "event_calendar_source": "analyst",
                "note": LABEL,
            }
        ]
    ).to_csv(DATA / "venues.csv", index=False)
    lon, lat = pt(300, 1200)
    lon2, lat2 = pt(-4000, -4000)
    pd.DataFrame(
        [
            {
                "ID": "H1",
                "NAME": "Fixture General",
                "BEDS": 350,
                "LATITUDE": lat,
                "LONGITUDE": lon,
                "note": LABEL,
            },
            {
                "ID": "H2",
                "NAME": "Outside Clinic",
                "BEDS": -999,
                "LATITUDE": lat2,
                "LONGITUDE": lon2,
                "note": LABEL,
            },
        ]
    ).to_csv(DATA / "hospitals.csv", index=False)
    lon, lat = pt(1100, 300)
    pd.DataFrame(
        [
            {
                "UNITID": "999001",
                "INSTNM": "Fixture University",
                "LATITUDE": lat,
                "LONGITUD": lon,
                "note": LABEL,
            }
        ]
    ).to_csv(DATA / "ipeds_hd.csv", index=False)
    pd.DataFrame(
        [
            {"UNITID": "999001", "EFFYLEV": 1, "EFYTOTLT": 12000, "note": LABEL},
            {"UNITID": "999001", "EFFYLEV": 2, "EFYTOTLT": 9000, "note": LABEL},
        ]
    ).to_csv(DATA / "ipeds_effy.csv", index=False)
    aadt = gpd.GeoDataFrame(
        [
            {"STATION_ID": f"A{k}", "AADT": 8000 + 1500 * k, "YEAR": 2025, "ROUTE": "Main St"}
            for k in range(4)
        ],
        geometry=[Point(X0 + 600 + 350 * k, Y0 + (NGRID // 2) * BLOCK) for k in range(4)],
        crs=UTM,
    )
    aadt["note"] = LABEL
    write_geojson(aadt, DATA / "aadt.geojson")
    flood = gpd.GeoDataFrame(
        [
            {"FLD_ZONE": "AE", "ZONE_SUBTY": "FLOODWAY", "SFHA_TF": "T"},
            {"FLD_ZONE": "AE", "ZONE_SUBTY": None, "SFHA_TF": "T"},
            {"FLD_ZONE": "X", "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD", "SFHA_TF": "F"},
        ],
        geometry=[
            box(BX0 + 130, BY0, BX0 + 240, BY0 + 400),
            box(BX0 + 240, BY0, BX0 + 380, BY0 + 400),
            box(BX0 + 380, BY0, BX0 + 600, BY0 + 400),
        ],
        crs=UTM,
    )
    flood["note"] = LABEL
    write_geojson(flood, DATA / "nfhl.geojson")
    lon, lat = pt(900, 900)
    lon2, lat2 = pt(200, 700)
    pd.DataFrame(
        [
            {
                "REGISTRY_ID": "E1",
                "PRIMARY_NAME": "Old Plating Works",
                "PGM_SYS_ACRNM": "ACRES",
                "LATITUDE83": lat,
                "LONGITUDE83": lon,
                "note": LABEL,
            },
            {
                "REGISTRY_ID": "E2",
                "PRIMARY_NAME": "Dry Cleaner",
                "PGM_SYS_ACRNM": "RCRAINFO",
                "LATITUDE83": lat2,
                "LONGITUDE83": lon2,
                "note": LABEL,
            },
        ]
    ).to_csv(DATA / "epa_sites.csv", index=False)
    (HERE / "README.md").write_text(
        f"# Fixture market, {LABEL}\n\n"
        "Generated by `make_fixture.py` (seeded). Lake Erie, UTM 17N.\n"
        "Formats mimic the real sources; values are invented to exercise code paths.\n"
        "Never used by a real market config.\n",
        encoding="utf-8",
    )
    print("fixture written to", DATA)


def gtfs() -> None:
    """Stops A (every 10 min 07–09), B (every 30 min), C (off-peak only), parent station P."""

    def pt(x: float, y: float) -> tuple[float, float]:
        return ll(BX0 + x, BY0 + y)

    stops = [
        ("P", "Central Station", *pt(750, 750)[::-1], "1"),
        ("A", "Main & 5th", *pt(750, 740)[::-1], "0"),
        ("B", "Main & 10th", *pt(1300, 740)[::-1], "0"),
        ("C", "Lakeview", *pt(200, 1400)[::-1], "0"),
    ]
    files: dict[str, str] = {}
    files["agency.txt"] = (
        "agency_id,agency_name,agency_url,agency_timezone\nFX,Fixture Transit,https://example.invalid,America/New_York\n"
    )
    files["feed_info.txt"] = (
        f"feed_publisher_name,feed_publisher_url,feed_lang\n{LABEL},https://example.invalid,en\n"
    )
    files["stops.txt"] = "stop_id,stop_name,stop_lat,stop_lon,location_type\n" + "".join(
        f"{s},{n},{la:.7f},{lo:.7f},{t}\n" for s, n, la, lo, t in stops
    )
    files["routes.txt"] = "route_id,agency_id,route_short_name,route_type\nR1,FX,1,3\nR2,FX,2,3\n"
    files["calendar.txt"] = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WK,1,1,1,1,1,0,0,20260101,20271231\nWE,0,0,0,0,0,1,1,20260101,20271231\n"
    )
    files["calendar_dates.txt"] = "service_id,date,exception_type\nWK,20261126,2\n"
    trips, st = (
        ["route_id,service_id,trip_id\n"],
        ["trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"],
    )
    t = 0
    for m in range(6 * 60 + 30, 10 * 60, 10):  # R1 via A every 10 min
        t += 1
        trips.append(f"R1,WK,T{t}\n")
        st.append(f"T{t},{m // 60:02d}:{m % 60:02d}:00,{m // 60:02d}:{m % 60:02d}:00,A,1\n")
    for m in range(7 * 60, 9 * 60, 30):  # R2 via B every 30 min
        t += 1
        trips.append(f"R2,WK,T{t}\n")
        st.append(f"T{t},{m // 60:02d}:{m % 60:02d}:00,{m // 60:02d}:{m % 60:02d}:00,B,1\n")
    for m in (13 * 60, 25 * 60 + 15):  # C off-peak incl. after-midnight time
        t += 1
        trips.append(f"R2,WK,T{t}\n")
        st.append(f"T{t},{m // 60:02d}:{m % 60:02d}:00,{m // 60:02d}:{m % 60:02d}:00,C,1\n")
    t += 1
    trips.append(f"R1,WE,T{t}\n")
    st.append(f"T{t},08:00:00,08:00:00,A,1\n")  # weekend trip must not count on a weekday
    files["trips.txt"] = "".join(trips)
    files["stop_times.txt"] = "".join(st)
    with zipfile.ZipFile(DATA / "gtfs.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)


def _label_parquet(path: Path) -> None:
    import pyarrow.parquet as pq

    t = pq.read_table(path)
    md = dict(t.schema.metadata or {})
    md[b"note"] = LABEL.encode()
    pq.write_table(t.replace_schema_metadata(md), path)


if __name__ == "__main__":
    main()
