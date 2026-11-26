"""Persist evidence, claim, and confidence verification diagnostics.

Revision ID: 20261103_0005
Revises: 20261103_0004
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0005"
down_revision: str | None = "20261103_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(sa.Column("evidence_status", sa.String(32), nullable=True))
        batch_op.add_column(
            sa.Column("verification_status", sa.String(32), nullable=True)
        )
        batch_op.add_column(sa.Column("confidence_score", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("verification_metadata", sa.JSON(), nullable=True)
        )
        batch_op.add_column(sa.Column("confidence_metadata", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("retrieval_attempts", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_column("retrieval_attempts")
        batch_op.drop_column("confidence_metadata")
        batch_op.drop_column("verification_metadata")
        batch_op.drop_column("confidence_score")
        batch_op.drop_column("verification_status")
        batch_op.drop_column("evidence_status")
