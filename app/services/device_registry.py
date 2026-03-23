from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Device, DeviceType
from app.models.greenhouse import Greenhouse


DEFAULT_GREENHOUSE_DEVICES: tuple[
    tuple[str, DeviceType, float | None, float | None], ...
] = (
    ("soil_water_pump", DeviceType.ACTUATOR, None, None),
    ("air_water_pump", DeviceType.ACTUATOR, None, None),
    ("led", DeviceType.ACTUATOR, None, None),
    ("fan", DeviceType.ACTUATOR, None, None),
    ("air", DeviceType.SENSOR, 400, 1200),
    ("humidity", DeviceType.SENSOR, 40, 70),
    ("temperature", DeviceType.SENSOR, 18, 28),
    ("moisture", DeviceType.SENSOR, 35, 70),
    ("light", DeviceType.SENSOR, 20, 60),
)


def ensure_greenhouse_devices(db: Session, greenhouse: Greenhouse) -> dict[str, Device]:
    statement = select(Device).where(Device.greenhouse_id == greenhouse.id)
    devices = {device.name: device for device in db.exec(statement).all()}
    created = False
    updated = False
    topic_prefix = greenhouse.mqtt_topic_id or settings.DEFAULT_MQTT_TOPIC_ID

    for device_name, device_type, min_value, max_value in DEFAULT_GREENHOUSE_DEVICES:
        expected_topic_root = f"{topic_prefix}/{device_name}"

        if device_name in devices:
            device = devices[device_name]
            desired_min_value = (
                device.min_value if device.min_value is not None else min_value
            )
            desired_max_value = (
                device.max_value if device.max_value is not None else max_value
            )
            if (
                device.type != device_type
                or device.topic_root != expected_topic_root
                or device.min_value != desired_min_value
                or device.max_value != desired_max_value
            ):
                device.type = device_type
                device.topic_root = expected_topic_root
                device.min_value = desired_min_value
                device.max_value = desired_max_value
                db.add(device)
                updated = True
            continue

        device = Device(
            greenhouse_id=greenhouse.id,
            type=device_type,
            name=device_name,
            topic_root=expected_topic_root,
            min_value=min_value,
            max_value=max_value,
        )
        db.add(device)
        devices[device_name] = device
        created = True

    if created or updated:
        db.commit()
        for device in devices.values():
            if device.id is None:
                db.refresh(device)

    return devices
