from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import User


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

