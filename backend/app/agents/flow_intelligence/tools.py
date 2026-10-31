"""The Flow Intelligence Agent's complete, explicit tool allow-list
(docs/AGENTIC_ARCHITECTURE.md §"Tool permissions") — exactly these five
functions, each wrapping one typed query from
app/analytics/duckdb_queries.py. There is no generic "run a query"
tool, and gather_evidence (app/agents/flow_intelligence/agent.py) calls
nothing else — the allow-list is enforced by what the code imports, not
a runtime permission check.
"""

from app.analytics import duckdb_queries


def query_jackpot_volume(duckdb_path: str) -> dict:
    return duckdb_queries.get_jackpot_volume(duckdb_path).model_dump(mode="json")


def query_wips(duckdb_path: str) -> dict:
    return duckdb_queries.get_wips(duckdb_path).model_dump(mode="json")


def query_induct_throughput(duckdb_path: str) -> list[dict]:
    return [b.model_dump(mode="json") for b in duckdb_queries.get_induct_throughput(duckdb_path)]


def query_stow_throughput(duckdb_path: str) -> list[dict]:
    return [b.model_dump(mode="json") for b in duckdb_queries.get_stow_throughput(duckdb_path)]


def query_parcel_dwell_time(duckdb_path: str) -> dict:
    return duckdb_queries.get_parcel_dwell_time_stats(duckdb_path).model_dump(mode="json")
