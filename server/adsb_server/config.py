from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_SENTRY_SECRET = Path("/run/secrets/sentry_dsn")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "adsb"
    postgres_user: str = "adsb"
    postgres_password: str = ""

    log_queries: bool = False
    sentry_dsn: str = ""
    environment: str = "production"
    redis_url: str = ""  # empty = cache disabled

    scheduler_cache_dir: Path = Path("/data/cache")
    scheduler_lookback_days: int = 0  # 0 = unlimited; set to e.g. 7 in dev
    scheduler_keep_traces: bool = False  # keep downloaded tarballs after ingestion

    herbie_cache_dir: Path = Path("/data/cache/herbie")
    herbie_keep_cache: bool = False  # keep GRIB files after ingestion (useful for debugging)

    @property
    def effective_sentry_dsn(self) -> str:
        """SENTRY_DSN env var, or /run/secrets/sentry_dsn Docker secret, or empty."""
        if self.sentry_dsn:
            return self.sentry_dsn
        try:
            return _SENTRY_SECRET.read_text().strip()
        except FileNotFoundError:
            return ""

    def init_sentry(self) -> None:
        """Initialise Sentry SDK if a DSN is available. No-op otherwise."""
        if dsn := self.effective_sentry_dsn:
            import sentry_sdk

            sentry_sdk.init(
                dsn=dsn,
                environment=self.environment,
                send_default_pii=False,
                traces_sample_rate=1.0,
                enable_logs=True,
            )

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
