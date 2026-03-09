import json
from typing import Optional

import paho.mqtt.client as mqtt

from app.core.config import settings


class MQTTService:
    """Service for publishing MQTT commands."""

    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self._connect()

    def _connect(self):
        """Initialize MQTT client connection."""
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        try:
            self.client.connect(
                settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60
            )
            self.client.loop_start()
        except Exception as e:
            self.client = None
            print(f"MQTT connection error: {e}")

    def _ensure_connected(self) -> bool:
        if self.client is None:
            self._connect()
        elif not self.client.is_connected():
            try:
                self.client.reconnect()
            except Exception:
                self._connect()

        return self.client is not None and self.client.is_connected()

    def publish_device_command(self, topic: str, payload):
        """
        Publish a command to control a device.

        Args:
            topic:
            payload:
        """
        if not self._ensure_connected():
            return False

        # Construct command topic: {topic_root}/command
        # command_topic = f"{topic_root}/command"
        command_topic = topic
        # Create command payload
        # payload = {
        #     "device_id": device_id,
        #     "state": state,
        #     "timestamp": None  # Will be set by device
        # }
        if not isinstance(payload, str):
            payload = json.dumps(payload)

        try:
            result = self.client.publish(command_topic, payload, qos=1, retain=False)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"Published command to {command_topic}: {payload}")
                return True
            else:
                print(f"Failed to publish command: {result.rc}")
                return False
        except Exception as e:
            print(f"Error publishing MQTT command: {e}")
            return False

    def disconnect(self):
        """Disconnect MQTT client."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# Global MQTT service instance
mqtt_service = MQTTService()
