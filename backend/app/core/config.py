from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env.

    Only Milestone 1 concerns live here: identity, logging, and the two
    local-first data stores (PostgreSQL for operational state, DuckDB for
    analytics). Later milestones add settings alongside the features that
    need them rather than pre-declaring unused config.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "StationOS"
    env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "stationos"
    # SecretStr (Milestone 9 secure-configuration review) — masks the
    # value out of repr()/str()/logs by default; docs/SECURITY_AND_GOVERNANCE.md
    # already said "never log a full Settings object," this makes that
    # true even if something does by accident.
    postgres_password: SecretStr = SecretStr("stationos")
    postgres_db: str = "stationos"

    duckdb_path: str = "../data/analytics/stationos.duckdb"

    # LLMProvider (ADR-0008): the first real adapter targets a local
    # Ollama server — no API key, true local-first, per the project
    # owner's explicit choice (docs/OPEN_QUESTIONS.md). Not installed on
    # every dev machine by default; see docs/AGENTIC_ARCHITECTURE.md for
    # setup and the FakeLLMProvider used where no live server is needed.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
