import pytest

from app.core.config import Settings


def test_cors_origins_accepts_comma_separated_values():
    settings = Settings(CORS_ORIGINS="https://app.example.com, https://admin.example.com")

    assert settings.CORS_ORIGINS == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_production_requires_strong_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(
            APP_ENV="production",
            SECRET_KEY="change-me-before-production",
            CORS_ORIGINS="https://app.example.com",
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(
            APP_ENV="production",
            SECRET_KEY="x" * 32,
            CORS_ORIGINS="*",
        )


def test_production_accepts_strong_secret_and_cors():
    settings = Settings(
        APP_ENV="production",
        SECRET_KEY="x" * 32,
        CORS_ORIGINS="https://app.example.com",
        MQTT_USERNAME="broker-user",
        MQTT_PASSWORD="broker-password",
    )

    assert settings.is_production is True
    assert settings.CORS_ORIGINS == ["https://app.example.com"]
