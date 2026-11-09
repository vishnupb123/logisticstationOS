"""Inbound planning: the daily truckfile (planned linehaul trips for an
out-for-delivery date) and ferry-status tracking for ferry-borne trips.

A station's inbound team refreshes the truckfile daily by checking each
ferry-borne trip's sailing against the ferry operator's status. Here that
check goes through the `FerryStatusProvider` protocol; the only shipped
implementation is `SyntheticFerryStatusProvider` (seeded, deterministic) —
consistent with the project's synthetic-data-only rule. A real provider
(an operator's published status feed/API, used within its terms) is a
drop-in adapter, deliberately not built here: scraping real third-party
websites is out of scope for a public, synthetic-data repository.
"""
