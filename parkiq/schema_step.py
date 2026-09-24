"""Step ``schema`` (tool 1 BuildSchema, M1 subset).

M1: initialise the run GeoPackage with the config-derived tables so every run carries the exact
rates, criteria, weights and finance parameters it used (SCOPE §4.3): ParkingRates,
CriteriaDefinitions, WeightScenarios, FinanceParams. M2 extends this into the full BuildSchema
(all empty layers, domains as GeoPackage constraints, related tables).
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from parkiq.config import DAYPARTS
from parkiq.runner import RunContext, register


@register("schema", deps=(), reads=("rates", "criteria", "weights", "finance"))
def build_schema(ctx: RunContext) -> dict[str, Any]:
    """Write config tables for this run."""
    cfg = ctx.cfg
    calib = cfg.rates.calibration_factors
    rates = pd.DataFrame(
        [
            {
                "category": cat,
                "daypart": dp,
                "rate": getattr(row, dp),
                "unit": row.unit,
                "source_citation": row.source,
                "calibration_factor": calib.get(cat, {}).get(dp)
                if isinstance(calib.get(cat), dict)
                else None,
            }
            for cat, row in sorted(cfg.rates.rates.items())
            for dp in DAYPARTS
        ]
    )
    n = cfg.criteria.normalization
    crit = pd.DataFrame(
        [
            {
                "criterion_id": cid,
                "name": c.name,
                "description": c.description,
                "unit": c.unit,
                "direction": c.direction,
                "normalization": f"winsorize {n.winsor_percentiles}; min-max {n.scale}"
                + ("; inverted" if c.direction == "Cost" else ""),
            }
            for cid, c in sorted(cfg.criteria.criteria.items())
        ]
    )
    weights = pd.DataFrame(
        [
            {"scenario": s, "criterion_id": cid, "weight": w}
            for s, ws in sorted(cfg.weights.scenarios.items())
            for cid, w in sorted(ws.items())
        ]
    )
    fin = pd.DataFrame(
        [
            {"param": k, "value": json.dumps(v)}
            for k, v in sorted(cfg.finance.model_dump(mode="json").items())
        ]
    )
    ctx.store.write_table("ParkingRates", rates)
    ctx.store.write_table("CriteriaDefinitions", crit)
    ctx.store.write_table("WeightScenarios", weights)
    ctx.store.write_table("FinanceParams", fin)
    return {
        "schema_version": ctx.store.schema.version,
        "rates_rows": len(rates),
        "criteria": len(crit),
        "weights_rows": len(weights),
        "finance_params": len(fin),
    }
