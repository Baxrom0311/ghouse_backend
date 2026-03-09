import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Greenhouse


def test_create_greenhouse(login_client: TestClient, db_session: Session):
    res = login_client.post("/api/greenhouses", json={"name": "Greenhouse 4592899jf9e"})

    stm = select(Greenhouse).where(Greenhouse.name == "Greenhouse 4592899jf9e")
    assert db_session.exec(stm).first()
    assert res.status_code == 201
