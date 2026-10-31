from functools import lru_cache

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
    postgres_password: str = "stationos"
    postgres_db: str = "stationos"

    duckdb_path: str = "../data/analytics/stationos.duckdb"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
