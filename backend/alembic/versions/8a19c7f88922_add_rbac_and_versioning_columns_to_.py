"""add rbac and versioning columns to decision_records

Revision ID: 8a19c7f88922
Revises: 57b3ef4063b0
Create Date: 2026-10-31 17:04:29.043342

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8a19c7f88922'
down_revision: str | Sequence[str] | None = '57b3ef4063b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'decision_records',
        sa.Column(
            'component_versions',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default='{}',
        ),
    )
    op.add_column('decision_records', sa.Column('approver_role', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('decision_records', 'approver_role')
    op.drop_column('decision_records', 'component_versions')
