# ParkIQ: Parking Lot Site Selection, Franklin County

Part of **ParkIQ: A Parking Lot Site Selection Location Intelligence Analysis**.

Where in Franklin County, Ohio, would a new paid surface parking lot fill up and pay? This
analysis answers that in four stages, each on the walking network rather than in straight lines.

## 1. Where parking is needed

Parking demand comes from 10,350 demand anchors: offices (LODES jobs, adjusted for how many
workers drive and how often they are in the office), hospitals (beds), campuses (enrollment),
hotels (rooms) and restaurants and shops (floor area). Each anchor's demand spreads over the
H3 hexagons its visitors can reach within a 3, 5 or 8-minute walk. Modeled demand across the
county: 382,785 stalls on a weekday daytime, 295,661 on a weekday evening, 254,471 on a weekend
day and 323,153 on a weekend evening.

## 2. Where parking already is

Supply is 6,418 mapped lots and garages (OpenStreetMap, deduplicated, capacity from stated counts
or lot area), 1,864 metered block faces (City of Columbus), and lots estimated on 12,766
commercial parcels that have no mapped parking. Private lots count at half their capacity.

## 3. Where paid parking is short

The gap is demand minus supply in each hexagon and time of week. A **hot zone** is a cluster of
hexagons short of parking on a weekday daytime and again in an evening or at the weekend. Only
places with paid parking within an 8-minute walk (meters, paid lots, operator garages) are a
market for a new paid lot: 6 hot zones qualify, 4 of them short by at least 50 stalls, near Ohio
State, along the Short North to downtown spine, and near Columbus State and Franklin University.
Another 564 zones are short of parking where parking is free; they are mapped for context only.

## 4. Which parcels could become a lot

Every one of 492,935 parcels is screened. A site must be within an 8-minute walk of a paid-market
hot zone (8,438 sites), fit 50 to 300 stalls, be vacant, a surface lot or lightly improved, allow
a parking lot under zoning (or already be one), have street frontage, a workable shape, no
floodway and a gentle slope. Contiguous parcels of the same owner are assembled first (168
assemblies). Land of The Ohio State University fails, because campus parking is under a
long-term concession.

**Result: 48 candidate sites** (2 pass outright, 46 need a review item such as zoning near the
Downtown parking-zone line or an existing lot's legal status). 21 are viable only as existing
surface lots, 13 touch Downtown parking Zone A where new lots are not allowed, and 19 are owned by
public or institutional owners (acquisition likely difficult, ground lease possible).

Candidates are scored on ten criteria (shortage nearby by time of week, competing supply, walk
to the main destinations, land cost per stall, access, zoning certainty and others), ranked under
three weighting scenarios, and tested with 1,000 random weightings. Rates, venues and planned
projects are held neutral until the field rate survey and project data arrive, so the ranking can
still change. Buy and ground lease underwriting (yield, IRR) follows once the finance assumptions
are set.

## Details

* Method choices and their reasons: [`docs/DECISIONS.md`](../DECISIONS.md)
* Open confirmations: [`docs/VERIFY.md`](../VERIFY.md)
* Reproduce the run: [`docs/REPLICATION.md`](../REPLICATION.md)
* Code: [`parkiq/`](../../parkiq/README.md)

Candidate sites and parcel-level results are not published.
