"""M5 scoring and screen helpers: normalization, ranks, OAT, Dirichlet ranks, frontage, assembly.

Geometries here are small SYNTHETIC test shapes (tests only), not market data.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS
from shapely.geometry import LineString, box

from parkiq.score import composite_rank, normalize, oat_weights, ranks_matrix
from parkiq.screen import assemble, frontage

FT = CRS.from_epsg(3735)


def test_normalize_benefit_cost_and_winsor() -> None:
    x = np.arange(1, 101, dtype=float)
    s, note = normalize(x, "Benefit")
    assert note == "ok"
    assert s.min() == 0 and s.max() == 100
    assert s[0] == s[4] == 0  # winsorized below p5
    c, _ = normalize(x, "Cost")
    np.testing.assert_allclose(c, 100 - s)


def test_normalize_constant_missing_and_small_n() -> None:
    s, note = normalize(np.full(7, 3.0), "Benefit")
    assert note.startswith("zero variance") and (s == 50).all()
    s, note = normalize(np.full(5, np.nan), "Cost")
    assert note.startswith("no data") and (s == 50).all()
    s, note = normalize(np.array([1.0, np.nan, 3.0]), "Benefit")  # N < 20 still scales
    assert s[1] == 50 and s[0] == 0 and s[2] == 100 and "1 missing" in note


def test_composite_in_range_and_unique_ranks_with_id_tiebreak() -> None:
    scores = np.array([[50.0, 50.0], [50.0, 50.0], [100.0, 0.0]])
    w = np.array([0.5, 0.5])
    comp, rank = composite_rank(scores, w, np.array(["b", "a", "c"]))
    assert ((comp >= 0) & (comp <= 100)).all()
    assert sorted(rank) == [1, 2, 3]
    assert rank[1] < rank[0]  # tie on composite → id "a" before "b"


def test_oat_weights_sum_to_one() -> None:
    w = np.array([0.18, 0.14, 0.08, 0.12, 0.10, 0.08, 0.12, 0.08, 0.05, 0.05])
    for i in range(10):
        for f in (1.25, 0.75):
            w2 = oat_weights(w, i, f)
            assert w2.sum() == pytest.approx(1.0)
            assert w2[i] == pytest.approx(w[i] * f)


def test_dirichlet_ranks_reproducible_and_unique() -> None:
    rng = np.random.default_rng(1)
    s = rng.uniform(0, 100, size=(8, 10))
    ids = np.array([f"p{i}" for i in range(8)])
    d1 = np.random.default_rng(42).dirichlet(np.ones(10), 50)
    d2 = np.random.default_rng(42).dirichlet(np.ones(10), 50)
    r1, r2 = ranks_matrix(d1 @ s.T, ids), ranks_matrix(d2 @ s.T, ids)
    np.testing.assert_array_equal(r1, r2)
    assert all(sorted(row) == list(range(1, 9)) for row in r1)
    np.testing.assert_allclose(d1.sum(axis=1), 1.0)


def test_frontage_uses_positions_not_labels() -> None:
    # sites carry non-contiguous labels (as in the screen); a street runs along the south edge
    sites = gpd.GeoDataFrame(
        geometry=[box(0, 20, 100, 120), box(500, 20, 600, 120)], index=[7, 42], crs=FT
    )
    edges = gpd.GeoDataFrame(
        {"highway": ["residential", "service"], "name": ["A St", "Alley"]},
        geometry=[LineString([(-50, 0), (650, 0)]), LineString([(500, 200), (600, 200)])],
        crs=FT,
    )
    fr = frontage(sites, edges, 50.0)
    assert list(fr.index) == [7, 42]
    assert fr.loc[7, "frontage"] == pytest.approx(100 + 2 * 30, rel=0.05)  # south edge + side stubs
    assert not fr.loc[7, "corner"] and not fr.loc[7, "arterial"]


def test_assemble_same_owner_contiguous_only() -> None:
    parcels = gpd.GeoDataFrame(
        {"owner": ["ACME LLC", "Acme, LLC", "OTHER", "ACME LLC"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10), box(100, 0, 110, 10)],
        crs=FT,
    )
    lab = pd.Series(assemble(parcels))
    assert lab[0] == lab[1]  # touching, same normalized owner
    assert lab[2] != lab[0] and lab[3] != lab[0]  # other owner / not contiguous
