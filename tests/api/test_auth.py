from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, get_auth_token


def test_register_creates_user(client: TestClient, db_session: Session):
    email = "fresh-user@example.com"
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "StrongPassword123",
            "first_name": "Fresh",
            "last_name": "User",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == email
    assert payload["first_name"] == "Fresh"
    assert "hashed_password" not in payload

    statement = select(User).where(User.email == email)
    created_user = db_session.exec(statement).first()
    assert created_user is not None


def test_register_rejects_weak_password(client: TestClient):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "weak-password@example.com",
            "password": "short",
            "first_name": "Weak",
            "last_name": "Password",
        },
    )

    assert response.status_code == 422


def test_change_password_rejects_weak_new_password(login_client: TestClient):
    response = login_client.post(
        "/api/auth/password/change",
        json={
            "current_password": "TestPassword123",
            "new_password": "password",
        },
    )

    assert response.status_code == 422


def test_inactive_user_token_is_rejected(
    client: TestClient,
    db_session: Session,
    test_user: User,
):
    auth_header = get_auth_token(client, TEST_EMAIL, TEST_PASSWORD)

    test_user.is_active = False
    db_session.add(test_user)
    db_session.commit()

    response = client.get("/api/auth/whoami", headers={"Authorization": auth_header})

    assert response.status_code == 403
