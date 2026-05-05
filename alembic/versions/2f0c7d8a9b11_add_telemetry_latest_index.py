"""Add telemetry latest lookup index

Revision ID: 2f0c7d8a9b11
Revises: e7f4a2b1c9d0
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "2f0c7d8a9b11"
down_revision: Union[str, None] = "e7f4a2b1c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_telemetry_greenhouse_time_id",
        "telemetry",
        ["greenhouse_id", "time", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_greenhouse_time_id", table_name="telemetry")
