import json
import logging
import os
from typing import Annotated
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:4173",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
]
PLACEHOLDER_SECRETS = {
    "",
    "change-me-before-production",
    "dev-secret-key-change-me-in-production",
}


class Settings(BaseSettings):
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite:///sqlite.db"
    DATABASE_ENGINE_ECHO: bool = False
    DATABASE_ENGINE_CONNECT_ARGS: dict = Field(default_factory=dict)
    DATABASE_ENGINE_KWARGS: dict = Field(default_factory=dict)

    # --- Conditional Logic (Post Initialization) ---

    def model_post_init(self, __context) -> None:
        if self.DATABASE_URL.startswith("sqlite") and not self.DATABASE_ENGINE_CONNECT_ARGS:
            self.DATABASE_ENGINE_CONNECT_ARGS = {"check_same_thread": False}
        elif "pymysql" in self.DATABASE_URL and not self.DATABASE_ENGINE_KWARGS:
            self.DATABASE_ENGINE_KWARGS = dict(
                pool_recycle=7200, pool_size=10, max_overflow=5
            )

        if not self.CORS_ORIGINS and not self.is_production:
            self.CORS_ORIGINS = list(DEV_CORS_ORIGINS)

        if bool(self.MQTT_USERNAME) != bool(self.MQTT_PASSWORD):
            raise ValueError(
                "MQTT_USERNAME and MQTT_PASSWORD must both be set or both be empty."
            )

        if self.is_production:
            secret_key = self.SECRET_KEY.strip()
            if secret_key in PLACEHOLDER_SECRETS or len(secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY must be set to a strong value with at least 32 characters in production."
                )

            if not self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must be set in production.")

            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS cannot contain '*' in production.")

    # temp
    GENERATE_SAMPLE_DATA: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MQTT
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    DEFAULT_MQTT_TOPIC_ID: str = "1"

    # OpenAI
    OPENAI_API_KEY: str = "OPENAI_API_KEY"

    # Gemini
    GOOGLE_API_KEY: str = "GOOGLE_API_KEY"

    # Deepseek
    DEEPSEEK_API_KEY: str = "DEEPSEEK_API_KEY"

    # AI Settings
    AI_MODEL_NAME: str = "gemini-2.5-flash"
    AI_CHAT_MODEL: str = "deepseek-chat"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-me-in-production"
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # DO NOT TOUCH BELOW!
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    # REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=(".env.example", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @field_validator("APP_ENV", mode="before")
    @classmethod
    def normalize_app_env(cls, value: str | None) -> str:
        return str(value or "development").strip().lower()

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str | None) -> str:
        return str(value or "INFO").strip().upper()

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value in (None, "", []):
            return []

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return []
            if normalized.startswith("["):
                parsed = json.loads(normalized)
                if not isinstance(parsed, list):
                    raise ValueError("CORS_ORIGINS JSON value must be a list.")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in normalized.split(",") if item.strip()]

        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        raise ValueError("Unsupported CORS_ORIGINS format.")


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings object.
    This is the dependency function used throughout the application and overridden during tests.
    """
    if os.getenv("APP_ENV") == "test":
        return Settings(
            APP_ENV="test",
            DATABASE_URL="sqlite:///test0_sqlite.db",
            DATABASE_ENGINE_ECHO=False,
            DATABASE_ENGINE_CONNECT_ARGS={"check_same_thread": False},
            GENERATE_SAMPLE_DATA=False,
        )
    return Settings()


settings: Settings = get_settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
