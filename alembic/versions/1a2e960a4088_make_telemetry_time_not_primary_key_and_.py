"""Add device table and mqtt topic id

Revision ID: 1a2e960a4088
Revises: 312cc9d3f3dc
Create Date: 2025-12-11 16:07:11.110540

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2e960a4088"
down_revision: Union[str, None] = "312cc9d3f3dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("greenhouse", sa.Column("mqtt_topic_id", sa.String(), nullable=True))
    op.create_index(
        "ix_greenhouse_mqtt_topic_id",
        "greenhouse",
        ["mqtt_topic_id"],
        unique=True,
    )
    op.create_table(
        "device",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("greenhouse_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("topic_root", sa.String(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["greenhouse_id"], ["greenhouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("device")
    op.drop_index("ix_greenhouse_mqtt_topic_id", table_name="greenhouse")
    op.drop_column("greenhouse", "mqtt_topic_id")
