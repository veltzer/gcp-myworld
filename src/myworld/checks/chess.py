"""
Checks of the chess games.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import pgn
from myworld.checks.core import Problem, Result, check
from myworld.models import ChessGame

# what a check reads of each game: never its text, there may be 60,000 of them
READ = (
    ChessGame.id, ChessGame.owner_id, ChessGame.white, ChessGame.black, ChessGame.final_position,
    ChessGame.date_utcz, ChessGame.date_ymd, ChessGame.date_my, ChessGame.date_y,
)


def games(session: Session) -> list[Any]:
    """ Every game, of every account: by account, then as added. """
    return list(session.execute(select(*READ).order_by(ChessGame.owner_id, ChessGame.id)).all())


def problem(game: Any, message: str) -> Problem:
    return Problem(f"{game.white} vs {game.black} (chess game {game.id}, account {game.owner_id})", message, f"chess/{game.id}", game.owner_id)


@check("chess-dates", "Every chess game has a date", "chess games", "chess")
def check_chess_dates(session: Session) -> Result:
    """ Every chess game, of every account, has the date it was played (a day, a month, a year or a full time). """
    found = games(session)
    undated = [g for g in found if g.date_utcz is None and g.date_ymd is None and not g.date_my and g.date_y is None]
    return Result(checked=len(found), problems=[problem(g, "has no date") for g in undated])


@check("chess-players", "Every chess game names its two players", "chess games", "chess")
def check_chess_players(session: Session) -> Result:
    """ Every chess game, of every account, says who played White and who played Black, and they are not the same name. """
    found = games(session)
    problems = [
        problem(g, "does not name both players" if not (g.white and g.black) else "has the same player on both sides")
        for g in found
        if not (g.white and g.black) or g.white == g.black
    ]
    return Result(checked=len(found), problems=problems)


@check("chess-positions", "Every chess game says where it ended", "chess games", "chess")
def check_chess_positions(session: Session) -> Result:
    """
    Every chess game, of every account, has where its pieces stood when it
    ended, the picture of its card: eight ranks of pieces, as the first
    field of a FEN writes them. One added in the app while the page could
    not play its moves has none.
    """
    found = games(session)
    problems = [
        problem(g, "has no final position" if not g.final_position else f"has the final position {g.final_position!r}, which is not eight ranks of pieces")
        for g in found
        if not pgn.POSITION.fullmatch(g.final_position)
    ]
    return Result(checked=len(found), problems=problems)
