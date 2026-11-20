"""
The games of chess an account played: chess_games, a row for each, with the
game as it was written (pgn) and what is listed and sorted by read out of
it. scripts/import_chess.py fills it. Adding: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "chess_games" in sa.inspect(op.get_bind()).get_table_names():
        # a database marked as being at the baseline may already have the tables of today
        return
    op.create_table('chess_games',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('source_key', sa.String(length=100), nullable=False),
    sa.Column('color', sa.String(length=5), nullable=False),
    sa.Column('white', sa.String(length=100), nullable=False),
    sa.Column('black', sa.String(length=100), nullable=False),
    sa.Column('white_elo', sa.Integer(), nullable=True),
    sa.Column('black_elo', sa.Integer(), nullable=True),
    sa.Column('result', sa.String(length=7), nullable=False),
    sa.Column('termination', sa.String(length=300), nullable=False),
    sa.Column('time_control', sa.String(length=50), nullable=False),
    sa.Column('eco', sa.String(length=10), nullable=False),
    sa.Column('opening', sa.String(length=300), nullable=False),
    sa.Column('event', sa.String(length=200), nullable=False),
    sa.Column('site', sa.String(length=100), nullable=False),
    sa.Column('link', sa.String(length=500), nullable=False),
    sa.Column('plies', sa.Integer(), nullable=False),
    sa.Column('final_position', sa.String(length=80), nullable=False),
    sa.Column('remark', sa.Text(), nullable=False),
    sa.Column('pgn', sa.Text(), nullable=False),
    sa.Column('date_utcz', sa.DateTime(), nullable=True),
    sa.Column('date_ymd', sa.Date(), nullable=True),
    sa.Column('date_my', sa.String(length=7), nullable=False),
    sa.Column('date_y', sa.Integer(), nullable=True),
    sa.Column('date_timezone', sa.String(length=64), nullable=False),
    sa.CheckConstraint("color IN ('white', 'black')", name='ck_chess_game_color'),
    sa.CheckConstraint("result IN ('1-0', '0-1', '1/2-1/2', '*')", name='ck_chess_game_result'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'source_key', name='uq_chess_game_source')
    )
    with op.batch_alter_table('chess_games', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chess_games_owner_id'), ['owner_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('chess_games', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chess_games_owner_id'))

    op.drop_table('chess_games')
