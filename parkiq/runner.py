"""Step registry, run folders, resume/idempotency and run artifacts (docs/ARCHITECTURE.md §2).

A run lives in ``<output_root>/<market>/<run_id>/``. Each step:

1. refuses to run if an upstream step has not succeeded, or if a config value it needs is null;
2. computes an input hash (config sections it reads + upstream hashes + code version + input
   file fingerprints) and skips when ``run_log.json`` already records success with that hash
   (unless ``force``);
3. writes its outputs (idempotent — see ``store.py``);
4. records itself in ``run_log.json`` and ``ScoreRuns``; refreshes ``params.yaml`` and
   ``data_sources.csv``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

import parkiq
from parkiq.config import REPO_ROOT, ResolvedConfig, missing_for_step
from parkiq.schema import Schema
from parkiq.store import Store, utcnow

log = logging.getLogger(__name__)

ORDER: tuple[str, ...] = (
    "schema",
    "setup",
    "ingest",
    "qaqc",
    "demand",
    "supply",
    "gap",
    "screen",
    "walksheds",
    "criteria",
    "suitability",
    "sensitivity",
    "finance",
    "shortlist",
    "package",
)


class StepBlocked(RuntimeError):
    """A step cannot run: missing upstream step or null required config."""


class StepNotImplemented(RuntimeError):
    """The step belongs to a later milestone."""


@dataclass
class RunContext:
    """Everything a step needs. Built by :func:`open_run`."""

    cfg: ResolvedConfig
    run_id: str
    run_dir: Path
    store: Store
    cache_dir: Path
    force: bool = False
    source_filter: list[str] | None = None
    log_path: Path | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def rasters_dir(self) -> Path:
        """Folder for GeoTIFFs beside the GeoPackage."""
        p = self.run_dir / "rasters"
        p.mkdir(exist_ok=True)
        return p


StepFn = Callable[[RunContext], dict[str, Any]]


@dataclass(frozen=True)
class Step:
    """A registered pipeline step."""

    name: str
    fn: StepFn | None
    deps: tuple[str, ...]
    reads: tuple[str, ...]  # dotted config sections hashed into the input hash
    milestone: str = "M1"


_REGISTRY: dict[str, Step] = {}


def register(
    name: str, deps: tuple[str, ...], reads: tuple[str, ...], milestone: str = "M1"
) -> Callable[[StepFn], StepFn]:
    """Decorator registering a step function."""

    def deco(fn: StepFn) -> StepFn:
        _REGISTRY[name] = Step(name, fn, deps, reads, milestone)
        return fn

    return deco


def _placeholder(name: str, deps: tuple[str, ...], milestone: str) -> None:
    if name not in _REGISTRY:
        _REGISTRY[name] = Step(name, None, deps, (), milestone)


def steps() -> dict[str, Step]:
    """All steps (implemented or placeholder), importing step modules on first use."""
    from parkiq import ingest, qaqc, schema_step, setup  # noqa: F401  (registers steps)

    _placeholder("demand", ("qaqc",), "M4")
    _placeholder("supply", ("qaqc",), "M3")
    _placeholder("gap", ("demand", "supply"), "M4")
    _placeholder("screen", ("gap",), "M5")
    _placeholder("walksheds", ("screen",), "M5")
    _placeholder("criteria", ("walksheds",), "M5")
    _placeholder("suitability", ("criteria",), "M5")
    _placeholder("sensitivity", ("suitability",), "M5")
    _placeholder("finance", ("suitability",), "M6")
    _placeholder("shortlist", ("finance", "sensitivity"), "M6")
    _placeholder("package", ("shortlist",), "M7")
    return _REGISTRY


# --------------------------------------------------------------------------- run identity


def code_version() -> str:
    """Package version plus git commit (``+dirty`` if the tree has uncommitted changes)."""
    commit = git_commit()
    return f"{parkiq.__version__}+{commit}" if commit else parkiq.__version__


def git_commit() -> str | None:
    """Short git commit of the repo, or None outside a git checkout."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "status",
                "--porcelain",
                "--",
                "parkiq",
                "configs",
                "schema",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def new_run_id(slug: str, scenario: str, now: datetime | None = None) -> str:
    """``YYYYMMDD_HHMM_<market>_<scenario>`` (SCOPE §6.5)."""
    return f"{(now or datetime.now()).strftime('%Y%m%d_%H%M')}_{slug}_{scenario}"


def output_root(explicit: str | Path | None = None) -> Path:
    """Where runs are written: explicit arg > ``PARKIQ_OUTPUT_ROOT`` > ``<repo>/outputs``."""
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("PARKIQ_OUTPUT_ROOT")
    return Path(env).resolve() if env else REPO_ROOT / "outputs"


# --------------------------------------------------------------------------- run lifecycle


def _setup_logging(path: Path) -> None:
    root = logging.getLogger("parkiq")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
            h.close()
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(fh)


def open_run(
    cfg: ResolvedConfig,
    run_id: str | None = None,
    out: str | Path | None = None,
    force: bool = False,
    source_filter: list[str] | None = None,
) -> RunContext:
    """Create a new run folder or reopen an existing one.

    Args:
        cfg: Resolved configuration.
        run_id: Existing run to resume; None creates a new one.
        out: Output root override.
        force: Re-run steps even if their input hash is unchanged.
        source_filter: Restrict ingest to these source IDs.

    Returns:
        The run context.
    """
    root = output_root(out) / cfg.slug
    rid = run_id or new_run_id(cfg.slug, cfg.weights.run_id_scenario)
    run_dir = root / rid
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    cache = root / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "logs" / f"{rid}.log"
    _setup_logging(log_path)
    schema = Schema.load(cfg.schema_path)
    store = Store(run_dir / f"ParkIQ_{cfg.slug}.gpkg", schema, rid, cfg.crs)
    ctx = RunContext(cfg, rid, run_dir, store, cache, force, source_filter, log_path)
    write_params(ctx)
    log.info("run %s opened (%s) code %s", rid, run_dir, code_version())
    return ctx


def _run_log_path(ctx: RunContext) -> Path:
    return ctx.run_dir / "run_log.json"


def read_run_log(ctx: RunContext) -> dict[str, Any]:
    """Load ``run_log.json`` (empty skeleton if new)."""
    p = _run_log_path(ctx)
    if p.exists():
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return data
    return {"run_id": ctx.run_id, "market": ctx.cfg.slug, "steps": {}}


def _write_run_log(ctx: RunContext, data: dict[str, Any]) -> None:
    _run_log_path(ctx).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_params(ctx: RunContext) -> None:
    """Write ``params.yaml`` — the fully resolved config plus run identity."""
    d = {
        "run_id": ctx.run_id,
        "code_version": code_version(),
        "schema_version": ctx.store.schema.version,
        **ctx.cfg.as_dict(),
    }
    (ctx.run_dir / "params.yaml").write_text(
        yaml.safe_dump(json.loads(json.dumps(d, default=str)), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def export_data_sources(ctx: RunContext) -> None:
    """Export ``DataSourceRegistry`` to ``data_sources.csv``."""
    df = ctx.store.read_table("DataSourceRegistry")
    if len(df):
        df.sort_values("source_id").to_csv(ctx.run_dir / "data_sources.csv", index=False)


def _input_fingerprint(ctx: RunContext) -> str:
    """Fingerprint of local source files (path, size, mtime) so edited inputs re-trigger."""
    parts = []
    for sid, s in sorted(ctx.cfg.sources.items()):
        paths = s.path if isinstance(s.path, list) else ([s.path] if s.path else [])
        for p in paths:
            pp = Path(p)
            if pp.exists():
                st = pp.stat()
                parts.append(f"{sid}:{pp}:{st.st_size}:{int(st.st_mtime)}")
    g = ctx.cfg.market.network.graph_path
    if g and Path(g).exists():
        parts.append(f"graph:{g}:{Path(g).stat().st_size}")
    b = ctx.cfg.market.market.boundary
    if b.type == "custom" and Path(b.value).exists():
        parts.append(f"boundary:{b.value}:{Path(b.value).stat().st_size}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def step_hash(ctx: RunContext, step: Step, run_log: dict[str, Any]) -> str:
    """Input hash for a step."""
    dep_hashes = [run_log["steps"].get(d, {}).get("input_hash", "") for d in step.deps]
    payload = {
        "step": step.name,
        "config": ctx.cfg.section_hash(*step.reads) if step.reads else "",
        "deps": dep_hashes,
        "code": code_version(),
        "inputs": _input_fingerprint(ctx) if step.name in ("setup", "ingest") else "",
        "sources": sorted(ctx.source_filter or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def resolve_steps(spec: str) -> list[str]:
    """Parse ``--steps`` (``all`` or comma list) into ordered step names."""
    reg = steps()
    if spec.strip() == "all":
        return list(ORDER)
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in reg]
    if unknown:
        raise ValueError(f"Unknown steps {unknown}. Valid: {', '.join(ORDER)}")
    return [n for n in ORDER if n in names]


def run_steps(
    ctx: RunContext, names: list[str], stop_at_unimplemented: bool = True
) -> dict[str, dict[str, Any]]:
    """Run steps in pipeline order.

    Args:
        ctx: Run context.
        names: Steps to run (already ordered).
        stop_at_unimplemented: For ``--steps all``: stop quietly at the first later-milestone
            step instead of raising.

    Returns:
        Per-step status dicts, as recorded in ``run_log.json``.

    Raises:
        StepBlocked: When a dependency or required config value is missing.
        StepNotImplemented: When an explicitly requested step is not built yet.
    """
    reg = steps()
    results: dict[str, dict[str, Any]] = {}
    for name in names:
        step = reg[name]
        run_log = read_run_log(ctx)
        if step.fn is None:
            msg = f"step '{name}' is scheduled for {step.milestone} and not implemented yet"
            if stop_at_unimplemented:
                log.warning(msg)
                results[name] = {"status": "not_implemented", "message": msg}
                break
            raise StepNotImplemented(msg)
        for dep in step.deps:
            if run_log["steps"].get(dep, {}).get("status") != "succeeded":
                raise StepBlocked(
                    f"step '{name}' needs '{dep}' to have succeeded in run "
                    f"{ctx.run_id}; run --steps {dep} first"
                )
        missing = missing_for_step(ctx.cfg, name)
        if missing:
            raise StepBlocked(
                f"step '{name}' needs these config values set (currently null): "
                + ", ".join(missing)
            )
        h = step_hash(ctx, step, run_log)
        prev = run_log["steps"].get(name, {})
        if not ctx.force and prev.get("status") == "succeeded" and prev.get("input_hash") == h:
            log.info("skip %s (inputs unchanged)", name)
            results[name] = {**prev, "skipped": True}
            continue
        started = utcnow()
        log.info("=== step %s start", name)
        rec: dict[str, Any] = {
            "status": "running",
            "started": started.isoformat(),
            "input_hash": h,
            "code_version": code_version(),
        }
        run_log["steps"][name] = rec
        _write_run_log(ctx, run_log)
        try:
            summary = step.fn(ctx)
        except Exception as exc:
            rec.update(status="failed", finished=utcnow().isoformat(), message=str(exc))
            _write_run_log(ctx, run_log)
            log.exception("step %s failed", name)
            raise
        rec.update(status="succeeded", finished=utcnow().isoformat(), summary=summary)
        # a re-run step invalidates downstream steps recorded earlier
        for later in ORDER[ORDER.index(name) + 1 :]:
            if later in run_log["steps"] and later not in names:
                run_log["steps"][later]["status"] = "stale"
        _write_run_log(ctx, run_log)
        _record_score_run(ctx, name, summary)
        write_params(ctx)
        export_data_sources(ctx)
        log.info("=== step %s done: %s", name, summary)
        results[name] = rec
    return results


def _record_score_run(ctx: RunContext, step: str, summary: dict[str, Any]) -> None:
    import pandas as pd

    row = pd.DataFrame(
        [
            {
                "market": ctx.cfg.slug,
                "scenario": ctx.cfg.weights.run_id_scenario,
                "step": step,
                "timestamp": utcnow(),
                "toolbox_version": parkiq.__version__,
                "git_commit": git_commit(),
                "params_json": json.dumps({"step": step, "summary": summary}, default=str),
                "candidate_cnt": summary.get("candidate_cnt"),
            }
        ]
    )
    ctx.store.write_table("ScoreRuns", row, key={"step": step})
