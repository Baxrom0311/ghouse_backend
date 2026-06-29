"""Add vision_event table

Revision ID: a3b7c9d1e5f2
Revises: 2f0c7d8a9b11
Create Date: 2026-06-12 01:34:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b7c9d1e5f2"
down_revision: Union[str, None] = "2f0c7d8a9b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vision_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("greenhouse_id", sa.Integer(), sa.ForeignKey("greenhouse.id"), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("health_status", sa.String(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("sensor_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vision_event_greenhouse_id", "vision_event", ["greenhouse_id"])
    op.create_index("ix_vision_event_greenhouse_created", "vision_event", ["greenhouse_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_vision_event_greenhouse_created", table_name="vision_event")
    op.drop_index("ix_vision_event_greenhouse_id", table_name="vision_event")
    op.drop_table("vision_event")
