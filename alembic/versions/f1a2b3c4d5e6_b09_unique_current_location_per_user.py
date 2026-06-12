"""B09: partial unique index — one is_current=True per user

Revision ID: f1a2b3c4d5e6
Revises: cb3b8c851c9d
Create Date: 2026-06-12 15:00:00.000000

Adds a partial unique index on user_locations(user_id) WHERE is_current=True.
This enforces the invariant that each user has at most one active current
location at the database level, preventing the race condition where two
concurrent GPS pings both insert is_current=True rows (B09).

The service layer catches IntegrityError and retries once on violation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'cb3b8c851c9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Before creating the unique index, clean up any existing duplicate
    # is_current=True rows that may have been created before this fix.
    # Keep only the most recently created row per user.
    op.execute("""
        UPDATE user_locations ul
        SET is_current = FALSE
        WHERE is_current = TRUE
          AND id NOT IN (
              SELECT DISTINCT ON (user_id) id
              FROM user_locations
              WHERE is_current = TRUE
              ORDER BY user_id, created_at DESC
          )
    """)

    # Partial unique index: only ONE is_current=TRUE row allowed per user.
    # Rows where is_current=FALSE are excluded from the index entirely,
    # so they are not affected and historical rows remain intact.
    op.create_index(
        index_name='uix_user_locations_single_current',
        table_name='user_locations',
        columns=['user_id'],
        unique=True,
        postgresql_where=sa.text('is_current = TRUE'),
    )


def downgrade() -> None:
    op.drop_index(
        index_name='uix_user_locations_single_current',
        table_name='user_locations',
    )
