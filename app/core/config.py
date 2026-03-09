import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///sqlite.db"
    DATABASE_ENGINE_ECHO: bool = False
    DATABASE_ENGINE_CONNECT_ARGS: dict = Field(default_factory=dict)
    DATABASE_ENGINE_KWARGS: dict = Field(default_factory=dict)

    # --- Conditional Logic (Post Initialization) ---

    def model_post_init(self, __context) -> None:
        print(f"Current DATABASE_URL: {self.DATABASE_URL[:10]}...")

        if self.DATABASE_URL.startswith("sqlite"):
            print("Detected SQLite URL, setting check_same_thread=False.")
            self.DATABASE_ENGINE_CONNECT_ARGS = {"check_same_thread": False}
        elif "pymysql" in self.DATABASE_URL:
            print("Detected MySQL URL, setting parameters...")
            self.DATABASE_ENGINE_KWARGS = dict(
                pool_recycle=7200, pool_size=10, max_overflow=5
            )
            print("Setting...", self.DATABASE_ENGINE_KWARGS)
        else:
            print("Detected non-SQLite URL, using default connection args.")
            # If you set DATABASE_ENGINE_CONNECT_ARGS via an env var,
            # the default will be the env var value (which is likely correct)
            # If not, it remains the Field default_factory dict.
            pass

    # temp
    GENERATE_SAMPLE_DATA: bool = True

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MQTT
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
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

    # DO NOT TOUCH BELOW!
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    # REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.example"),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached instance of the Settings object.
    This is the dependency function used throughout the application and overridden during tests.
    """
    if os.getenv("APP_ENV") == "test":
        return Settings(
            DATABASE_URL="sqlite:///test0_sqlite.db",
            DATABASE_ENGINE_ECHO=False,
            DATABASE_ENGINE_CONNECT_ARGS={"check_same_thread": False},
            GENERATE_SAMPLE_DATA=False,
        )
    return Settings()


settings: Settings = get_settings()
