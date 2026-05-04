"""Add tenant, subscription, and AI chat history

Revision ID: b4d1e2c3a9f0
Revises: 8a0f3c91d7b5
Create Date: 2026-05-02 00:00:00.000000

"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b4d1e2c3a9f0"
down_revision: Union[str, None] = "8a0f3c91d7b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("max_greenhouses", sa.Integer(), nullable=True),
        sa.Column("ai_monthly_message_limit", sa.Integer(), nullable=True),
        sa.Column("telemetry_retention_days", sa.Integer(), nullable=True),
        sa.Column("price_monthly_cents", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_code", "plan", ["code"], unique=True)

    op.create_table(
        "tenant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenant_owner_id", "tenant", ["owner_id"], unique=False)
    op.create_index("ix_tenant_created_at", "tenant", ["created_at"], unique=False)

    op.create_table(
        "tenantmember",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_index("ix_tenantmember_tenant_id", "tenantmember", ["tenant_id"])
    op.create_index("ix_tenantmember_user_id", "tenantmember", ["user_id"])
    op.create_index("ix_tenantmember_role", "tenantmember", ["role"])
    op.create_index("ix_tenantmember_created_at", "tenantmember", ["created_at"])

    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_tenant_id", "subscription", ["tenant_id"])
    op.create_index("ix_subscription_plan_id", "subscription", ["plan_id"])
    op.create_index("ix_subscription_status", "subscription", ["status"])
    op.create_index(
        "ix_subscription_current_period_start",
        "subscription",
        ["current_period_start"],
    )
    op.create_index("ix_subscription_created_at", "subscription", ["created_at"])

    op.create_table(
        "usageevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usageevent_tenant_id", "usageevent", ["tenant_id"])
    op.create_index("ix_usageevent_user_id", "usageevent", ["user_id"])
    op.create_index("ix_usageevent_event_type", "usageevent", ["event_type"])
    op.create_index("ix_usageevent_created_at", "usageevent", ["created_at"])

    with op.batch_alter_table("greenhouse") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_greenhouse_tenant_id_tenant", "tenant", ["tenant_id"], ["id"]
        )
        batch_op.create_index("ix_greenhouse_tenant_id", ["tenant_id"])

    op.create_table(
        "chatsession",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("greenhouse_id", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["greenhouse_id"], ["greenhouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chatsession_owner_id", "chatsession", ["owner_id"])
    op.create_index("ix_chatsession_greenhouse_id", "chatsession", ["greenhouse_id"])
    op.create_index("ix_chatsession_scope", "chatsession", ["scope"])
    op.create_index("ix_chatsession_created_at", "chatsession", ["created_at"])

    op.create_table(
        "chatmessage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chatsession.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chatmessage_session_id", "chatmessage", ["session_id"])
    op.create_index("ix_chatmessage_role", "chatmessage", ["role"])
    op.create_index("ix_chatmessage_created_at", "chatmessage", ["created_at"])

    _backfill_personal_tenants()


def _backfill_personal_tenants() -> None:
    connection = op.get_bind()
    now = utc_now_naive()
    plan_table = sa.table(
        "plan",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("max_greenhouses", sa.Integer),
        sa.column("ai_monthly_message_limit", sa.Integer),
        sa.column("telemetry_retention_days", sa.Integer),
        sa.column("price_monthly_cents", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    tenant_table = sa.table(
        "tenant",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("owner_id", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    member_table = sa.table(
        "tenantmember",
        sa.column("tenant_id", sa.Integer),
        sa.column("user_id", sa.Integer),
        sa.column("role", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    subscription_table = sa.table(
        "subscription",
        sa.column("tenant_id", sa.Integer),
        sa.column("plan_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("current_period_start", sa.DateTime),
        sa.column("cancel_at_period_end", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    connection.execute(
        plan_table.insert().values(
            code="free",
            name="Free",
            max_greenhouses=3,
            ai_monthly_message_limit=100,
            telemetry_retention_days=30,
            price_monthly_cents=0,
            is_active=True,
        )
    )
    free_plan_id = connection.execute(
        sa.select(plan_table.c.id).where(plan_table.c.code == "free")
    ).scalar_one()

    users = connection.execute(
        sa.text('SELECT id, email, first_name FROM "user" ORDER BY id')
    ).mappings()
    for user in users:
        display_name = (user["first_name"] or user["email"] or "User").strip()
        connection.execute(
            tenant_table.insert().values(
                name=f"{display_name} workspace",
                owner_id=user["id"],
                created_at=now,
            )
        )
        tenant_id = connection.execute(
            sa.select(tenant_table.c.id).where(tenant_table.c.owner_id == user["id"])
        ).scalar_one()
        connection.execute(
            member_table.insert().values(
                tenant_id=tenant_id,
                user_id=user["id"],
                role="OWNER",
                created_at=now,
            )
        )
        connection.execute(
            subscription_table.insert().values(
                tenant_id=tenant_id,
                plan_id=free_plan_id,
                status="TRIALING",
                current_period_start=now,
                cancel_at_period_end=False,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            sa.text("UPDATE greenhouse SET tenant_id = :tenant_id WHERE owner_id = :user_id"),
            {"tenant_id": tenant_id, "user_id": user["id"]},
        )


def downgrade() -> None:
    op.drop_index("ix_chatmessage_created_at", table_name="chatmessage")
    op.drop_index("ix_chatmessage_role", table_name="chatmessage")
    op.drop_index("ix_chatmessage_session_id", table_name="chatmessage")
    op.drop_table("chatmessage")

    op.drop_index("ix_chatsession_created_at", table_name="chatsession")
    op.drop_index("ix_chatsession_scope", table_name="chatsession")
    op.drop_index("ix_chatsession_greenhouse_id", table_name="chatsession")
    op.drop_index("ix_chatsession_owner_id", table_name="chatsession")
    op.drop_table("chatsession")

    with op.batch_alter_table("greenhouse") as batch_op:
        batch_op.drop_index("ix_greenhouse_tenant_id")
        batch_op.drop_constraint("fk_greenhouse_tenant_id_tenant", type_="foreignkey")
        batch_op.drop_column("tenant_id")

    op.drop_index("ix_usageevent_created_at", table_name="usageevent")
    op.drop_index("ix_usageevent_event_type", table_name="usageevent")
    op.drop_index("ix_usageevent_user_id", table_name="usageevent")
    op.drop_index("ix_usageevent_tenant_id", table_name="usageevent")
    op.drop_table("usageevent")

    op.drop_index("ix_subscription_created_at", table_name="subscription")
    op.drop_index("ix_subscription_current_period_start", table_name="subscription")
    op.drop_index("ix_subscription_status", table_name="subscription")
    op.drop_index("ix_subscription_plan_id", table_name="subscription")
    op.drop_index("ix_subscription_tenant_id", table_name="subscription")
    op.drop_table("subscription")

    op.drop_index("ix_tenantmember_created_at", table_name="tenantmember")
    op.drop_index("ix_tenantmember_role", table_name="tenantmember")
    op.drop_index("ix_tenantmember_user_id", table_name="tenantmember")
    op.drop_index("ix_tenantmember_tenant_id", table_name="tenantmember")
    op.drop_table("tenantmember")

    op.drop_index("ix_tenant_created_at", table_name="tenant")
    op.drop_index("ix_tenant_owner_id", table_name="tenant")
    op.drop_table("tenant")

    op.drop_index("ix_plan_code", table_name="plan")
    op.drop_table("plan")
