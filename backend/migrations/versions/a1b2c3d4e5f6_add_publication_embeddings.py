"""add publication_embeddings table for local semantic RAG

Revision ID: a1b2c3d4e5f6
Revises: 0cdc4f1a90e1
Create Date: 2026-11-27 00:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "0cdc4f1a90e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_embeddings",
        sa.Column(
            "publication_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_publication_embeddings_model_name",
        "publication_embeddings",
        ["model_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_publication_embeddings_model_name", table_name="publication_embeddings")
    op.drop_table("publication_embeddings")
