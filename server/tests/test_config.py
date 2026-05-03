from adsb_server.config import Settings, get_settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.postgres_db == "adsb"
    assert s.postgres_host == "localhost"
    assert s.postgres_port == 5432


def test_asyncpg_dsn_format() -> None:
    s = Settings(
        postgres_host="db.example.com",
        postgres_port=5433,
        postgres_db="mydb",
        postgres_user="user",
        postgres_password="secret",
    )
    dsn = s.asyncpg_dsn
    assert dsn.startswith("postgresql://")
    assert "db.example.com:5433" in dsn
    assert "mydb" in dsn
    assert "asyncpg" not in dsn


def test_sqlalchemy_url_format() -> None:
    s = Settings(postgres_user="u", postgres_password="p", postgres_host="h", postgres_db="d")
    url = s.sqlalchemy_url
    assert url.startswith("postgresql+asyncpg://")
    assert "u:p@h" in url
    assert "/d" in url


def test_get_settings_cached() -> None:
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()
