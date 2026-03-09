"""Initial schema

Revision ID: c85389723dc5
Revises:
Create Date: 2025-12-11 15:16:30.484099

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c85389723dc5"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "greenhouse",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "plant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("greenhouse_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("variety", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["greenhouse_id"], ["greenhouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("greenhouse_id", sa.Integer(), nullable=False),
        sa.Column("air", sa.Float(), nullable=True),
        sa.Column("light", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("moisture", sa.Float(), nullable=True),
        sa.Column("soil_water_pump", sa.Boolean(), nullable=True),
        sa.Column("air_water_pump", sa.Boolean(), nullable=True),
        sa.Column("led", sa.Boolean(), nullable=True),
        sa.Column("fan", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["greenhouse_id"], ["greenhouse.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("telemetry")
    op.drop_table("plant")
    op.drop_table("greenhouse")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
