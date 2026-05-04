from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security import get_password_hash
from app.models.greenhouse import Greenhouse
from app.models.tenant import TenantMember, TenantRole
from app.models.user import User
from app.services.tenant_service import ensure_personal_tenant
from tests.conftest import get_auth_token

def test_current_tenant_overview_creates_personal_workspace(login_client: TestClient):
    response = login_client.get("/api/tenants/current")

    assert response.status_code == 200
    data = response.json()
    assert data["tenant"]["name"] == "TestUser workspace"
    assert data["role"] == "owner"
    assert data["plan"]["code"] == "free"
    assert data["plan"]["max_greenhouses"] == 3
    assert data["greenhouse_count"] == 0
    assert data["ai_messages_used"] == 0


def test_viewer_can_read_but_cannot_modify_greenhouse(
    client: TestClient,
    db_session: Session,
):
    owner = User(
        email="owner@example.com",
        hashed_password=get_password_hash("OwnerPassword123"),
        first_name="Owner",
    )
    viewer = User(
        email="viewer@example.com",
        hashed_password=get_password_hash("ViewerPassword123"),
        first_name="Viewer",
    )
    db_session.add(owner)
    db_session.add(viewer)
    db_session.commit()
    db_session.refresh(owner)
    db_session.refresh(viewer)

    tenant = ensure_personal_tenant(db_session, owner)
    db_session.add(
        TenantMember(
            tenant_id=tenant.id,
            user_id=viewer.id,
            role=TenantRole.VIEWER,
        )
    )
    greenhouse = Greenhouse(
        name="Shared greenhouse",
        owner_id=owner.id,
        tenant_id=tenant.id,
        mqtt_topic_id="viewer-role-test",
    )
    db_session.add(greenhouse)
    db_session.commit()
    db_session.refresh(greenhouse)

    auth_header = get_auth_token(client, "viewer@example.com", "ViewerPassword123")

    read_response = client.get(
        f"/api/greenhouses/{greenhouse.id}",
        headers={"Authorization": auth_header},
    )
    write_response = client.patch(
        f"/api/greenhouses/{greenhouse.id}",
        headers={"Authorization": auth_header},
        json={"name": "Viewer edit"},
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403
