"""Live station runtime: long-running, in-memory station-day sessions that
every page, the agent orchestrator and the chat assistant share (ADR-0012).

A session is a *simulated* operating day advancing in real time on a
background thread. Nothing here is persisted except what the agents write to
their playbook; nothing here can act on anything outside the in-memory twin.
"""
