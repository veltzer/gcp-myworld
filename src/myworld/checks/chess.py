"""
Checks of the chess games.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from myworld import pgn
from myworld.checks.core import Problem, Result, check
from myworld.models import ChessGame

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# what a check reads of each game: never its text, there may be 60,000 of them
READ = (
    ChessGame.id, ChessGame.owner_id, ChessGame.color, ChessGame.white, ChessGame.black, ChessGame.opponent, ChessGame.plies, ChessGame.final_position,
    ChessGame.date_utcz, ChessGame.date_ymd, ChessGame.date_my, ChessGame.date_y,
    # whether it has its text, asked of the database, which reads the text itself
    (ChessGame.pgn != "").label("has_text"),
)


def games(session: Session) -> list[Any]:
    """ Every game, of every account: by account, then as added. """
    return list(session.execute(select(*READ).order_by(ChessGame.owner_id, ChessGame.id)).all())


def problem(game: Any, message: str) -> Problem:
    return Problem(f"{pgn.name(game.white, game.black, game.opponent)} (chess game {game.id}, account {game.owner_id})", message, f"chess/{game.id}", game.owner_id)


@check("chess-dates", "Every chess game with its text has a date", "chess games", "chess")
def check_chess_dates(session: Session) -> Result:
    """
    Every chess game of every account that has its text has the date it was
    played (a day, a month, a year or a full time): a game's text says its
    date, so one without is a text read wrong. A game recorded without its
    moves (only whom the user played and how it ended) is not asked for one:
    many were never dated, and that is how they are kept.
    """
    found = games(session)
    undated = [g for g in found if g.has_text and g.date_utcz is None and g.date_ymd is None and not g.date_my and g.date_y is None]
    return Result(checked=len(found), problems=[problem(g, "has no date") for g in undated])


def players_problem(game: Any) -> str | None:
    """ What is wrong with who played a game, if anything. """
    if not (game.white or game.black):
        # recorded without its sides: whom the user played is all it says
        return None if game.opponent else "does not name the opponent"
    if not (game.white and game.black):
        return "does not name both players"
    return "has the same player on both sides" if game.white == game.black else None


@check("chess-players", "Every chess game names its two players", "chess games", "chess")
def check_chess_players(session: Session) -> Result:
    """
    Every chess game, of every account, says who played White and who played
    Black, and they are not the same name. One recorded without its sides
    (only how it ended) names the opponent.
    """
    found = games(session)
    problems = [problem(g, said) for g in found if (said := players_problem(g)) is not None]
    return Result(checked=len(found), problems=problems)


@check("chess-positions", "Every chess game says where it ended", "chess games", "chess")
def check_chess_positions(session: Session) -> Result:
    """
    Every chess game, of every account, has where its pieces stood when it
    ended, the picture of its card: eight ranks of pieces, as the first
    field of a FEN writes them. One added in the app while the page could
    not play its moves has none. One with no move (none made, or none
    recorded) has no position to show, and is not asked for one.
    """
    found = games(session)
    problems = [
        problem(g, "has no final position" if not g.final_position else f"has the final position {g.final_position!r}, which is not eight ranks of pieces")
        for g in found
        if g.plies and not pgn.POSITION.fullmatch(g.final_position)
    ]
    return Result(checked=len(found), problems=problems)
