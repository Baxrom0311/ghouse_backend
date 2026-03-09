from datetime import datetime
from time import sleep

from faker import Faker
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import Greenhouse, User
from app.models.telemetry import Telemetry


def fakeit():
    pass


def generate_sample_data(engine: Engine):
    print("\n\nGENERATING SAMPLE DATA...")
    """Generate sample data: 2-3 users, 1-2 greenhouses per user, and all device types."""
    fake = Faker()

    with Session(engine) as db:
        # Check if data already exists
        existing_users = db.exec(select(User)).first()
        if existing_users:
            return  # Data already exists, skip generation

        # Create 2-3 users
        users: list[User] = []
        for i in range(3):
            user = User(
                email=f"test{i + 1}@example.com",
                first_name=f"Test User " + str(i + 1),
                last_name=fake.last_name(),
                hashed_password=get_password_hash("test"),
            )
            db.add(user)
            users.append(user)

        db.flush()  # Flush to get user IDs

        # Create 1-2 greenhouses per user with all device types
        default_topic_assigned = False
        for user in users:
            num_greenhouses = fake.random_int(min=1, max=2)

            for gh_num in range(num_greenhouses):
                mqtt_topic_id = f"demo-{user.id}-{gh_num + 1}"
                if not default_topic_assigned:
                    mqtt_topic_id = settings.DEFAULT_MQTT_TOPIC_ID
                    default_topic_assigned = True

                greenhouse = Greenhouse(
                    name=f"My Greenhouse {gh_num + 1}",
                    owner_id=user.id,
                    mqtt_topic_id=mqtt_topic_id,
                )
                db.add(greenhouse)
                db.flush()  # Flush to get greenhouse ID

        db.commit()

        greenhouses = db.exec(select(Greenhouse)).all()
        # Add some telemetries if not exists in the greenhouses
        telemetries = []
        for greenhouse in greenhouses:
            if len(greenhouse.telemetries) < 1:
                telemetry = Telemetry(
                    time=fake.date_time(),
                    greenhouse_id=greenhouse.id,
                    # Sensors
                    air=fake.random_int(min=0, max=100),
                    light=fake.random_int(min=0, max=100),
                    humidity=fake.random_int(min=0, max=100),
                    temperature=fake.random_int(min=0, max=100),
                    moisture=fake.random_int(min=0, max=100),
                    # Actuators
                    soil_water_pump=fake.boolean(),
                    air_water_pump=fake.boolean(),
                    led=fake.boolean(),
                    fan=fake.boolean(),
                    # Others
                    ai_mode=fake.boolean(),
                )
                telemetries.append(telemetry)

        db.add_all(telemetries)
        db.commit()

    print("\n\nGENERATING SAMPLE DATA... done")
