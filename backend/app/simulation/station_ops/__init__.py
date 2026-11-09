"""Station Operations Twin — a full operating-day digital twin of a
fictional delivery station: linehaul arrival (incl. ferry-borne trips
whose delay comes from the truckfile) -> receive/unload -> induct lines
(scan quality, line downtime) -> sort (missorts) -> stow (WIP band) ->
cycle pick start (which blocks further induct: late volume rolls over)
-> pick -> stage -> depart -> delivery-attempt outcome.

Sits beside, not on top of, the Cycle-1 twin in app/simulation/model.py,
which the Milestone 6 RL environment and Milestone 8 predictive model
depend on byte-for-byte — this package never imports or modifies it.

Same boundaries as every simulation path (ADR-0006/ADR-0002): no
PostgreSQL, no disk; every snapshot is `source_kind="simulated"`. The
API layer may read a truckfile from PostgreSQL and pass it *in* as plain
config, but nothing here ever reads or writes a database.
"""
