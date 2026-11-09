from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    agents,
    analytics,
    decisions,
    health,
    rl,
    runtime,
    simulation,
    station_ops,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing

configure_logging()
configure_tracing()

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Live sessions' agents write their evaluations to the playbook (learning).
    from app.db.postgres import SessionLocal
    from app.runtime.session import manager

    manager.session_factory = SessionLocal
    yield
    manager.stop_all()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

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
app.include_router(station_ops.router)
app.include_router(runtime.router)
