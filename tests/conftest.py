import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

os.environ.setdefault("APP_ENV", "test")

from app.core.db import create_db_and_tables, db_drop_all, get_session
from app.core.security import get_password_hash
from app.main import app
from app.models.user import User

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "TestPassword123"


@pytest.fixture(scope="module")
def client():
    db_drop_all()
    create_db_and_tables()

    with TestClient(app) as client:
        yield client

    db_drop_all()


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    create_db_and_tables()
    for session in get_session():
        yield session


@pytest.fixture(scope="function")
def test_user(db_session: Session) -> User:
    session = db_session

    hashed_password = get_password_hash(TEST_PASSWORD)

    user = User(
        email=TEST_EMAIL, hashed_password=hashed_password, first_name="TestUser"
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    test_user_id = user.id

    yield user

    session.delete(user)
    session.commit()


# Reuse the helper function from the previous example
def get_auth_token(client: TestClient, email: str, password: str) -> str:
    """Performs a login request and returns the full Authorization header value."""
    login_data = {"email": email, "password": password}
    response = client.post("/api/auth/login", json=login_data)
    response.raise_for_status()
    token_response = response.json()

    access_token = token_response.get("access_token")
    token_type = token_response.get("token_type", "bearer")

    return f"{token_type.capitalize()} {access_token}"


@pytest.fixture(scope="function")
def login_client(client: TestClient, test_user) -> TestClient:
    auth_header_value = get_auth_token(client, TEST_EMAIL, TEST_PASSWORD)

    client.headers.update({"Authorization": auth_header_value})

    yield client

    del client.headers["Authorization"]
