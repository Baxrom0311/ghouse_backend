import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.api.routes import device as device_route
from app.api.routes import greenhouse as greenhouse_route
from app.models import Device, Greenhouse, Plant, Telemetry
from worker.ingestion import apply_topic_id_ack


def test_create_greenhouse(login_client: TestClient, db_session: Session):
    res = login_client.post("/api/greenhouses", json={"name": "Greenhouse 4592899jf9e"})

    stm = select(Greenhouse).where(Greenhouse.name == "Greenhouse 4592899jf9e")
    assert db_session.exec(stm).first()
    assert res.status_code == 201


def test_create_greenhouse_prefers_default_topic_when_available(
    login_client: TestClient,
    db_session: Session,
):
    db_session.exec(delete(Device))
    db_session.exec(delete(Plant))
    db_session.exec(delete(Telemetry))
    db_session.exec(delete(Greenhouse))
    db_session.commit()

    first_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Existing Greenhouse", "mqtt_topic_id": "legacy-topic"},
    )
    assert first_response.status_code == 201

    second_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Default Topic Greenhouse"},
    )

    assert second_response.status_code == 201
    assert (
        second_response.json()["mqtt_topic_id"]
        == greenhouse_route.settings.DEFAULT_MQTT_TOPIC_ID
    )

    second_greenhouse = db_session.exec(
        select(Greenhouse).where(Greenhouse.name == "Default Topic Greenhouse")
    ).first()
    assert second_greenhouse is not None
    assert second_greenhouse.mqtt_topic_id == greenhouse_route.settings.DEFAULT_MQTT_TOPIC_ID


def test_device_settings_persist_after_reads(
    login_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        lambda *args, **kwargs: True,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Persistence Greenhouse"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.post(
        f"/api/greenhouses/{greenhouse_id}/devices/temperature/settings",
        json={"min": 19, "max": 27},
    )
    assert update_response.status_code == 200

    greenhouse_response = login_client.get(f"/api/greenhouses/{greenhouse_id}")
    assert greenhouse_response.status_code == 200

    devices_response = login_client.get(f"/api/greenhouses/{greenhouse_id}/devices")
    assert devices_response.status_code == 200

    temperature_device = next(
        device
        for device in devices_response.json()
        if device["name"] == "temperature"
    )
    assert temperature_device["min_value"] == 19
    assert temperature_device["max_value"] == 27


def test_greenhouse_topic_change_publishes_migration_command(
    login_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    published_commands: list[tuple[str, object, bool]] = []

    def fake_publish(topic: str, payload: object, retain: bool = False) -> bool:
        published_commands.append((topic, payload, retain))
        return True

    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        fake_publish,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Migrating Greenhouse", "mqtt_topic_id": "device-1"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.patch(
        f"/api/greenhouses/{greenhouse_id}",
        json={"mqtt_topic_id": "device-2"},
    )

    assert update_response.status_code == 200
    assert len(published_commands) == 1
    assert published_commands[0][0] == "device-1/system/topic_id"
    assert published_commands[0][2] is True
    assert published_commands[0][1]["topic_id"] == "device-2"
    assert published_commands[0][1]["token"]
    assert update_response.json()["mqtt_topic_id"] == "device-1"

    greenhouse = db_session.get(Greenhouse, greenhouse_id)
    assert greenhouse is not None
    assert greenhouse.mqtt_topic_id == "device-1"
    assert greenhouse.pending_mqtt_topic_id == "device-2"
    assert greenhouse.mqtt_topic_update_token

    payload = {
        "topic_id": "device-2",
        "token": greenhouse.mqtt_topic_update_token,
    }
    assert apply_topic_id_ack(db_session, "device-2", json.dumps(payload)) is True

    db_session.refresh(greenhouse)
    assert greenhouse.mqtt_topic_id == "device-2"
    assert greenhouse.pending_mqtt_topic_id is None
    assert greenhouse.mqtt_topic_update_token is None

    fan_device = db_session.exec(
        select(Device)
        .where(Device.greenhouse_id == greenhouse_id)
        .where(Device.name == "fan")
    ).first()
    assert fan_device is not None
    assert fan_device.topic_root == "device-2/fan"


def test_greenhouse_topic_change_ack_requires_matching_pending_token(
    login_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        lambda *args, **kwargs: True,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Protected Migration Greenhouse", "mqtt_topic_id": "device-11"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.patch(
        f"/api/greenhouses/{greenhouse_id}",
        json={"mqtt_topic_id": "device-12"},
    )
    assert update_response.status_code == 200

    greenhouse = db_session.get(Greenhouse, greenhouse_id)
    assert greenhouse is not None
    original_token = greenhouse.mqtt_topic_update_token

    assert apply_topic_id_ack(
        db_session,
        "device-12",
        '{"topic_id":"device-12","token":"wrong-token"}',
    ) is False

    db_session.refresh(greenhouse)
    assert greenhouse.mqtt_topic_id == "device-11"
    assert greenhouse.pending_mqtt_topic_id == "device-12"
    assert greenhouse.mqtt_topic_update_token == original_token


def test_greenhouse_topic_change_ack_requires_token(
    login_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        lambda *args, **kwargs: True,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Token Migration Greenhouse", "mqtt_topic_id": "device-21"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.patch(
        f"/api/greenhouses/{greenhouse_id}",
        json={"mqtt_topic_id": "device-22"},
    )
    assert update_response.status_code == 200

    assert (
        apply_topic_id_ack(
            db_session,
            "device-22",
            '{"topic_id":"device-22"}',
        )
        is False
    )

    greenhouse = db_session.get(Greenhouse, greenhouse_id)
    assert greenhouse is not None
    assert greenhouse.mqtt_topic_id == "device-21"
    assert greenhouse.pending_mqtt_topic_id == "device-22"


def test_greenhouse_topic_id_reserved_during_pending_migration(
    login_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        lambda *args, **kwargs: True,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Pending Source Greenhouse", "mqtt_topic_id": "device-31"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.patch(
        f"/api/greenhouses/{greenhouse_id}",
        json={"mqtt_topic_id": "device-32"},
    )
    assert update_response.status_code == 200

    conflicting_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Conflicting Greenhouse", "mqtt_topic_id": "device-32"},
    )
    assert conflicting_response.status_code == 400
    assert conflicting_response.json()["detail"] == "mqtt_topic_id already in use"


def test_greenhouse_topic_change_publish_failure_does_not_persist_other_updates(
    login_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        device_route.mqtt_service,
        "publish_device_command",
        lambda *args, **kwargs: False,
    )

    create_response = login_client.post(
        "/api/greenhouses",
        json={"name": "Stable Greenhouse", "mqtt_topic_id": "device-41"},
    )
    greenhouse_id = create_response.json()["id"]

    update_response = login_client.patch(
        f"/api/greenhouses/{greenhouse_id}",
        json={
            "name": "Should Not Persist",
            "ai_mode": True,
            "mqtt_topic_id": "device-42",
        },
    )

    assert update_response.status_code == 503
    assert update_response.json()["detail"] == "MQTT broker unavailable"

    greenhouse = db_session.get(Greenhouse, greenhouse_id)
    assert greenhouse is not None
    assert greenhouse.name == "Stable Greenhouse"
    assert greenhouse.ai_mode is None
    assert greenhouse.mqtt_topic_id == "device-41"
    assert greenhouse.pending_mqtt_topic_id is None
    assert greenhouse.mqtt_topic_update_token is None


def test_greenhouse_topic_id_must_be_single_segment(
    login_client: TestClient,
):
    response = login_client.post(
        "/api/greenhouses",
        json={"name": "Bad Topic Greenhouse", "mqtt_topic_id": "bad/topic"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "mqtt_topic_id must be a single MQTT topic segment"
