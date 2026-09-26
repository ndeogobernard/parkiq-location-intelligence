"""S07 parking-app listings and S16 land listings (licensed / terms [VERIFY]). Thin stubs (M2).

* S07 (flag ``data_licenses.parking_apps``): facility listings with rates → SupplyFacilities.
* S16 (flag ``data_licenses.land_listings``): land asking prices → Parcels.listing_price.

With the flag off (default) each takes the not-configured path: a registry row, a WARNING
naming the effect, no rows. Never mocked and never scraped without confirmed terms; with the
flag on, ``standardize`` refuses until written against real-format samples (PLAN Q4/Q5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from parkiq.ingest.base import IngestError, SourceAdapter, Standardized

if TYPE_CHECKING:
    from parkiq.runner import RunContext


class _ListingStub(SourceAdapter):
    def standardize(self, raw: Any, ctx: RunContext) -> Standardized:
        raise IngestError(
            f"{self.source_id} {self.entry.dataset}: licensed but not implemented — needs a "
            "real-format sample file and confirmed terms of use (PLAN Q4/Q5)."
        )


class ParkingListingsAdapter(_ListingStub):
    """S07 — SpotHero / ParkWhiz / ParkMobile facility listings (stub)."""

    source_id = "S07"
    license_flag = "parking_apps"
    downstream_effect = "no listed rates — rate surface uses city meters/other sources only"


class LandListingsAdapter(_ListingStub):
    """S16 — CoStar / LoopNet / Crexi land listings (stub)."""

    source_id = "S16"
    license_flag = "land_listings"
    downstream_effect = "no asking prices — land cost from Auditor values only"
