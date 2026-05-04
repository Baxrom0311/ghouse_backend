import json
import logging
import ssl
import threading
import time
from typing import Optional

import certifi
import paho.mqtt.client as mqtt

from app.core.config import settings

logger = logging.getLogger(__name__)
MQTT_CONNECT_TIMEOUT_SECONDS = 5.0
MQTT_CONNECT_POLL_SECONDS = 0.05


class MQTTService:
    """Service for publishing MQTT commands."""

    def __init__(self):
        self.client: Optional[mqtt.Client] = None
        self._lock = threading.RLock()

    def _wait_until_connected(self, client: mqtt.Client) -> bool:
        deadline = time.monotonic() + MQTT_CONNECT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if client.is_connected():
                return True
            time.sleep(MQTT_CONNECT_POLL_SECONDS)
        return client.is_connected()

    def _connect(self):
        """Initialize MQTT client connection."""
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if settings.MQTT_USERNAME:
            client.username_pw_set(
                settings.MQTT_USERNAME,
                settings.MQTT_PASSWORD or None,
            )
        if settings.MQTT_TLS_ENABLED:
            client.tls_set(
                ca_certs=settings.MQTT_TLS_CA_CERTS or certifi.where(),
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            client.tls_insecure_set(False)
        try:
            client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60)
            client.loop_start()
            if not self._wait_until_connected(client):
                logger.warning("MQTT connection timed out waiting for CONNACK")
                client.loop_stop()
                client.disconnect()
                self.client = None
                return
            self.client = client
        except Exception as e:
            self.client = None
            logger.warning("MQTT connection error: %s", e)

    def _ensure_connected(self) -> bool:
        with self._lock:
            if self.client is None:
                self._connect()
            elif not self.client.is_connected():
                try:
                    self.client.reconnect()
                    if not self._wait_until_connected(self.client):
                        logger.warning("MQTT reconnect timed out waiting for CONNACK")
                        self.client.loop_stop()
                        self.client.disconnect()
                        self.client = None
                        self._connect()
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
        with self._lock:
            if not self._ensure_connected():
                return False

            command_topic = topic
            if not isinstance(payload, str):
                payload = json.dumps(payload)

            try:
                result = self.client.publish(command_topic, payload, qos=1, retain=retain)
                result.wait_for_publish(timeout=5)
                if not result.is_published():
                    logger.warning("Timed out publishing MQTT command to %s", command_topic)
                    return False
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    logger.info("Published MQTT message to %s", command_topic)
                    return True
                logger.warning("Failed to publish MQTT command: %s", result.rc)
                return False
            except Exception as e:
                logger.exception("Error publishing MQTT command: %s", e)
                return False

    def disconnect(self):
        """Disconnect MQTT client."""
        with self._lock:
            if self.client:
                self.client.loop_stop()
                self.client.disconnect()
                self.client = None


# Global MQTT service instance
mqtt_service = MQTTService()
