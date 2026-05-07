from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "adsb"
    postgres_user: str = "adsb"
    postgres_password: str = ""

    redis_url: str = "redis://localhost:6379"

    scheduler_cache_dir: Path = Path("/data/cache")
    scheduler_interval_seconds: int = 1800
    scheduler_lookback_days: int = 0  # 0 = unlimited; set to e.g. 7 in dev
    scheduler_keep_traces: bool = False  # keep downloaded tarballs after ingestion

    @property
    def asyncpg_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
