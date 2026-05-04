"""Add device command status table

Revision ID: 8a0f3c91d7b5
Revises: 6d4c8df9f1d2
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8a0f3c91d7b5"
down_revision: Union[str, None] = "6d4c8df9f1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devicecommand",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("greenhouse_id", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("ack_payload_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["greenhouse_id"], ["greenhouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_devicecommand_greenhouse_id",
        "devicecommand",
        ["greenhouse_id"],
        unique=False,
    )
    op.create_index(
        "ix_devicecommand_status",
        "devicecommand",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_devicecommand_created_at",
        "devicecommand",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_devicecommand_created_at", table_name="devicecommand")
    op.drop_index("ix_devicecommand_status", table_name="devicecommand")
    op.drop_index("ix_devicecommand_greenhouse_id", table_name="devicecommand")
    op.drop_table("devicecommand")
