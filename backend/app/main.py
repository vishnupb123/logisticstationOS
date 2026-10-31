from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, analytics, decisions, health, rl, simulation
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing

configure_logging()
configure_tracing()

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Local-first, single-operator tool, not a public multi-tenant service
# (app/core/config.py::Settings.cors_allowed_origins) — a narrow,
# explicit allow-list for a local Vite dev server, not a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analytics.router)
app.include_router(agents.router)
app.include_router(simulation.router)
app.include_router(rl.router)
app.include_router(decisions.router)
