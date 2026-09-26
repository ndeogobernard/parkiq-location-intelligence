"""Live endpoint smoke tests, opt-in: ``pytest -m network``.

They only check that each [VERIFY] endpoint answers in the expected shape; passing one is evidence
toward closing the matching docs/VERIFY.md item, not a closure by itself.
"""

from __future__ import annotations

import pytest
import requests

import parkiq  # noqa: F401  (OS trust store for HTTPS)

pytestmark = pytest.mark.network
TIMEOUT = 60


def test_tiger_county_url_exists() -> None:  # V-33
    r = requests.head(
        "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip",
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    assert r.status_code == 200


def test_acs_block_group_api() -> None:  # V-15, the API now requires a key
    import os

    key = os.environ.get("CENSUS_API_KEY")
    params = {
        "get": "NAME,B01003_001E,B08301_002E",
        "for": "block group:*",
        "in": "state:39 county:049",
    }
    if not key:
        r = requests.get(
            "https://api.census.gov/data/2023/acs/acs5", params=params, timeout=TIMEOUT
        )
        assert "missing_key" in r.url  # documents the behaviour the adapter reports
        pytest.skip("CENSUS_API_KEY not set")
    r = requests.get(
        "https://api.census.gov/data/2023/acs/acs5", params={**params, "key": key}, timeout=TIMEOUT
    )
    assert r.status_code == 200
    assert r.json()[0][:3] == ["NAME", "B01003_001E", "B08301_002E"]


def test_tnm_dem_product_search() -> None:  # V-23
    r = requests.get(
        "https://tnmaccess.nationalmap.gov/api/v1/products",
        params={
            "datasets": "National Elevation Dataset (NED) 1/3 arc-second",
            "bbox": "-83.0,39.95,-82.98,39.97",
            "prodFormats": "GeoTIFF",
            "outputFormat": "JSON",
        },
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    assert any("downloadURL" in it for it in r.json().get("items", []))


def test_fema_nfhl_layer() -> None:  # V-21
    r = requests.get(
        "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28",
        params={"f": "json"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200
    fields = {f["name"] for f in r.json().get("fields", [])}
    assert {"FLD_ZONE", "ZONE_SUBTY", "SFHA_TF"} <= fields


def test_lodes_oh_crosswalk_head() -> None:  # V-14
    r = requests.head(
        "https://lehd.ces.census.gov/data/lodes/LODES8/oh/oh_xwalk.csv.gz",
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    assert r.status_code == 200
