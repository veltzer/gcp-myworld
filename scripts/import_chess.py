#!/usr/bin/env python

"""
Add the chess games of PGN files to the database, for one user.

  scripts/import_chess.py --email me@example.com            the files of ../data/raw/topics/games/chess
  scripts/import_chess.py --email me@example.com FILE ...   these files (.pgn, or .pgn.gz)
  scripts/import_chess.py --email me@example.com --dry-run  do it all and say what was done, then roll it back

Only the games the account does not have yet are added, so it is safe to
run again, on the same files or on newer ones: a game is told from every
other by its address at the site it was played on, else by its players,
its day and its moves. A game the account has is never changed (its remark
may have been written in the app since).

The user is the player called by one of --handle (each a name they went
by, written exactly); the other player is the opponent. A game neither of
whose players is the user is not theirs and is left out, and said. Every
game is played through, which says where its pieces ended (the picture of
its card); one with a move that cannot be played is added as it is
written, ending where its last legal move left it, and said.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/import_chess.py ...
"""

import argparse
import gzip
import sys
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed: find it from any directory, no PYTHONPATH needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from myworld import pgn
from myworld.models import ChessGame, User, make_engine

# where the files are kept, next to this repository
SOURCE = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "topics" / "games" / "chess"
# the names the owner of these files went by: on the chess servers, at Chess.com, and on two machines against GNU Chess
HANDLES = ("veltzer", "mark_veltzer", "Administrator", "mark")
# rows sent to the database at a time (a statement holds 65,535 values at most, and a row is some 26)
BATCH = 500


class ChessImportError(Exception):
    pass


def read(path: Path) -> str:
    """ The text of a PGN file, gzipped or not. """
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return pgn.decode(data)


def files(source: Path) -> list[Path]:
    found = sorted(path for path in source.iterdir() if path.name.endswith((".pgn", ".pgn.gz"))) if source.is_dir() else []
    if not found:
        raise ChessImportError(f"{source}: no .pgn or .pgn.gz files there")
    return found


def played(game: pgn.Game) -> tuple[str, bool]:
    """ Where the pieces ended (the first field of a FEN), and whether every move could be played: it stops at one that cannot. """
    board = chess.Board()
    for move in game.moves:
        try:
            board.push_san(move.san)
        except ValueError:
            return board.board_fen(), False
    return board.board_fen(), True


def color_of(game: pgn.Game, handles: frozenset[str]) -> str | None:
    """ The side the user played; None for a game neither of whose players is the user. """
    white, black = game.tags.get("White", "") in handles, game.tags.get("Black", "") in handles
    if white and black:
        raise ChessImportError(f"{game.tags.get('White')} vs {game.tags.get('Black')} ({game.tags.get('Date')}): both players are the user")
    return pgn.WHITE if white else pgn.BLACK if black else None


def import_chess(session: Session, owner: User, paths: list[Path], handles: frozenset[str]) -> dict[str, int]:
    """ Add the games of paths that owner does not have yet. Does not commit. """
    have = set(session.scalars(select(ChessGame.source_key).where(ChessGame.owner_id == owner.id)))
    counts = {"games read": 0, "added": 0, "already there": 0, "twice in the files": 0, "not the user's": 0, "with a move that cannot be played": 0}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for text in pgn.split(read(path)):
            game = pgn.parse(text)
            counts["games read"] += 1
            color = color_of(game, handles)
            who = f"{path.name}: {game.tags.get('White')} vs {game.tags.get('Black')} ({game.tags.get('Date')})"
            if color is None:
                counts["not the user's"] += 1
                print(f"{who}: neither player is the user: left out")
                continue
            fields = pgn.fields(game)
            if fields["source_key"] in seen:
                counts["twice in the files"] += 1
                continue
            seen.add(fields["source_key"])
            if fields["source_key"] in have:
                counts["already there"] += 1
                continue
            position, whole = played(game)
            if not whole:
                counts["with a move that cannot be played"] += 1
                print(f"{who}: a move cannot be played: added as written")
            # where the site says it ended is where the moves end
            said = game.tags.get("CurrentPosition", "").split(" ")[0]
            if said and whole and said != position:
                raise ChessImportError(f"{who}: the moves end at {position}, not at the {said} it says")
            rows.append({
                **fields, "owner_id": owner.id, "color": color, "final_position": position, "remark": "",
                "date_timezone": "UTC" if fields["date_utcz"] is not None else "",
            })
            counts["added"] += 1
    # each batch one statement of many rows: a row a statement is a trip to the database each, an hour of them
    for start in range(0, len(rows), BATCH):
        session.execute(insert(ChessGame).values(rows[start:start + BATCH]))
    session.flush()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--email", required=True, help="email of the account that will own the games")
    parser.add_argument("--source", type=Path, default=SOURCE, help="the directory whose .pgn and .pgn.gz files are read, when no file is named")
    parser.add_argument("--handle", action="append", help=f"a name the user played under, exactly as written; may be given several times (default: {', '.join(HANDLES)})")
    parser.add_argument("--dry-run", action="store_true", help="do it all and print what was done, then roll it back")
    parser.add_argument("files", nargs="*", type=Path, help="PGN files to read, instead of those of --source")
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        try:
            owner = session.scalars(select(User).where(User.email == args.email)).first()
            if owner is None:
                raise ChessImportError(f"no account for {args.email}: sign in once first")
            counts = import_chess(session, owner, args.files or files(args.source), frozenset(args.handle or HANDLES))
        except (ChessImportError, pgn.PgnError, OSError) as e:
            print(f"import_chess: {e}", file=sys.stderr)
            return 1
        who = f"{owner.email} (account {owner.id})"
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    summary = ", ".join(f"{count} {what}" for what, count in counts.items())
    print(f"{engine.url.render_as_string(hide_password=True)}: chess games for {who}: {summary}{' (dry run: rolled back)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
