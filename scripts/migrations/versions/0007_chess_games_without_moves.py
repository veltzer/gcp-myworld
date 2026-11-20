"""
A chess game may be recorded without its moves: only whom the user played
and how it ended, maybe without the side they played (color ""). Whom they
played and how it ended are columns of their own (opponent, outcome),
filled here for every game there is from its sides and its result. A game
with no move has no final position: it had the start, as though it had
ended where it began, and its card showed a board it never reached.
Adding columns the new code reads: run before the deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # a database the models made already has the columns: only its rows are brought up to date
    if "outcome" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chess_games")}:
        with op.batch_alter_table("chess_games") as batch:
            batch.add_column(sa.Column("opponent", sa.String(length=300), server_default="", nullable=False))
            batch.add_column(sa.Column("outcome", sa.String(length=5), server_default="", nullable=False))
            batch.drop_constraint("ck_chess_game_color", type_="check")
            batch.create_check_constraint("ck_chess_game_color", "color IN ('white', 'black', '')")
            batch.create_check_constraint("ck_chess_game_outcome", "outcome IN ('won', 'lost', 'drawn', '')")
    op.execute("""
        UPDATE chess_games SET
            opponent = CASE color WHEN 'white' THEN black WHEN 'black' THEN white ELSE opponent END,
            outcome = CASE
                WHEN (color = 'white' AND result = '1-0') OR (color = 'black' AND result = '0-1') THEN 'won'
                WHEN (color = 'white' AND result = '0-1') OR (color = 'black' AND result = '1-0') THEN 'lost'
                WHEN color IN ('white', 'black') AND result = '1/2-1/2' THEN 'drawn'
                WHEN color IN ('white', 'black') THEN ''
                ELSE outcome
            END
    """)
    op.execute("UPDATE chess_games SET final_position = '' WHERE plies = 0")


def downgrade() -> None:
    # a game whose side is not known cannot be kept by the tables of before
    op.execute("DELETE FROM chess_games WHERE color = ''")
    op.execute("UPDATE chess_games SET final_position = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR' WHERE plies = 0")
    with op.batch_alter_table("chess_games") as batch:
        batch.drop_constraint("ck_chess_game_outcome", type_="check")
        batch.drop_constraint("ck_chess_game_color", type_="check")
        batch.create_check_constraint("ck_chess_game_color", "color IN ('white', 'black')")
        batch.drop_column("outcome")
        batch.drop_column("opponent")
