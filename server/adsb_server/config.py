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

    terrain_data_dir: Path = Path("/data/terrain")

    # Where each batch drops its partition dumps.  Unset disables flight
    # backups entirely (the default, so dev and CI never write them); in
    # production this is a local spool a host timer ships to the backup volume.
    flight_backup_dir: Path | None = None
    # Measured on a real week of this data (2 GB sample, 4 threads):
    #   level  6   4.13x    5s
    #   level  9   4.32x   10s
    #   level 12   4.37x   23s
    #   level 15   4.47x   80s
    #   level 19   5.11x  265s
    # The curve looks like it is flattening at 12 and then is not: 19 wins
    # another 15% over 9, which is ~60 GB across an 18-month backup set. It
    # costs about 50 minutes of CPU for a week's partition, once a week, in a
    # job that is already off the critical path. Worth it; lower it if that
    # ever stops being true.
    flight_backup_zstd_level: int = 19
    # Threads for compression. zstd releases the GIL, so these genuinely run in
    # parallel; 0 would mean single-threaded.
    flight_backup_zstd_workers: int = 4

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
