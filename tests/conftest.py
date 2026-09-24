"""Shared test fixtures. The fixture market is SYNTHETIC — NOT REAL DATA."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from parkiq.config import ResolvedConfig, load_config
from parkiq.runner import RunContext, open_run, run_steps

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fixture_market"
FIXTURE_YAML = FIXTURE_DIR / "fixture.yaml"


@pytest.fixture(scope="session")
def fixture_cfg() -> ResolvedConfig:
    """Resolved fixture config."""
    return load_config(FIXTURE_YAML)


@pytest.fixture(scope="session")
def m1_run(tmp_path_factory: pytest.TempPathFactory, fixture_cfg: ResolvedConfig) -> RunContext:
    """One full M1 run (schema → qaqc) of the fixture, shared by read-only tests."""
    out = tmp_path_factory.mktemp("runs")
    ctx = open_run(fixture_cfg, run_id="20260101_0000_fixture_Balanced", out=out)
    run_steps(ctx, ["schema", "setup", "ingest", "qaqc"])
    return ctx


def write_variant(tmp_path: Path, edit: dict[str, object]) -> Path:
    """Copy fixture.yaml next to the fixture data with a nested-key edit; return its path.

    ``edit`` maps dotted paths to new values; a value of ``...`` deletes the key.
    """
    data = yaml.safe_load(FIXTURE_YAML.read_text(encoding="utf-8"))
    for dotted, val in edit.items():
        cur = data
        # provenance keys are literal dotted strings ("site.max_slope_pct")
        parts = (
            ["provenance", dotted.split(".", 1)[1]]
            if dotted.startswith("provenance.")
            else dotted.split(".")
        )
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        if val is ...:
            cur.pop(parts[-1], None)
        else:
            cur[parts[-1]] = val
    p = FIXTURE_DIR / f"_variant_{tmp_path.name}.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


@pytest.fixture
def variant(tmp_path: Path) -> Iterator[object]:
    """Factory for edited fixture configs; files are removed after the test."""
    made: list[Path] = []

    def _make(edit: dict[str, object]) -> Path:
        p = write_variant(tmp_path, edit)
        made.append(p)
        return p

    yield _make
    for p in made:
        p.unlink(missing_ok=True)


@pytest.fixture
def fresh_out(tmp_path: Path) -> Iterator[Path]:
    """Empty output root for runs that mutate state."""
    out = tmp_path / "out"
    out.mkdir()
    yield out
    shutil.rmtree(out, ignore_errors=True)
