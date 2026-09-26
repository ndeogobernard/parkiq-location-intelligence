"""Zoning screen: resolve a parcel's commercial-parking status from a market zoning table.

The table (e.g. ``markets/franklin_oh/zoning_screen.csv``) is hand-curated from the ordinance, one
row per district, with ``commercial_parking_use`` (dm_ZoningScreen), ``confidence`` and citations.
This module turns a parcel's jurisdiction, GIS zoning code, overlays and (downtown) parking zone
into a screen result and a routing decision (SCOPE §5.5; ADR-0058, ADR-0059):

* ByRight / Conditional -> ``Pass`` (Conditional scores lower in C09);
* Unknown -> ``Review``;
* Prohibited -> ``Fail``, **except** Low-confidence Prohibited -> ``Review``;
* any Limited-overlay code (``L`` prefix) takes its base district's result and is always ``Review``
  ("limitation text applies");
* overlay rows cap the result: the parcel gets the more restrictive of base and overlay;
* a parcel near a digitized parking-zone boundary (``near_zone_boundary``) is always ``Review``
  (Pass or Fail: the traced line is approximate).

The reason string always carries the district, result, confidence and citation.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

USES = ("ByRight", "Conditional", "Prohibited", "Unknown")
CONFIDENCE = ("High", "Medium", "Low")
REQUIRED = (
    "jurisdiction",
    "zoning_code",
    "district_name",
    "commercial_parking_use",
    "confidence",
    "confidence_reason",
    "ordinance_citation",
    "verified_date",
    "notes",
)
# Restrictiveness for combining base and overlay (higher = more restrictive).
_RANK = {"ByRight": 0, "Conditional": 1, "Unknown": 2, "Prohibited": 3}
_ROUTE_RANK = {"Pass": 0, "Review": 1, "Fail": 2}


class ZoningTableError(ValueError):
    """Raised for an invalid zoning table."""


@dataclass(frozen=True)
class ZoningRow:
    """One table row."""

    jurisdiction: str
    zoning_code: str
    district_name: str
    use: str
    confidence: str
    confidence_reason: str
    citation: str


@dataclass(frozen=True)
class ZoningResult:
    """Screen result for one parcel."""

    zoning_screen: str  # dm_ZoningScreen
    confidence: str
    route: str  # Pass | Review | Fail
    reason: str
    matched_code: str | None


def _key(code: str) -> str:
    """Normalise a zoning code for matching: upper case, no hyphens/spaces (C-4 -> C4)."""
    return re.sub(r"[\s\-]", "", code.upper())


class ZoningTable:
    """A loaded, validated zoning table for one market."""

    def __init__(self, rows: list[ZoningRow], aliases: dict[str, str] | None = None) -> None:
        self.rows = rows
        self.aliases = {_key(k): v for k, v in (aliases or {}).items()}
        self._by_code: dict[tuple[str, str], ZoningRow] = {}
        for r in rows:
            k = (r.jurisdiction.lower(), _key(r.zoning_code))
            if k in self._by_code:
                raise ZoningTableError(f"duplicate row for {r.jurisdiction} {r.zoning_code}")
            self._by_code[k] = r

    @classmethod
    def load(cls, path: str | Path, aliases: dict[str, str] | None = None) -> ZoningTable:
        """Read and validate a zoning table CSV.

        Args:
            path: CSV path.
            aliases: GIS code -> table code for codes that are not a hyphenation variant
                (e.g. ``{"RURAL": "R"}``); market configuration, not code.

        Raises:
            ZoningTableError: On missing columns or values outside the domains.
        """
        with Path(path).open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ZoningTableError(f"{path}: missing columns {missing}")
            rows = []
            for i, d in enumerate(reader, start=2):
                if d["commercial_parking_use"] not in USES:
                    raise ZoningTableError(
                        f"{path}:{i}: commercial_parking_use "
                        f"{d['commercial_parking_use']!r} not in {USES}"
                    )
                if d["confidence"] not in CONFIDENCE:
                    raise ZoningTableError(
                        f"{path}:{i}: confidence {d['confidence']!r} not in {CONFIDENCE}"
                    )
                rows.append(
                    ZoningRow(
                        d["jurisdiction"].strip(),
                        d["zoning_code"].strip(),
                        d["district_name"],
                        d["commercial_parking_use"],
                        d["confidence"],
                        d["confidence_reason"],
                        d["ordinance_citation"],
                    )
                )
        return cls(rows, aliases)

    def _get(self, jurisdiction: str, code: str) -> ZoningRow | None:
        return self._by_code.get((jurisdiction.lower(), _key(code)))

    def match_code(self, jurisdiction: str, gis_code: str) -> tuple[ZoningRow | None, bool]:
        """Find the table row for a GIS zoning code.

        Order: exact (hyphen-insensitive) -> configured alias -> planned-district density suffix
        (``PUD8`` -> ``PUD``) -> Limited prefix (``LC4`` -> ``C-4``, limited=True). Exact matches
        win, so a district literally named ``LRR`` is never read as ``L`` + ``RR``.

        Returns:
            (row or None, limited flag)
        """
        k = _key(gis_code)
        for cand in (k, _key(self.aliases.get(k, k)), re.sub(r"^(PUD|PC)\d+$", r"\1", k)):
            row = self._get(jurisdiction, cand)
            if row is not None:
                return row, False
        if k.startswith("L") and len(k) > 1:
            base, _ = self.match_code(jurisdiction, k[1:])
            if base is not None:
                return base, True
        return None, False

    def resolve(
        self,
        jurisdiction: str | None,
        gis_code: str | None,
        overlays: list[str] | None = None,
        parking_zone: str | None = None,
        near_zone_boundary: bool = False,
    ) -> ZoningResult:
        """Screen result for one parcel.

        Args:
            jurisdiction: Municipality/township governing zoning (``None`` = unknown).
            gis_code: Zoning code as it appears in the zoning layer (``C4``, ``LC4``, ``UCR``).
            overlays: Overlay codes present on the parcel (e.g. ``["overlay:UCO"]``).
            parking_zone: Downtown parking zone (``"A"``/``"B"``) when known.
            near_zone_boundary: Parcel lies within the review distance of a digitized parking-zone
                boundary (S23c is traced from a code map, so the line is approximate).

        Returns:
            The resolved result.
        """
        juris = (jurisdiction or "").strip()
        own = [r for r in self.rows if r.jurisdiction.lower() == juris.lower()]
        if not juris or not own:
            row = self._get("*", "*")
            return self._result(
                row, route_override=None, extra=[f"jurisdiction {juris or '?'} not in table"]
            )
        row, limited = self.match_code(juris, gis_code) if gis_code else (None, False)
        extra: list[str] = []
        if row is not None and _key(row.zoning_code) == "DD" and parking_zone:
            zrow = self._get(juris, f"DD|ParkingZone{parking_zone.upper()}")
            if zrow is not None:
                row = zrow
        if row is None:
            row = self._get(juris, "*") or self._get("*", "*")
            extra.append(f"code {gis_code!r} not in table")
        result = self._result(
            row,
            route_override="Review" if limited else None,
            extra=["limitation text applies"] if limited else [],
        )
        for ov in overlays or []:
            orow = self._get(juris, ov)
            if orow is None:
                extra.append(f"overlay {ov} not in table")
                continue
            ores = self._result(orow, route_override=None, extra=[])
            if _RANK[ores.zoning_screen] > _RANK[result.zoning_screen]:
                result = ZoningResult(
                    ores.zoning_screen,
                    ores.confidence,
                    result.route,
                    result.reason,
                    result.matched_code,
                )
            route = max(result.route, ores.route, key=_ROUTE_RANK.__getitem__)
            result = ZoningResult(
                result.zoning_screen,
                result.confidence,
                route,
                f"{result.reason}; {ov}: {orow.use} ({orow.confidence_reason})",
                result.matched_code,
            )
        if near_zone_boundary:
            extra.append("near digitized Zone A/B boundary")
        if extra:
            result = ZoningResult(
                result.zoning_screen,
                result.confidence,
                "Review" if near_zone_boundary else result.route,
                f"{result.reason}; " + "; ".join(extra),
                result.matched_code,
            )
        return result

    @staticmethod
    def _result(
        row: ZoningRow | None, route_override: str | None, extra: list[str]
    ) -> ZoningResult:
        if row is None:
            return ZoningResult("Unknown", "Low", "Review", "no zoning table row", None)
        if row.use in ("ByRight", "Conditional"):
            route = "Pass"
        elif row.use == "Unknown" or row.confidence == "Low":
            route = "Review"
        else:
            route = "Fail"
        if route_override:
            route = route_override
        reason = (
            f"{row.zoning_code} {row.use} ({row.confidence}: {row.confidence_reason};"
            f" {row.citation})"
        )
        if extra:
            reason += "; " + "; ".join(extra)
        return ZoningResult(row.use, row.confidence, route, reason, row.zoning_code)
