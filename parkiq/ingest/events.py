"""S10 — analyst-maintained venue table: seats and events per year (+ calendar source)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from parkiq.ingest.tables import _TableAdapter

if TYPE_CHECKING:
    pass


class VenuesAdapter(_TableAdapter):
    """S10 — analyst-maintained venue table: seats and events per year (+ calendar source).

    OSM/Overture venue candidates are in ``Places`` for review; seats/events come from here.
    """

    source_id = "S10"
    target, raw_layer, id_field = "Venues", "Raw_Venues", "venue_id"
    required = ("venue_id", "name")
    optional = ("seats", "events_per_year", "event_calendar_source")
    downstream_effect = "no event daypart demand (C03 and event revenue are zero)"
