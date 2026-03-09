import pytest
from fastapi.testclient import TestClient


def test_root_path(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
