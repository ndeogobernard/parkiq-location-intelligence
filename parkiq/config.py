"""Configuration models, loading, merging and validation.

Every config value the library reads goes through these pydantic models (docs/ENGINEERING.md).
Rules:

* Unknown keys are errors (``extra="forbid"``).
* Parameters the scope leaves open (status DECIDE) are ``None`` by default. They never get a
  value in code; instead each pipeline step declares the dotted paths it needs
  (:data:`STEP_REQUIREMENTS`) and refuses to run while any is null.
* Provenance (status SCOPE / VERIFY / SET / DECIDE + source) is carried in a ``provenance:`` map
  in each YAML file, keyed by dotted path, mirroring the admin workbook's Parameters sheet.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pyproj import CRS

from parkiq import units

Daypart = Literal["wd_day", "wd_eve", "we_day", "we_eve", "event"]
AnchorCategory = Literal[
    "Office",
    "Medical",
    "University",
    "Hotel",
    "RestaurantBar",
    "Retail",
    "Venue",
    "Transit",
    "ResidentialBlock",
    "Government",
    "Other",
]  # dm_AnchorCategory (SCOPE §4.4)
DAYPARTS: tuple[str, ...] = ("wd_day", "wd_eve", "we_day", "we_eve", "event")
SCENARIOS: tuple[str, ...] = ("Balanced", "DemandFirst", "CostFirst")
CRITERIA: tuple[str, ...] = tuple(f"C{i:02d}" for i in range(1, 11))
Status = Literal["SCOPE", "VERIFY", "SET", "DECIDE"]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "configs"
DEFAULT_SCHEMA = REPO_ROOT / "schema" / "schema.yaml"


class ConfigError(ValueError):
    """Raised for any invalid, inconsistent or missing configuration."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(_Strict):
    """Where a parameter value came from."""

    status: Status
    source: str = ""


# --------------------------------------------------------------------------- market file


class Boundary(_Strict):
    """Market boundary definition (SCOPE §2.1)."""

    type: Literal["place", "county", "custom"]
    value: str = Field(description="GEOID for place/county; path to a polygon file for custom")


class SubmarketsSource(_Strict):
    """Polygons for focus submarkets (reporting/insets only — never a filter, SCOPE §2.2)."""

    path: Path
    name_field: str
    type_field: str | None = None


class MarketSection(_Strict):
    """``market:`` block."""

    name: str
    slug: str = Field(pattern=r"^[a-z0-9_]+$")
    boundary: Boundary
    focus_submarkets: list[str] = Field(default_factory=list)
    submarkets_source: SubmarketsSource | None = None
    analysis_crs: str
    units: Literal["ft", "m"]

    @model_validator(mode="after")
    def _crs_matches_units(self) -> MarketSection:
        try:
            kind = units.crs_unit_kind(CRS.from_user_input(self.analysis_crs))
        except Exception as exc:  # pyproj raises several types
            raise ValueError(f"analysis_crs {self.analysis_crs!r}: {exc}") from exc
        if kind != self.units:
            raise ValueError(
                f"market.units is {self.units!r} but {self.analysis_crs} is in {kind!r}"
            )
        if self.focus_submarkets and self.submarkets_source is None:
            raise ValueError(
                "focus_submarkets are named but submarkets_source (polygons) is not set"
            )
        return self


class StudySection(_Strict):
    """``study:`` block — study area and grid (SCOPE §2.2)."""

    buffer_miles: float = Field(ge=0)
    h3_resolution: int = Field(ge=0, le=15)


class SiteSection(_Strict):
    """``site:`` block — screen and layout parameters (SCOPE §2.1, §5.5)."""

    min_parcel_sqft: float = Field(gt=0)
    max_parcel_sqft: float = Field(gt=0)
    target_stalls_range: tuple[int, int]
    stall_area_sqft_gross: float = Field(gt=0)
    layout_efficiency: float = Field(gt=0, le=1)
    setback_landscape_pct: float = Field(ge=0, lt=1)
    max_slope_pct: float = Field(gt=0)
    min_frontage_ft: float = Field(ge=0)
    min_shape_index: float = Field(ge=0, le=1)
    improvement_ratio_max: float | None = None
    frontage_buffer_ft: float | None = None

    @model_validator(mode="after")
    def _ranges(self) -> SiteSection:
        if self.min_parcel_sqft >= self.max_parcel_sqft:
            raise ValueError("site.min_parcel_sqft must be < max_parcel_sqft")
        lo, hi = self.target_stalls_range
        if not 0 < lo < hi:
            raise ValueError("site.target_stalls_range must be [min, max] with 0 < min < max")
        return self


class TransitAdjustment(_Strict):
    """Transit demand adjustment (SCOPE §2.1)."""

    high_frequency_radius_m: float = Field(gt=0)
    demand_factor: float = Field(gt=0, le=1)
    high_frequency_headway_max_min: float | None = None
    peak_window: tuple[str, str] | None = None

    @field_validator("peak_window")
    @classmethod
    def _hhmm(cls, v: tuple[str, str] | None) -> tuple[str, str] | None:
        if v is None:
            return v
        for s in v:
            hh, mm = s.split(":")
            if not (0 <= int(hh) <= 47 and 0 <= int(mm) < 60):
                raise ValueError(f"peak_window time {s!r} must be HH:MM")
        return v


class DemandSection(_Strict):
    """``demand:`` block (SCOPE §2.1, §5.2)."""

    walk_shed_minutes: list[float]
    decay_weights: dict[float, float]
    dayparts: list[Daypart]
    parking_generation_source: str
    transit_adjustment: TransitAdjustment
    mode_adjustment: Literal["relative", "none"] | None = None
    residential_offstreet_share: float | None = None
    excluded_anchor_categories: list[AnchorCategory] = Field(default_factory=list)
    # M4 (ADR-0068..0071)
    commute_categories: list[AnchorCategory] = Field(default_factory=list)
    workplace_drive_share_path: Path | None = None
    workplace_places_path: Path | None = None
    meters_per_floor: float | None = Field(default=None, gt=0)
    hotel_sqft_per_room: float | None = Field(default=None, gt=0)
    campus_rule: dict[str, list[str]] = Field(default_factory=dict)
    single_anchor_share: float | None = Field(default=None, gt=0, le=1)
    floor_area_cap_sqft: dict[str, float] = Field(default_factory=dict)
    # ADR-0078: in-office attendance vs the rate's (pre-pandemic) baseline, {category: {daypart: f}}
    attendance_factor: dict[str, dict[str, float]] = Field(default_factory=dict)
    workplace_min_commuters: float | None = Field(default=None, ge=0)
    workplace_source_id: str | None = None
    jurisdiction_places_path: Path | None = None

    @model_validator(mode="after")
    def _consistent(self) -> DemandSection:
        if sorted(self.walk_shed_minutes) != self.walk_shed_minutes:
            raise ValueError("demand.walk_shed_minutes must be ascending")
        if set(self.decay_weights) != set(self.walk_shed_minutes):
            raise ValueError("demand.decay_weights keys must equal walk_shed_minutes")
        if tuple(self.dayparts) != DAYPARTS:
            raise ValueError(f"demand.dayparts must be exactly {list(DAYPARTS)} (SCOPE §1.3)")
        return self


class NetworkSection(_Strict):
    """``network:`` block — pedestrian network (SCOPE §5.1, ADR-0004)."""

    backend: Literal["osmnx"]
    walking_speed_m_s: float = Field(gt=0)
    network_type: str
    graph_path: Path | None = None


class SupplySection(_Strict):
    """``supply:`` block (SCOPE §2.1, §5.3)."""

    private_effective_share: float = Field(ge=0, le=1)
    onstreet_stall_length_ft: float = Field(gt=0)
    dedupe_distance_m: float = Field(gt=0)
    dedupe_name_similarity: float | None = Field(default=None, ge=0, le=1)
    dedupe_unnamed_touch_m: float | None = Field(default=None, ge=0)
    onstreet_intersection_clearance_ft: float | None = None
    onstreet_driveway_allowance_ft: float | None = None
    unknown_access_as_private: bool | None = None
    curb_local_highways: list[str] = Field(default_factory=list)
    curb_sensitive_ratio: float | None = Field(default=None, gt=0)
    surface_capacity_factor: float | None = Field(default=None, gt=0)
    exclusions_path: Path | None = None
    parcel_estimate_classes: list[str] = Field(default_factory=list)
    parcel_estimate_max_acres: float | None = Field(default=None, gt=0)
    paid_operators: list[str] = Field(default_factory=list)
    survey_observations_path: Path | None = None
    paid_signal_overrides_path: Path | None = None  # ADR-0075: reviewed paid signals to drop
    practical_capacity: float | None = Field(default=None, gt=0, le=1)  # ADR-0079
    benchmark_occupancy_path: Path | None = None  # ADR-0079: observed peak occupancy by area


class RankingSection(_Strict):
    """``ranking:`` block (SCOPE §5.8)."""

    financial_weight: float = Field(ge=0, le=1)
    suitability_weight: float = Field(ge=0, le=1)
    shortlist_size: int | None = None

    @model_validator(mode="after")
    def _sum(self) -> RankingSection:
        if abs(self.financial_weight + self.suitability_weight - 1.0) > 1e-9:
            raise ValueError("ranking weights must sum to 1.00")
        return self


class DataLicenses(_Strict):
    """``data_licenses:`` — flags gating licensed sources. Absent flag = not licensed."""

    regrid: bool = False
    foot_traffic: Literal["placer", "advan", "none"] = "none"
    parking_transactions: str = "none"
    parking_apps: bool = False
    land_listings: bool = False
    cost_index: bool = False
    ite_manual: bool = False
    str_hotels: bool = False
    ticketmaster: bool = False


class SourceEntry(_Strict):
    """One source's settings (defaults from configs/sources.yaml, overridden per market)."""

    provider: str = ""
    dataset: str = ""
    license: str = ""
    license_flag: str | None = None
    url: str | None = None
    path: Path | list[Path] | None = None
    vintage: str | None = None
    enabled: bool = True
    verify: bool = False
    synthetic: bool = False
    field_map: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class MarketConfig(_Strict):
    """A complete market file (``markets/<slug>.yaml``)."""

    market: MarketSection
    study: StudySection
    site: SiteSection
    demand: DemandSection
    network: NetworkSection
    supply: SupplySection
    finance: dict[str, Any] = Field(default_factory=dict)
    ranking: RankingSection | None = None
    c04_daypart_weights: dict[Daypart, float] | None = None  # overrides criteria.yaml (ADR-0081)
    data_licenses: DataLicenses
    sources: dict[str, SourceEntry] = Field(default_factory=dict)
    provenance: dict[str, Provenance] = Field(default_factory=dict)


# --------------------------------------------------------------------------- shared configs


class WeightsConfig(_Strict):
    """``configs/weights.yaml`` (SCOPE Appendix B)."""

    scenarios: dict[str, dict[str, float]]
    ranking: RankingSection
    run_id_scenario: str
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid(self) -> WeightsConfig:
        if set(self.scenarios) != set(SCENARIOS):
            raise ValueError(f"weights.scenarios must be exactly {list(SCENARIOS)}")
        for name, w in self.scenarios.items():
            if set(w) != set(CRITERIA):
                raise ValueError(f"scenario {name} must weight exactly {list(CRITERIA)}")
            if abs(sum(w.values()) - 1.0) > 1e-9:
                raise ValueError(f"scenario {name} weights sum to {sum(w.values()):.6f}, not 1.00")
            if any(v < 0 for v in w.values()):
                raise ValueError(f"scenario {name} has a negative weight")
        if self.run_id_scenario not in SCENARIOS:
            raise ValueError("run_id_scenario must be one of the scenarios")
        return self


class RateRow(_Strict):
    """One parking-generation rate row (SCOPE Appendix C)."""

    anchor_category: AnchorCategory
    unit: str
    wd_day: float = Field(ge=0)
    wd_eve: float = Field(ge=0)
    we_day: float = Field(ge=0)
    we_eve: float = Field(ge=0)
    event: float = Field(ge=0)
    source: str
    baseline_drive_share: float | None = None

    @property
    def verify(self) -> bool:
        """True while the citation is unconfirmed."""
        return "[VERIFY]" in self.source


class RatesConfig(_Strict):
    """``configs/parking_rates.yaml``."""

    rates: dict[str, RateRow]
    calibration_factors: dict[str, Any] = Field(default_factory=dict)


class CriterionDef(_Strict):
    """One criterion definition."""

    name: str
    unit: str
    direction: Literal["Benefit", "Cost"]
    description: str
    shed_minutes: float | None = None
    dayparts: list[Daypart] | None = None


class NormalizationConfig(_Strict):
    """Normalization settings (SCOPE §5.7)."""

    winsor_percentiles: tuple[float, float]
    scale: tuple[float, float]
    constant_score: float


class CriteriaConfig(_Strict):
    """``configs/criteria.yaml``."""

    normalization: NormalizationConfig
    criteria: dict[str, CriterionDef]
    c04_daypart_weights: dict[Daypart, float] | None = None
    c06: dict[str, float]
    c09_scores: dict[str, float]
    sensitivity: dict[str, float] = Field(
        default_factory=lambda: {
            "oat_pct": 0.25,
            "draws": 1000,
            "alpha": 1.0,
            "seed": 0,
            "top_n": 10,
        }
    )
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _all(self) -> CriteriaConfig:
        if set(self.criteria) != set(CRITERIA):
            raise ValueError(f"criteria must define exactly {list(CRITERIA)}")
        return self


class FinanceConfig(_Strict):
    """Resolved finance parameters (defaults ← market overrides). DECIDE keys may be null."""

    land_cost_source: list[str]
    assessed_to_market_ratio: float | None = None
    construction_cost_per_stall_usd: float | None = None
    soft_cost_pct: float | None = None
    opex_per_stall_year_usd: float | None = None
    property_tax_rate: float | None = None
    new_entrant_rate_discount: float | None = None
    occupancy_caps: dict[Daypart, float] | None = None
    target_cap_rate: float | None = None
    hold_years: int | None = None
    discount_rate: float | None = None
    tech_fee_pct_revenue: float | None = None
    mgmt_fee_pct_revenue: float | None = None
    occupancy_curve: list[tuple[float, float]] | None = None
    capture_share: float | None = None
    billing: dict[Daypart, dict[str, Any]] | None = None
    operating_days: dict[Daypart, float] | None = None
    event_weekday_share: float | None = None
    permit_share: float | None = None
    office_heavy_threshold: float | None = None
    revenue_growth: float | None = None
    opex_growth: float | None = None
    exit_cap_rate: float | None = None
    selling_cost_pct: float | None = None
    ground_lease_rent_pct_of_land_value: float | None = None
    ground_lease_escalator: float | None = None
    ground_lease_term_years: int | None = None
    daypart_rate_map: dict[Daypart, list[str]]
    evening_stay_hours: float | None = None

    @field_validator("occupancy_caps")
    @classmethod
    def _caps(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is not None:
            if set(v) != set(DAYPARTS):
                raise ValueError("occupancy_caps must cover all five dayparts")
            if any(not 0 <= x <= 1 for x in v.values()):
                raise ValueError("occupancy_caps must be in [0, 1] (rg_Occupancy)")
        return v


# --------------------------------------------------------------------------- resolved bundle


class ResolvedConfig(BaseModel):
    """Everything a run needs, fully resolved. Written to ``params.yaml``."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    market_path: Path
    config_dir: Path
    schema_path: Path
    market: MarketConfig
    weights: WeightsConfig
    rates: RatesConfig
    criteria: CriteriaConfig
    finance: FinanceConfig
    ranking: RankingSection
    sources: dict[str, SourceEntry]
    provenance: dict[str, Provenance]
    fallbacks: list[str] = Field(default_factory=list)

    @property
    def slug(self) -> str:
        """Market slug."""
        return self.market.market.slug

    @property
    def crs(self) -> CRS:
        """Analysis CRS."""
        return CRS.from_user_input(self.market.market.analysis_crs)

    def get(self, dotted: str) -> Any:
        """Look up a dotted path in the resolved config (e.g. ``finance.capture_share``)."""
        return _get_path(self.as_dict(), dotted)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict of the resolved config (what params.yaml contains)."""
        return {
            "market_file": str(self.market_path),
            "market": self.market.model_dump(
                mode="json", exclude={"sources", "provenance", "finance"}
            ),
            "finance": self.finance.model_dump(mode="json"),
            "ranking": self.ranking.model_dump(mode="json"),
            "weights": self.weights.model_dump(mode="json", exclude={"provenance"}),
            "rates": self.rates.model_dump(mode="json"),
            "criteria": self.criteria.model_dump(mode="json", exclude={"provenance"}),
            "sources": {k: v.model_dump(mode="json") for k, v in sorted(self.sources.items())},
            "provenance": {k: v.model_dump() for k, v in sorted(self.provenance.items())},
            "fallbacks": list(self.fallbacks),
        }

    def section_hash(self, *dotted: str) -> str:
        """Stable hash of the given config sections (used for step input hashes)."""
        d = self.as_dict()
        payload = {p: _get_path(d, p) for p in dotted}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _get_path(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                # dict keys may be non-strings after model_dump (e.g. float decay keys)
                matches = [k for k in cur if str(k) == part]
                if not matches:
                    raise KeyError(dotted)
                cur = cur[matches[0]]
        else:
            raise KeyError(dotted)
    return cur


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    return data


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _fmt(exc: ValidationError, where: Path) -> str:
    lines = [f"{where}:"]
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"])
        lines.append(f"  - {loc}: {e['msg']}")
    return "\n".join(lines)


def _resolve_path(p: Path, base: Path) -> Path:
    return p if p.is_absolute() else (base / p).resolve()


def load_config(
    market_path: str | Path,
    config_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
) -> ResolvedConfig:
    """Load, merge and validate a market file with the shared configs.

    Args:
        market_path: Path to ``markets/<slug>.yaml``.
        config_dir: Directory holding the shared configs (default: repo ``configs/``).
        schema_path: Path to ``schema/schema.yaml`` (default: repo copy).

    Returns:
        The fully resolved configuration.

    Raises:
        ConfigError: On any validation failure, with every problem listed.
    """
    market_path = Path(market_path).resolve()
    cdir = Path(config_dir).resolve() if config_dir else DEFAULT_CONFIG_DIR
    spath = Path(schema_path).resolve() if schema_path else DEFAULT_SCHEMA
    errors: list[str] = []

    raw_market = _load_yaml(market_path)
    try:
        market = MarketConfig.model_validate(raw_market)
    except ValidationError as exc:
        raise ConfigError(_fmt(exc, market_path)) from exc

    def _v(model: type[BaseModel], path: Path) -> Any:
        try:
            return model.model_validate(_load_yaml(path))
        except ValidationError as exc:
            errors.append(_fmt(exc, path))
            return None

    weights = _v(WeightsConfig, cdir / "weights.yaml")
    rates = _v(RatesConfig, cdir / "parking_rates.yaml")
    criteria = _v(CriteriaConfig, cdir / "criteria.yaml")

    fin_raw = _load_yaml(cdir / "finance_defaults.yaml")
    unknown_fin = set(market.finance) - set(FinanceConfig.model_fields)
    if unknown_fin:
        errors.append(f"{market_path}: unknown finance keys {sorted(unknown_fin)}")
    finance = None
    try:
        finance = FinanceConfig.model_validate(
            _deep_merge(fin_raw.get("finance", {}), market.finance)
        )
    except ValidationError as exc:
        errors.append(_fmt(exc, cdir / "finance_defaults.yaml"))

    src_raw = _load_yaml(cdir / "sources.yaml").get("sources", {})
    sources: dict[str, SourceEntry] = {}
    unknown_src = set(market.sources) - set(src_raw)
    if unknown_src:
        errors.append(f"{market_path}: sources not in configs/sources.yaml: {sorted(unknown_src)}")
    for sid, default in src_raw.items():
        override = raw_market.get("sources", {}).get(sid, {}) or {}
        try:
            entry = SourceEntry.model_validate(_deep_merge(default, override))
        except ValidationError as exc:
            errors.append(_fmt(exc, cdir / "sources.yaml"))
            continue
        base = market_path.parent
        if entry.path is not None:  # paths in a market file are relative to that file
            p = entry.path
            entry = entry.model_copy(
                update={
                    "path": [_resolve_path(x, base) for x in p]
                    if isinstance(p, list)
                    else _resolve_path(p, base)
                }
            )
        # convention: any option key ending in "_path" is a file path
        opts = {
            k: str(_resolve_path(Path(v), base))
            if k.endswith("_path") and isinstance(v, str)
            else v
            for k, v in entry.options.items()
        }
        if opts != entry.options:
            entry = entry.model_copy(update={"options": opts})
        sources[sid] = entry

    if errors:
        raise ConfigError("\n".join(errors))
    assert weights and rates and criteria and finance  # for type-checkers

    # Market file paths are relative to the market file
    m = market
    upd: dict[str, Any] = {}
    if m.network.graph_path is not None:
        upd["network"] = m.network.model_copy(
            update={"graph_path": _resolve_path(m.network.graph_path, market_path.parent)}
        )
    dm = m.demand
    dupd = {
        k: _resolve_path(getattr(dm, k), market_path.parent)
        for k in ("workplace_drive_share_path", "workplace_places_path", "jurisdiction_places_path")
        if getattr(dm, k) is not None
    }
    if dupd:
        upd["demand"] = dm.model_copy(update=dupd)
    supd = {
        k: _resolve_path(getattr(m.supply, k), market_path.parent)
        for k in (
            "exclusions_path",
            "survey_observations_path",
            "paid_signal_overrides_path",
            "benchmark_occupancy_path",
        )
        if getattr(m.supply, k) is not None
    }
    if supd:
        upd["supply"] = m.supply.model_copy(update=supd)
    mk = m.market
    if mk.submarkets_source is not None:
        ss = mk.submarkets_source.model_copy(
            update={"path": _resolve_path(mk.submarkets_source.path, market_path.parent)}
        )
        mk = mk.model_copy(update={"submarkets_source": ss})
    if mk.boundary.type == "custom":
        b = mk.boundary.model_copy(
            update={"value": str(_resolve_path(Path(mk.boundary.value), market_path.parent))}
        )
        mk = mk.model_copy(update={"boundary": b})
    upd["market"] = mk
    market = m.model_copy(update=upd)

    ranking = market.ranking or weights.ranking  # ADR-0017: market overrides shared
    if market.c04_daypart_weights is not None:
        tot = sum(market.c04_daypart_weights.values())
        if abs(tot - 1.0) > 1e-3:
            raise ConfigError(f"{market_path}: c04_daypart_weights sum to {tot:.4f}, not 1.00")
        criteria = criteria.model_copy(update={"c04_daypart_weights": market.c04_daypart_weights})
    provenance: dict[str, Provenance] = {}
    for f in ("finance_defaults.yaml", "weights.yaml", "criteria.yaml"):
        for k, v in _load_yaml(cdir / f).get("provenance", {}).items():
            provenance[k] = Provenance.model_validate(v)
    provenance.update(market.provenance)  # market wins

    return ResolvedConfig(
        market_path=market_path,
        config_dir=cdir,
        schema_path=spath,
        market=market,
        weights=weights,
        rates=rates,
        criteria=criteria,
        finance=finance,
        ranking=ranking,
        sources=sources,
        provenance=provenance,
    )


# --------------------------------------------------------------------------- step gating

#: Dotted config paths each step needs non-null. check-config reports readiness from this.
STEP_REQUIREMENTS: dict[str, list[str]] = {
    "schema": [],
    "setup": ["network.walking_speed_m_s"],
    "ingest": [],
    "qaqc": [],
    "demand": [
        "market.demand.transit_adjustment.high_frequency_headway_max_min",
        "market.demand.transit_adjustment.peak_window",
        "market.demand.mode_adjustment",
        "market.demand.hotel_sqft_per_room",
        "market.demand.meters_per_floor",
    ],
    "supply": [
        "market.supply.dedupe_name_similarity",
        "market.supply.dedupe_unnamed_touch_m",
        "market.supply.unknown_access_as_private",
        "market.supply.curb_sensitive_ratio",
    ],
    "gap": [],
    "screen": ["market.site.improvement_ratio_max", "market.site.frontage_buffer_ft"],
    "walksheds": [],
    "criteria": ["criteria.c04_daypart_weights"],
    "suitability": [],
    "sensitivity": [],
    "finance": [
        "finance.tech_fee_pct_revenue",
        "finance.mgmt_fee_pct_revenue",
        "finance.occupancy_curve",
        "finance.capture_share",
        "finance.billing",
        "finance.operating_days",
        "finance.event_weekday_share",
        "finance.revenue_growth",
        "finance.opex_growth",
        "finance.exit_cap_rate",
        "finance.selling_cost_pct",
        "finance.ground_lease_rent_pct_of_land_value",
        "finance.ground_lease_escalator",
        "finance.ground_lease_term_years",
    ],
    "shortlist": ["ranking.shortlist_size"],
    "package": [],
}


def missing_for_step(cfg: ResolvedConfig, step: str) -> list[str]:
    """Return the required dotted paths that are null for ``step``."""
    d = cfg.as_dict()
    d["network"] = d["market"]["network"]
    missing = []
    for p in STEP_REQUIREMENTS.get(step, []):
        try:
            v = _get_path(d, p)
        except KeyError:
            v = None
        if v is None:
            missing.append(p)
    return missing


def verify_items(cfg: ResolvedConfig) -> list[tuple[str, str]]:
    """List every value still tagged VERIFY: (item, source/reason)."""
    out: list[tuple[str, str]] = []
    for k, p in sorted(cfg.provenance.items()):
        if p.status == "VERIFY":
            out.append((k, p.source))
    excluded = set(cfg.market.demand.excluded_anchor_categories)
    for cat, row in sorted(cfg.rates.rates.items()):
        if row.verify and row.anchor_category not in excluded:
            out.append((f"rates.{cat}", row.source))
    custom_boundary = cfg.market.market.boundary.type == "custom"
    for sid, s in sorted(cfg.sources.items()):
        if sid == "S00" and custom_boundary:
            continue  # TIGER boundary file unused
        if s.enabled and s.verify and s.path is None:
            out.append((f"sources.{sid}", f"{s.dataset} — endpoint {s.url!r} unconfirmed"))
    return out


def unused_items(cfg: ResolvedConfig) -> list[tuple[str, str]]:
    """Config items this market does not use (so their [VERIFY] tags are not open items here)."""
    excluded = set(cfg.market.demand.excluded_anchor_categories)
    prov = cfg.provenance.get("demand.excluded_anchor_categories")
    why = prov.source if prov and prov.source else "demand.excluded_anchor_categories"
    return [
        (f"rates.{cat}", f"not used in this market; {row.anchor_category} excluded ({why})")
        for cat, row in sorted(cfg.rates.rates.items())
        if row.anchor_category in excluded
    ]


def parameter_report(cfg: ResolvedConfig) -> list[dict[str, Any]]:
    """Flatten numeric/list parameters with status, in the admin workbook's Parameters layout.

    Returns:
        Rows with keys ``group, parameter, value, status, source``. Numeric values with no
        provenance entry get status ``UNTAGGED`` (a check-config warning).
    """
    d = cfg.as_dict()
    rows: list[dict[str, Any]] = []
    groups = {
        "Market": d["market"]["market"],
        "Study": d["market"]["study"],
        "Site": d["market"]["site"],
        "Demand": d["market"]["demand"],
        "Network": d["market"]["network"],
        "Supply": d["market"]["supply"],
        "Finance": d["finance"],
        "Ranking": d["ranking"],
    }
    prefix = {"Finance": "finance", "Ranking": "ranking"}
    for g, sect in groups.items():
        for k, v in sect.items():
            if isinstance(v, dict) and g not in ("Finance",) and k not in ("decay_weights",):
                items = [(f"{k}.{kk}", vv) for kk, vv in v.items()]
            else:
                items = [(k, v)]
            for name, val in items:
                key = f"{prefix.get(g, g.lower())}.{name}"
                prov = cfg.provenance.get(key) or cfg.provenance.get(key.split(".", 1)[1])
                if val is None:
                    status, src = "DECIDE", prov.source if prov else ""
                elif prov:
                    status, src = prov.status, prov.source
                elif isinstance(val, int | float) and not isinstance(val, bool):
                    status, src = "UNTAGGED", ""
                else:
                    status, src = "SET", ""
                rows.append(
                    {"group": g, "parameter": name, "value": val, "status": status, "source": src}
                )
    return rows
