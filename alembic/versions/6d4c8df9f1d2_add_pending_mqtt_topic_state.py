"""Add pending MQTT topic migration state

Revision ID: 6d4c8df9f1d2
Revises: 1a2e960a4088
Create Date: 2026-04-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6d4c8df9f1d2"
down_revision: Union[str, None] = "1a2e960a4088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "greenhouse",
        sa.Column("pending_mqtt_topic_id", sa.String(), nullable=True),
    )
    op.add_column(
        "greenhouse",
        sa.Column("mqtt_topic_update_token", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE greenhouse
        SET pending_mqtt_topic_id = NULL,
            mqtt_topic_update_token = NULL
        WHERE pending_mqtt_topic_id IS NOT NULL
          AND (
            TRIM(pending_mqtt_topic_id) = ''
            OR TRIM(COALESCE(mqtt_topic_update_token, '')) = ''
            OR pending_mqtt_topic_id = mqtt_topic_id
            OR EXISTS (
                SELECT 1
                FROM greenhouse AS current_topics
                WHERE current_topics.id <> greenhouse.id
                  AND current_topics.mqtt_topic_id = greenhouse.pending_mqtt_topic_id
            )
            OR EXISTS (
                SELECT 1
                FROM greenhouse AS earlier_pending
                WHERE earlier_pending.id < greenhouse.id
                  AND earlier_pending.pending_mqtt_topic_id = greenhouse.pending_mqtt_topic_id
            )
          )
        """
    )
    op.create_index(
        "ix_greenhouse_pending_mqtt_topic_id",
        "greenhouse",
        ["pending_mqtt_topic_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_greenhouse_pending_mqtt_topic_id", table_name="greenhouse")
    op.drop_column("greenhouse", "mqtt_topic_update_token")
    op.drop_column("greenhouse", "pending_mqtt_topic_id")
