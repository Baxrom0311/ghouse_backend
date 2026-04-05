#!/bin/sh
set -eu

: "${MQTT_USERNAME:?MQTT_USERNAME must be set}"
: "${MQTT_PASSWORD:?MQTT_PASSWORD must be set}"

mosquitto_passwd -b -c /mosquitto/config/passwd "$MQTT_USERNAME" "$MQTT_PASSWORD"

exec /docker-entrypoint.sh mosquitto -c /mosquitto/config/mosquitto.conf
