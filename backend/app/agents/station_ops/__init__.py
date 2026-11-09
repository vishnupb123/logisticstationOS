"""Station Operations Agent: watches the full-day station twin, detects
risks to DEA / OTD / sort compliance / timely staging, evaluates candidate
mitigations by counterfactual simulation, records what worked in a
persistent playbook (its "learning"), and recommends — or, in the
simulation sandbox only, applies — the best plan. Real operational action
always routes through the human-approval gate (ADR-0009).
"""
