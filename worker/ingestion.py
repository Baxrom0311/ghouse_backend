import json
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlmodel import Session, select

from app.core.config import settings
from app.models.greenhouse import Greenhouse
from app.models.telemetry import Telemetry
from app.core.db import engine

def parse_mqtt_topic_id(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) != 2 or parts[1] != "state":
        return None

    return parts[0]


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
            print("Database connection established")
            return True
        except Exception as e:
            retry_count += 1
            print(f"Waiting for database... ({retry_count}/{max_retries})")
            if retry_count >= max_retries:
                print(f"Failed to connect to database: {e}")
                return False
            time.sleep(2)

    return False


def on_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects."""
    if rc == 0:
        print("Connected to MQTT broker")
        client.subscribe("+/state", qos=1)
        print("Subscribed to telemetry topics")
    else:
        print(f"Failed to connect to MQTT broker, return code {rc}")


def on_message(client, userdata, msg):
    """Callback when MQTT message is received."""
    try:
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        mqtt_topic_id = parse_mqtt_topic_id(topic)

        if mqtt_topic_id is None:
            print(f"Unsupported topic: {topic}")
            return

        print(f"Received message on topic: {topic}")
        print(f"Payload: {payload}")

        # Parse JSON payload
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON payload: {e}")
            return

        # Get database session
        with Session(engine) as session:
            statement = select(Greenhouse).where(
                Greenhouse.mqtt_topic_id == mqtt_topic_id
            )
            greenhouses = session.exec(statement).all()
            if not greenhouses:
                print(f"Skipping telemetry for unknown topic id: {mqtt_topic_id}")
                return
            if len(greenhouses) > 1:
                print(f"Skipping telemetry for duplicate topic id: {mqtt_topic_id}")
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

            print(f"Inserted telemetry: {telemetry.model_dump()}")

    except Exception as e:
        print(f"Error processing message: {e}")
        import traceback

        traceback.print_exc()


def on_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects."""
    print(f"Disconnected from MQTT broker (rc: {rc})")


def main():
    """Main function to run the MQTT ingestion worker."""
    print("Starting MQTT Ingestion Worker...")
    print(f"Database URL: {settings.DATABASE_URL}")
    print(f"MQTT Broker: {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")

    # Wait for database to be ready
    if not wait_for_db():
        print("Failed to connect to database. Exiting.")
        sys.exit(1)

    # Create MQTT client
    client = mqtt.Client()
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
        print(f"Error connecting to MQTT broker: {e}")
        sys.exit(1)

    # Start the loop
    print("Starting MQTT client loop...")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nShutting down MQTT worker...")
        client.disconnect()
        sys.exit(0)


if __name__ == "__main__":
    main()
