"""Runtime settings from COUNTERSIGN_* environment variables. Everything has a working default
for a single machine; a team deployment sets COUNTERSIGN_DATABASE_URL to PostgreSQL."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COUNTERSIGN_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    database_url: str = ""  # defaults to SQLite in data_dir
    model: str = "claude-opus-5-5"
    max_agent_turns: int = 30
    github_api_url: str = "https://api.github.com"

    # Claude Opus 5.5 list prices in USD per million tokens, for cost estimates only.
    price_input_per_mtok: float = 4.0
    price_output_per_mtok: float = 20.0
    price_cache_read_per_mtok: float = 0.20

    # Run agents inside the API process. Fine on one machine; a team deployment turns this off
    # and runs `python -m app.worker` separately, so restarting the API never touches agents.
    embedded_worker: bool = True
    worker_concurrency: int = 4
    worker_poll_seconds: float = 1.0
    run_max_attempts: int = 3
    heartbeat_seconds: float = 15.0
    lease_seconds: float = 90.0
    retry_base_seconds: float = 30.0

    @model_validator(mode="after")
    def _default_database(self) -> "Settings":
        if not self.database_url:
            # Filename predates the rename. Existing installs keep their data and audit chain.
            self.database_url = f"sqlite:///{self.data_dir / 'foreman.db'}"
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
