from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import auth as auth_route
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


def test_rate_limit_uses_trusted_proxy_client_headers():
    request = type(
        "Request",
        (),
        {
            "headers": {
                "cf-connecting-ip": "203.0.113.10",
                "x-forwarded-for": "198.51.100.7, 10.0.0.5",
                "x-real-ip": "192.0.2.8",
            },
            "client": type("Client", (), {"host": "172.18.0.2"})(),
        },
    )()

    assert auth_route._client_ip(request) == "203.0.113.10"


def test_rate_limit_uses_x_real_ip_before_forwarded_for():
    request = type(
        "Request",
        (),
        {
            "headers": {
                "x-forwarded-for": "203.0.113.10, 10.0.0.5",
                "x-real-ip": "198.51.100.7",
            },
            "client": type("Client", (), {"host": "172.18.0.2"})(),
        },
    )()

    assert auth_route._client_ip(request) == "198.51.100.7"


def test_rate_limit_ignores_headers_from_untrusted_peer():
    request = type(
        "Request",
        (),
        {
            "headers": {
                "cf-connecting-ip": "203.0.113.10",
                "x-real-ip": "198.51.100.7",
            },
            "client": type("Client", (), {"host": "8.8.8.8"})(),
        },
    )()

    assert auth_route._client_ip(request) == "8.8.8.8"


def test_password_change_revokes_existing_tokens(
    client: TestClient,
    test_user: User,
):
    login_response = client.post(
        "/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()
    access_token = login_payload["access_token"]
    refresh_token = login_payload["refresh_token"]

    change_response = client.post(
        "/api/auth/password/change",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "NewPassword123",
        },
    )
    assert change_response.status_code == 204

    refresh_response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 401

    whoami_response = client.get(
        "/api/auth/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert whoami_response.status_code == 401
