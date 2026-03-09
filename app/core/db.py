from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.core.config import settings

from .fake_db import generate_sample_data

BASE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BASE_DIR / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = BASE_DIR / "alembic"

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ENGINE_ECHO,
    pool_pre_ping=True,
    connect_args=settings.DATABASE_ENGINE_CONNECT_ARGS,
    **settings.DATABASE_ENGINE_KWARGS,
)


def build_unique_topic_id(
    used_topic_ids: set[str], greenhouse_id: int, prefer_default: bool = False
) -> str:
    candidate_topic_ids = []
    if prefer_default and settings.DEFAULT_MQTT_TOPIC_ID not in used_topic_ids:
        candidate_topic_ids.append(settings.DEFAULT_MQTT_TOPIC_ID)

    candidate_topic_ids.append(f"greenhouse-{greenhouse_id}")

    for candidate in candidate_topic_ids:
        if candidate not in used_topic_ids:
            used_topic_ids.add(candidate)
            return candidate

    suffix = 1
    while True:
        candidate = f"greenhouse-{greenhouse_id}-{suffix}"
        if candidate not in used_topic_ids:
            used_topic_ids.add(candidate)
            return candidate
        suffix += 1


def run_db_migrations():
    alembic_config = Config(str(ALEMBIC_INI_PATH))
    alembic_config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    alembic_config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    command.upgrade(alembic_config, "head")


def ensure_schema_compatibility():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "greenhouse" not in table_names:
        return

    greenhouse_columns = {
        column["name"] for column in inspector.get_columns("greenhouse")
    }

    if "mqtt_topic_id" not in greenhouse_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE greenhouse ADD COLUMN mqtt_topic_id VARCHAR")
            )

    if "device" in table_names:
        device_columns = {column["name"] for column in inspector.get_columns("device")}
        with engine.begin() as connection:
            if "min_value" not in device_columns:
                connection.execute(
                    text("ALTER TABLE device ADD COLUMN min_value FLOAT")
                )
            if "max_value" not in device_columns:
                connection.execute(
                    text("ALTER TABLE device ADD COLUMN max_value FLOAT")
                )

    from app.models.greenhouse import Greenhouse

    with Session(engine) as session:
        greenhouses = session.exec(select(Greenhouse).order_by(Greenhouse.id)).all()
        used_topic_ids: set[str] = set()
        single_greenhouse = len(greenhouses) == 1

        for greenhouse in greenhouses:
            topic_id = (greenhouse.mqtt_topic_id or "").strip()
            if not topic_id:
                greenhouse.mqtt_topic_id = build_unique_topic_id(
                    used_topic_ids,
                    greenhouse.id,
                    prefer_default=single_greenhouse and not used_topic_ids,
                )
                session.add(greenhouse)
                continue

            if topic_id in used_topic_ids:
                greenhouse.mqtt_topic_id = build_unique_topic_id(
                    used_topic_ids,
                    greenhouse.id,
                    prefer_default=single_greenhouse and not used_topic_ids,
                )
                session.add(greenhouse)
                continue

            greenhouse.mqtt_topic_id = topic_id
            used_topic_ids.add(topic_id)
            session.add(greenhouse)

        session.commit()

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_greenhouse_mqtt_topic_id ON greenhouse (mqtt_topic_id)"
            )
        )


def create_db_and_tables():
    """Create database tables."""
    run_db_migrations()
    ensure_schema_compatibility()
    if settings.GENERATE_SAMPLE_DATA:
        generate_sample_data(engine)


def db_drop_all():
    SQLModel.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def get_session():
    """Dependency to get database session."""
    with Session(engine) as session:
        yield session
