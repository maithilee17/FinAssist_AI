"""Add private storage metadata, extracted pages, and document chunks.

Revision ID: 20261101_0002
Revises: 20261031_0001
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261101_0002"
down_revision: str | None = "20261031_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.alter_column(
            "file_path",
            new_column_name="storage_path",
            existing_type=sa.String(length=1024),
        )
        batch_op.add_column(
            sa.Column("file_size", sa.BigInteger(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "mime_type",
                sa.String(length=100),
                server_default="application/pdf",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("page_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("processing_error", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("is_empty", sa.Boolean(), nullable=False),
        sa.Column("extraction_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint(
            "document_id", "page_number", name="uq_document_pages_document_page"
        ),
    )
    op.create_index(
        op.f("ix_document_pages_document_id"), "document_pages", ["document_id"]
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_numbers", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_document_chunks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_index"
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"]
    )
    op.create_index(op.f("ix_document_chunks_user_id"), "document_chunks", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_user_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_document_pages_document_id"), table_name="document_pages")
    op.drop_table("document_pages")

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("processing_error")
        batch_op.drop_column("page_count")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("file_size")
        batch_op.alter_column(
            "storage_path",
            new_column_name="file_path",
            existing_type=sa.String(length=1024),
        )
