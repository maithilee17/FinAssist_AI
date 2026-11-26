"""Add indexing metadata and grounded chat response fields.

Revision ID: 20261103_0003
Revises: 20261101_0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0003"
down_revision: str | None = "20261101_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "indexed_chunk_count", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("embedding_model", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        sa.text(
            "UPDATE documents SET processing_status = 'failed', "
            "processing_error = 'Semantic indexing is required; retry this document' "
            "WHERE processing_status = 'completed'"
        )
    )

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sources", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("model_name", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("retrieved_chunks_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("retrieval_time_ms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("generation_time_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE documents SET processing_status = 'failed', "
            "processing_error = 'Indexing was interrupted by a schema downgrade' "
            "WHERE processing_status = 'indexing'"
        )
    )
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_column("generation_time_ms")
        batch_op.drop_column("retrieval_time_ms")
        batch_op.drop_column("retrieved_chunks_count")
        batch_op.drop_column("model_name")
        batch_op.drop_column("sources")

    op.execute(
        sa.text(
            "UPDATE documents SET processing_status = 'completed', processing_error = NULL "
            "WHERE processing_error = 'Semantic indexing is required; retry this document'"
        )
    )

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("indexed_at")
        batch_op.drop_column("embedding_model")
        batch_op.drop_column("indexed_chunk_count")
