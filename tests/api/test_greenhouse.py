import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import device as device_route
from app.models import Greenhouse


def test_create_greenhouse(login_client: TestClient, db_session: Session):
    res = login_client.post("/api/greenhouses", json={"name": "Greenhouse 4592899jf9e"})

    stm = select(Greenhouse).where(Greenhouse.name == "Greenhouse 4592899jf9e")
    assert db_session.exec(stm).first()
    assert res.status_code == 201


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
    monkeypatch: pytest.MonkeyPatch,
):
    published_commands: list[tuple[str, object]] = []

    def fake_publish(topic: str, payload: object) -> bool:
        published_commands.append((topic, payload))
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
    assert ("device-1/system/topic_id", "device-2") in published_commands
    assert update_response.json()["mqtt_topic_id"] == "device-2"


def test_greenhouse_topic_id_must_be_single_segment(
    login_client: TestClient,
):
    response = login_client.post(
        "/api/greenhouses",
        json={"name": "Bad Topic Greenhouse", "mqtt_topic_id": "bad/topic"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "mqtt_topic_id must be a single MQTT topic segment"
