"""S01R — Regrid parcels (licensed; flag ``data_licenses.regrid``). Thin stub (M2).

With the flag off (default) the adapter takes the not-configured path: a registry row, a WARNING
naming the effect, no rows — the county fallback (S01) supplies ``Parcels``. With the flag on,
``standardize`` refuses until it has been written and tested against a real Regrid export
(PLAN Q5: vendor formats are never synthesized).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from parkiq.ingest.base import IngestError, SourceAdapter, Standardized

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class RegridParcelsAdapter(SourceAdapter):
    """S01R — Regrid parcels (stub)."""

    source_id = "S01R"
    license_flag = "regrid"
    downstream_effect = "none while the county fallback (S01) is configured"

    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        raise IngestError(
            "S01R Regrid: licensed but not implemented — needs a real Regrid export sample to "
            "build and test the field mapping against (PLAN Q5). Use the county fallback S01."
        )
