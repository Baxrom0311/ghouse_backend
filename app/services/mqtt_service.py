import json
import logging
import ssl
from typing import Optional

import certifi
import paho.mqtt.client as mqtt

from app.core.config import settings

logger = logging.getLogger(__name__)


class MQTTService:
    """Service for publishing MQTT commands."""

    def __init__(self):
        self.client: Optional[mqtt.Client] = None

    def _connect(self):
        """Initialize MQTT client connection."""
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings.MQTT_USERNAME:
            self.client.username_pw_set(
                settings.MQTT_USERNAME,
                settings.MQTT_PASSWORD or None,
            )
        if settings.MQTT_TLS_ENABLED:
            self.client.tls_set(
                ca_certs=settings.MQTT_TLS_CA_CERTS or certifi.where(),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self.client.tls_insecure_set(False)
        try:
            self.client.connect(
                settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60
            )
            self.client.loop_start()
        except Exception as e:
            self.client = None
            logger.warning("MQTT connection error: %s", e)

    def _ensure_connected(self) -> bool:
        if self.client is None:
            self._connect()
        elif not self.client.is_connected():
            try:
                self.client.reconnect()
            except Exception:
                self._connect()

        return self.client is not None and self.client.is_connected()

    def publish_device_command(self, topic: str, payload, retain: bool = False):
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
            result = self.client.publish(command_topic, payload, qos=1, retain=retain)
            result.wait_for_publish(timeout=5)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info("Published MQTT message to %s", command_topic)
                return True
            else:
                logger.warning("Failed to publish MQTT command: %s", result.rc)
                return False
        except Exception as e:
            logger.exception("Error publishing MQTT command: %s", e)
            return False

    def disconnect(self):
        """Disconnect MQTT client."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# Global MQTT service instance
mqtt_service = MQTTService()
