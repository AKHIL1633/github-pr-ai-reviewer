"""pattern embeddings + lookup indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector ships with RDS PostgreSQL 15 and the pgvector/pgvector Docker image.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE patterns ADD COLUMN IF NOT EXISTS embedding vector(1536)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_patterns_embedding "
        "ON patterns USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_index("ix_findings_pr_id", "findings", ["pr_id"])
    op.create_index(
        "ix_pull_requests_repo_pr_sha",
        "pull_requests",
        ["repo_full_name", "pr_number", "head_sha"],
    )


def downgrade() -> None:
    op.drop_index("ix_pull_requests_repo_pr_sha", table_name="pull_requests")
    op.drop_index("ix_findings_pr_id", table_name="findings")
    op.execute("DROP INDEX IF EXISTS ix_patterns_embedding")
    op.execute("ALTER TABLE patterns DROP COLUMN IF EXISTS embedding")
