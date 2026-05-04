import pytest

from app.core.config import Settings

PRODUCTION_API_KEY = "deepseek-production-key"


def test_cors_origins_accepts_comma_separated_values():
    settings = Settings(CORS_ORIGINS="https://app.example.com, https://admin.example.com")

    assert settings.CORS_ORIGINS == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_mcp_is_disabled_by_default():
    settings = Settings()

    assert settings.ENABLE_MCP is False


def test_production_requires_strong_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="postgresql://user:pass@db:5432/app",
            SECRET_KEY="change-me-before-production",
            CORS_ORIGINS="https://app.example.com",
            ALLOWED_HOSTS="app.example.com",
            DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        )


def test_production_rejects_example_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="postgresql://user:pass@db:5432/app",
            SECRET_KEY="change-me-before-production-minimum-32-characters",
            CORS_ORIGINS="https://app.example.com",
            ALLOWED_HOSTS="app.example.com",
            DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        )


def test_production_requires_deepseek_api_key():
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="postgresql://user:pass@db:5432/app",
            SECRET_KEY="x" * 32,
            CORS_ORIGINS="https://app.example.com",
            ALLOWED_HOSTS="app.example.com",
            DEEPSEEK_API_KEY="DEEPSEEK_API_KEY",
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="postgresql://user:pass@db:5432/app",
            SECRET_KEY="x" * 32,
            CORS_ORIGINS="*",
            ALLOWED_HOSTS="app.example.com",
            DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        )


def test_production_accepts_strong_secret_and_cors():
    settings = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@db:5432/app",
        SECRET_KEY="x" * 32,
        CORS_ORIGINS="https://app.example.com",
        ALLOWED_HOSTS="app.example.com",
        DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        MQTT_USERNAME="broker-user",
        MQTT_PASSWORD="broker-password",
    )

    assert settings.is_production is True
    assert settings.CORS_ORIGINS == ["https://app.example.com"]
    assert settings.ALLOWED_HOSTS == ["app.example.com"]
    assert settings.RUN_MIGRATIONS_ON_STARTUP is False


def test_production_can_enable_startup_migrations(monkeypatch):
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "true")
    settings = Settings(
        APP_ENV="production",
        DATABASE_URL="postgresql://user:pass@db:5432/app",
        SECRET_KEY="x" * 32,
        CORS_ORIGINS="https://app.example.com",
        ALLOWED_HOSTS="app.example.com",
        DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        MQTT_USERNAME="broker-user",
        MQTT_PASSWORD="broker-password",
    )

    assert settings.RUN_MIGRATIONS_ON_STARTUP is True


def test_production_rejects_sqlite_database():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="sqlite:///prod.db",
            SECRET_KEY="x" * 32,
            CORS_ORIGINS="https://app.example.com",
            ALLOWED_HOSTS="app.example.com",
            DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        )


def test_production_rejects_wildcard_allowed_hosts():
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="postgresql://user:pass@db:5432/app",
            SECRET_KEY="x" * 32,
            CORS_ORIGINS="https://app.example.com",
            ALLOWED_HOSTS="*",
            DEEPSEEK_API_KEY=PRODUCTION_API_KEY,
        )
