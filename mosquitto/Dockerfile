FROM eclipse-mosquitto:2

COPY config/mosquitto.conf /mosquitto/config/mosquitto.conf
COPY start-mosquitto.sh /usr/local/bin/start-mosquitto.sh

RUN chmod +x /usr/local/bin/start-mosquitto.sh

ENTRYPOINT ["/usr/local/bin/start-mosquitto.sh"]
