import json
import logging
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlmodel import Session, select

from app.core.config import configure_logging, settings
from app.core.db import engine
from app.models.greenhouse import Greenhouse
from app.models.telemetry import Telemetry
from app.services.device_registry import ensure_greenhouse_devices
from app.services.mqtt_service import mqtt_service

INVALID_MQTT_TOPIC_ID_CHARS = {"/", "+", "#"}
TOPIC_ID_UPDATE_SUFFIX = "/system/topic_id"
TOPIC_ID_ACK_SUFFIX = f"{TOPIC_ID_UPDATE_SUFFIX}/ack"

logger = logging.getLogger(__name__)


def parse_state_topic_id(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) != 2 or parts[1] != "state":
        return None

    return parts[0]


def parse_topic_id_ack_topic(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) != 4:
        return None
    if parts[1:] != ["system", "topic_id", "ack"]:
        return None
    return parts[0]


def topic_id_is_valid(topic_id: str) -> bool:
    return bool(topic_id) and not any(
        char in topic_id for char in INVALID_MQTT_TOPIC_ID_CHARS
    )


def parse_topic_change_payload(payload: str) -> tuple[str | None, str | None]:
    normalized_payload = payload.strip()
    if not normalized_payload:
        return None, None

    try:
        data = json.loads(normalized_payload)
    except json.JSONDecodeError:
        return normalized_payload, None

    if not isinstance(data, dict):
        return None, None

    topic_id = str(data.get("topic_id") or "").strip() or None
    token = str(data.get("token") or "").strip() or None
    return topic_id, token


def clear_retained_topic_change_messages(
    current_topic_id: str, pending_topic_id: str
) -> None:
    mqtt_service.publish_device_command(
        f"{current_topic_id}{TOPIC_ID_UPDATE_SUFFIX}",
        "",
        retain=True,
    )
    mqtt_service.publish_device_command(
        f"{pending_topic_id}{TOPIC_ID_ACK_SUFFIX}",
        "",
        retain=True,
    )


def apply_topic_id_ack(
    session: Session, ack_topic_id: str, payload: str
) -> bool:
    new_topic_id, ack_token = parse_topic_change_payload(payload)
    if not topic_id_is_valid(new_topic_id or "") or not ack_token:
        logger.warning("Ignoring invalid topic id ack payload: %r", payload)
        return False

    greenhouse = session.exec(
        select(Greenhouse)
        .where(Greenhouse.pending_mqtt_topic_id == ack_topic_id)
        .where(Greenhouse.mqtt_topic_update_token == ack_token)
    ).first()
    if greenhouse is None:
        logger.warning(
            "Skipping topic id ack for unknown pending topic id or token mismatch: %s",
            ack_topic_id,
        )
        return False

    pending_topic_id = (greenhouse.pending_mqtt_topic_id or "").strip()
    pending_token = (greenhouse.mqtt_topic_update_token or "").strip()
    if not pending_topic_id or not pending_token:
        logger.warning(
            "Skipping topic id ack because greenhouse=%s has no pending migration",
            greenhouse.id,
        )
        return False

    if (
        new_topic_id != pending_topic_id
        or ack_topic_id != pending_topic_id
        or ack_token != pending_token
    ):
        logger.warning(
            "Skipping topic id ack because payload does not match the pending migration "
            "for greenhouse=%s",
            greenhouse.id,
        )
        return False

    current_topic_id = (greenhouse.mqtt_topic_id or "").strip()

    conflict = session.exec(
        select(Greenhouse)
        .where(Greenhouse.mqtt_topic_id == new_topic_id)
        .where(Greenhouse.id != greenhouse.id)
    ).first()
    if conflict is not None:
        logger.warning(
            "Skipping topic id ack because target topic id is already in use: "
            "%s",
            new_topic_id,
        )
        return False

    greenhouse.mqtt_topic_id = new_topic_id
    greenhouse.pending_mqtt_topic_id = None
    greenhouse.mqtt_topic_update_token = None
    session.add(greenhouse)
    session.commit()
    session.refresh(greenhouse)
    ensure_greenhouse_devices(session, greenhouse)
    clear_retained_topic_change_messages(current_topic_id, new_topic_id)
    logger.info(
        "Applied topic id migration for greenhouse=%s: %s -> %s",
        greenhouse.id,
        current_topic_id,
        new_topic_id,
    )
    return True


def parse_optional_bool(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False

    return None


def wait_for_db():
    """Wait for database to be ready."""
    max_retries = 30
    retry_count = 0

    while retry_count < max_retries:
        try:
            with Session(engine) as session:
                # Try a simple query
                session.exec(select(Greenhouse).limit(1))
            logger.info("Database connection established")
            return True
        except Exception as e:
            retry_count += 1
            logger.warning(
                "Waiting for database... (%s/%s)",
                retry_count,
                max_retries,
            )
            if retry_count >= max_retries:
                logger.exception("Failed to connect to database: %s", e)
                return False
            time.sleep(2)

    return False


def on_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects."""
    if rc == 0:
        logger.info("Connected to MQTT broker")
        client.subscribe("+/state", qos=1)
        client.subscribe(f"+{TOPIC_ID_ACK_SUFFIX}", qos=1)
        logger.info("Subscribed to telemetry topics")
    else:
        logger.warning("Failed to connect to MQTT broker, return code %s", rc)


def on_message(client, userdata, msg):
    """Callback when MQTT message is received."""
    try:
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        telemetry_topic_id = parse_state_topic_id(topic)
        topic_id_ack_source = parse_topic_id_ack_topic(topic)

        if telemetry_topic_id is None and topic_id_ack_source is None:
            logger.warning("Unsupported topic: %s", topic)
            return

        logger.debug("Received message on topic: %s", topic)
        logger.debug("Payload: %s", payload)

        with Session(engine) as session:
            if topic_id_ack_source is not None:
                apply_topic_id_ack(session, topic_id_ack_source, payload)
                return

            # Parse JSON payload
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as e:
                logger.warning("Error parsing JSON payload: %s", e)
                return

            statement = select(Greenhouse).where(
                Greenhouse.mqtt_topic_id == telemetry_topic_id
            )
            greenhouses = session.exec(statement).all()
            if not greenhouses:
                logger.warning(
                    "Skipping telemetry for unknown topic id: %s",
                    telemetry_topic_id,
                )
                return
            if len(greenhouses) > 1:
                logger.warning(
                    "Skipping telemetry for duplicate topic id: %s",
                    telemetry_topic_id,
                )
                return
            greenhouse = greenhouses[0]

            # Extract telemetry data

            air = data.get("air")
            light = data.get("light")
            temperature = data.get("temperature")
            humidity = data.get("humidity")
            moisture = data.get("moisture")

            soil_water_pump = parse_optional_bool(data.get("soil_water_pump"))
            air_water_pump = parse_optional_bool(data.get("air_water_pump"))
            led = parse_optional_bool(data.get("led"))
            fan = parse_optional_bool(data.get("fan"))

            ai_mode = parse_optional_bool(data.get("ai_mode"))

            # Parse timestamp if provided, otherwise use current time
            timestamp = datetime.utcnow()
            if "timestamp" in data:
                try:
                    if isinstance(data["timestamp"], str):
                        parsed_timestamp = datetime.fromisoformat(
                            data["timestamp"].replace("Z", "+00:00")
                        )
                        timestamp = parsed_timestamp.astimezone(timezone.utc).replace(
                            tzinfo=None
                        )
                    elif isinstance(data["timestamp"], (int, float)):
                        timestamp = datetime.fromtimestamp(
                            data["timestamp"], tz=timezone.utc
                        ).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass  # Use current time if parsing fails

            # Create telemetry record
            telemetry = Telemetry(
                greenhouse_id=greenhouse.id,
                time=timestamp,
                air=air,
                light=light,
                temperature=temperature,
                humidity=humidity,
                moisture=moisture,
                # Actuators
                soil_water_pump=soil_water_pump,
                air_water_pump=air_water_pump,
                led=led,
                fan=fan,
                ai_mode=ai_mode,
            )

            session.add(telemetry)
            session.commit()

            logger.debug("Inserted telemetry: %s", telemetry.model_dump())

    except Exception as e:
        logger.exception("Error processing message: %s", e)


def on_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects."""
    logger.warning("Disconnected from MQTT broker (rc: %s)", rc)


def main():
    """Main function to run the MQTT ingestion worker."""
    configure_logging()
    logger.info("Starting MQTT Ingestion Worker")
    logger.info(
        "MQTT Broker: %s:%s",
        settings.MQTT_BROKER_HOST,
        settings.MQTT_BROKER_PORT,
    )

    # Wait for database to be ready
    if not wait_for_db():
        logger.error("Failed to connect to database. Exiting.")
        sys.exit(1)

    # Create MQTT client
    client = mqtt.Client()
    if settings.MQTT_USERNAME:
        client.username_pw_set(
            settings.MQTT_USERNAME,
            settings.MQTT_PASSWORD or None,
        )
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Connect to MQTT broker
    try:
        client.connect(
            settings.MQTT_BROKER_HOST,
            settings.MQTT_BROKER_PORT,
            60,  # Keepalive
        )
    except Exception as e:
        logger.exception("Error connecting to MQTT broker: %s", e)
        sys.exit(1)

    # Start the loop
    logger.info("Starting MQTT client loop")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down MQTT worker")
        client.disconnect()
        sys.exit(0)


if __name__ == "__main__":
    main()
