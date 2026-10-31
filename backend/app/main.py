from fastapi import FastAPI

from app.api.routes import health
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing

configure_logging()
configure_tracing()

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(health.router)
