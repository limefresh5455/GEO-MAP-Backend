from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a9f3b1c2d4e5'
down_revision: Union[str, None] = '20260618190000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # STEP 1: Drop all foreign keys that reference place_qa_sessions.id
    # so we can alter the primary key column type.
    # ------------------------------------------------------------------

    # FK on place_qa_messages.session_id (CASCADE)
    op.drop_constraint(
        'place_qa_messages_session_id_fkey',
        'place_qa_messages',
        type_='foreignkey',
    )

    # FK on place_questions.session_id (SET NULL)
    op.drop_constraint(
        'fk_place_questions_session_id',
        'place_questions',
        type_='foreignkey',
    )

    # FK on place_answer_logs.session_id (SET NULL)
    op.drop_constraint(
        'fk_place_answer_logs_session_id',
        'place_answer_logs',
        type_='foreignkey',
    )

    # ------------------------------------------------------------------
    # STEP 2: Null out session_id in audit tables (existing integer IDs
    # are stale — there are no sessions to link them to after migration).
    # ------------------------------------------------------------------
    op.execute("UPDATE place_questions SET session_id = NULL")
    op.execute("UPDATE place_answer_logs SET session_id = NULL")

    # ------------------------------------------------------------------
    # STEP 3: Truncate session-scoped tables (chat data only).
    # This removes all existing place_qa_sessions and place_qa_messages
    # rows so the column type change is clean (no data to migrate).
    # CASCADE automatically clears place_qa_messages via the FK.
    # ------------------------------------------------------------------
    op.execute("TRUNCATE place_qa_sessions CASCADE")

    # ------------------------------------------------------------------
    # STEP 4: Drop the primary key index on place_qa_sessions.id before
    # altering the column type (PostgreSQL requires this).
    # ------------------------------------------------------------------
    op.drop_index('ix_place_qa_sessions_id', table_name='place_qa_sessions')

    # ------------------------------------------------------------------
    # STEP 5: Alter place_qa_sessions.id from INTEGER to VARCHAR(24).
    # Remove the SERIAL/sequence default and set no DB-level default
    # (the application generates the ID before INSERT via SQLAlchemy
    # column default=generate_session_id).
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE place_qa_sessions "
        "ALTER COLUMN id DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE place_qa_sessions "
        "ALTER COLUMN id TYPE VARCHAR(24) USING id::VARCHAR"
    )

    # ------------------------------------------------------------------
    # STEP 6: Alter place_qa_messages.session_id from INTEGER to VARCHAR(24).
    # ------------------------------------------------------------------
    op.drop_index('ix_place_qa_messages_session_id', table_name='place_qa_messages')
    op.execute(
        "ALTER TABLE place_qa_messages "
        "ALTER COLUMN session_id TYPE VARCHAR(24) USING session_id::VARCHAR"
    )

    # ------------------------------------------------------------------
    # STEP 7: Alter audit table session_id columns from INTEGER to VARCHAR(24).
    # These are already NULL after STEP 2, so the USING cast is harmless.
    # ------------------------------------------------------------------
    op.drop_index('ix_place_questions_session_id', table_name='place_questions')
    op.execute(
        "ALTER TABLE place_questions "
        "ALTER COLUMN session_id TYPE VARCHAR(24) USING session_id::VARCHAR"
    )

    op.drop_index('ix_place_answer_logs_session_id', table_name='place_answer_logs')
    op.execute(
        "ALTER TABLE place_answer_logs "
        "ALTER COLUMN session_id TYPE VARCHAR(24) USING session_id::VARCHAR"
    )

    # ------------------------------------------------------------------
    # STEP 8: Recreate indexes
    # ------------------------------------------------------------------
    op.create_index(
        op.f('ix_place_qa_sessions_id'),
        'place_qa_sessions', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_qa_messages_session_id'),
        'place_qa_messages', ['session_id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_questions_session_id'),
        'place_questions', ['session_id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_answer_logs_session_id'),
        'place_answer_logs', ['session_id'], unique=False,
    )

    # ------------------------------------------------------------------
    # STEP 9: Recreate foreign keys with VARCHAR(24) types
    # ------------------------------------------------------------------
    op.create_foreign_key(
        'place_qa_messages_session_id_fkey',
        'place_qa_messages',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_place_questions_session_id',
        'place_questions',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_place_answer_logs_session_id',
        'place_answer_logs',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse: VARCHAR(24) -> INTEGER
    # Note: any VARCHAR session IDs that cannot be cast to INTEGER will
    # fail. This downgrade assumes the table is empty or all IDs happen
    # to be numeric strings. In practice, truncate before downgrading.
    # ------------------------------------------------------------------

    # Drop FKs
    op.drop_constraint(
        'place_qa_messages_session_id_fkey',
        'place_qa_messages',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_place_questions_session_id',
        'place_questions',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_place_answer_logs_session_id',
        'place_answer_logs',
        type_='foreignkey',
    )

    # Null audit rows
    op.execute("UPDATE place_questions SET session_id = NULL")
    op.execute("UPDATE place_answer_logs SET session_id = NULL")

    # Truncate sessions
    op.execute("TRUNCATE place_qa_sessions CASCADE")

    # Drop indexes
    op.drop_index('ix_place_qa_sessions_id', table_name='place_qa_sessions')
    op.drop_index('ix_place_qa_messages_session_id', table_name='place_qa_messages')
    op.drop_index('ix_place_questions_session_id', table_name='place_questions')
    op.drop_index('ix_place_answer_logs_session_id', table_name='place_answer_logs')

    # Revert column types
    op.execute(
        "ALTER TABLE place_qa_sessions "
        "ALTER COLUMN id TYPE INTEGER USING id::INTEGER"
    )
    op.execute(
        "ALTER TABLE place_qa_sessions "
        "ALTER COLUMN id SET DEFAULT nextval('place_qa_sessions_id_seq')"
    )
    op.execute(
        "ALTER TABLE place_qa_messages "
        "ALTER COLUMN session_id TYPE INTEGER USING session_id::INTEGER"
    )
    op.execute(
        "ALTER TABLE place_questions "
        "ALTER COLUMN session_id TYPE INTEGER USING session_id::INTEGER"
    )
    op.execute(
        "ALTER TABLE place_answer_logs "
        "ALTER COLUMN session_id TYPE INTEGER USING session_id::INTEGER"
    )

    # Recreate indexes
    op.create_index(
        op.f('ix_place_qa_sessions_id'),
        'place_qa_sessions', ['id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_qa_messages_session_id'),
        'place_qa_messages', ['session_id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_questions_session_id'),
        'place_questions', ['session_id'], unique=False,
    )
    op.create_index(
        op.f('ix_place_answer_logs_session_id'),
        'place_answer_logs', ['session_id'], unique=False,
    )

    # Recreate FKs
    op.create_foreign_key(
        'place_qa_messages_session_id_fkey',
        'place_qa_messages',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_place_questions_session_id',
        'place_questions',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_place_answer_logs_session_id',
        'place_answer_logs',
        'place_qa_sessions',
        ['session_id'],
        ['id'],
        ondelete='SET NULL',
    )
