#!/usr/bin/env python

"""
Add the chess games of chess.xml, the record of the games played over the
board, to the database, for one user.

  scripts/import_chess_xml.py --email me@example.com FILE            add the games of this file
  scripts/import_chess_xml.py --email me@example.com --dry-run FILE  do it all and say what was done, then roll it back

chess.xml, kept in the data repository, was imported and then removed from
it (its git history has it): this is for a file of the same form.

The file says of each game whom the user played (one of its opponents) and
how it ended for them (won, lost, tie, pat), and sometimes the day, the
time control or how long it was, and a remark; never the moves, nor the side
the user played. So each is a game without its moves (models.ChessGame):
no text, the side not known, and its opponent and outcome as the file says.
An opponent goes by their name, else by what the file says of them ("met in
Rosh Pinah"); what it says of them besides, their description and category,
is in the remark of each game against them ("opponent: brother; opponent's
category: family").

Many games are alike in all the file says (the same opponent, the same
result, no day), so a game is told from every other by its place in the
file (chess.xml:1 is the first): it is safe to run again on the same file,
and only the games the account does not have yet are added. A game the
account has is never changed. So a game is only ever added to the file at
its end: one put in its middle would move every game after it.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/import_chess_xml.py ...
"""

import argparse
import datetime
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed: find it from any directory, no PYTHONPATH needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from myworld import pgn
from myworld.models import ChessGame, User, make_engine

# how a game ended for the user, in the file's words: a pat is a stalemate, which is a draw
OUTCOMES = {"won": pgn.WON, "lost": pgn.LOST, "tie": pgn.DRAWN, "pat": pgn.DRAWN}
UNKNOWN = "unknown"
# the categories of opponents as the file spells them, where a remark spells them otherwise
CATEGORIES = {"familty": "family"}
# a day as the file writes it: "16.6.01", the year in two digits (99 is 1999, 01 is 2001)
_DAY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2})")
# or as date(1) does: "Fri Dec 13 14:56:44 IST 2002" (the time is when the line was written, not the game)
_DATE_OUTPUT = re.compile(r"\w{3} (\w{3}) +(\d{1,2}) [\d:]+ \w+ (\d{4})")
# its place in the file tells a game from every other
KEY = "chess.xml:{}"
# rows sent to the database at a time
BATCH = 500


class ChessXmlError(Exception):
    pass


def when(said: str) -> tuple[datetime.date | None, int | None]:
    """
    When a game was played, as the file says it: the day, or, where the file
    writes a day no calendar has ("31.11.01"), only its year, the one thing
    of it that is sure; (None, None) where it says "unknown".
    """
    if said == UNKNOWN:
        return None, None
    short = _DAY.fullmatch(said)
    if short:
        number, month, year = (int(part) for part in short.groups())
        year += 1900 if year >= 50 else 2000
        try:
            return datetime.date(year, month, number), None
        except ValueError:
            return None, year
    long = _DATE_OUTPUT.fullmatch(said)
    if long:
        return datetime.datetime.strptime(" ".join(long.groups()) + " +0000", "%b %d %Y %z").date(), None
    raise ChessXmlError(f"the date {said!r} is written in no way this knows")


def known(said: str) -> str:
    return "" if said == UNKNOWN else said


def opponents(root: ET.Element) -> dict[str, tuple[str, str]]:
    """
    Each opponent by their id: their name (first name and surname, else what
    the file says of them), and what it says of them besides, for a remark.
    """
    found = {}
    for opponent in root.iter("opponent"):
        field = {child.tag: (child.text or "").strip() for child in opponent}
        name = " ".join(part for part in (field.get("firstname", ""), field.get("surname", "")) if part)
        description = field.get("description", "")
        if not name and not description:
            raise ChessXmlError(f"opponent {field.get('id')} has no name and no description")
        category = field.get("category", "")
        category = CATEGORIES.get(category, category).replace("_", " ").replace("-", " ")
        about = [f"opponent: {description}" if name and description else "", f"opponent's category: {category}" if category else ""]
        found[field["id"]] = (name or description, "; ".join(part for part in about if part))
    return found


def games(path: Path) -> list[dict[str, Any]]:
    """ The games of the file, in order, as rows of chess_games (less whose they are). """
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", path.read_text(encoding="utf-8"), count=1))
    names = opponents(root)
    rows = []
    for place, game in enumerate(root.iter("game"), start=1):
        field = {child.tag: (child.text or "").strip() for child in game}
        if field.get("opponentid") not in names:
            raise ChessXmlError(f"game {place}: no opponent {field.get('opponentid')!r}")
        if field.get("result") not in OUTCOMES:
            raise ChessXmlError(f"game {place}: the result {field.get('result')!r} is none of {', '.join(OUTCOMES)}")
        # the time control, else how long it was ("unlimited", "long"); where the file says both, how long it was is a remark
        length = known(field.get("length", UNKNOWN))
        time_control = known(field.get("timecontrol", UNKNOWN)) or length
        date_ymd, date_y = when(field.get("date", UNKNOWN))
        # a day no calendar has is kept as the file wrote it
        name, about = names[field["opponentid"]]
        remarks = [field.get("remark", ""), f"dated {field['date']} in chess.xml, a day its month does not have" if date_y else "",
                   f"length: {length}" if length and length != time_control else "", about]
        rows.append({
            "source_key": KEY.format(place),
            "color": "", "white": "", "black": "", "white_elo": None, "black_elo": None,
            "opponent": name, "outcome": OUTCOMES[field["result"]],
            "result": "*", "termination": "stalemate" if field["result"] == "pat" else "",
            "time_control": time_control[:50], "eco": "", "opening": "", "event": "", "site": "Over the board", "link": "",
            "plies": 0, "final_position": "", "pgn": "", "remark": "; ".join(part for part in remarks if part),
            "date_utcz": None, "date_ymd": date_ymd, "date_my": "", "date_y": date_y, "date_timezone": "",
        })
    return rows


def import_chess_xml(session: Session, owner: User, path: Path) -> dict[str, int]:
    """ Add the games of path that owner does not have yet. Does not commit. """
    have = set(session.scalars(select(ChessGame.source_key).where(ChessGame.owner_id == owner.id, ChessGame.source_key.startswith("chess.xml:"))))
    found = games(path)
    rows = [{**row, "owner_id": owner.id} for row in found if row["source_key"] not in have]
    for start in range(0, len(rows), BATCH):
        session.execute(insert(ChessGame).values(rows[start:start + BATCH]))
    session.flush()
    return {
        "games read": len(found), "added": len(rows), "already there": len(found) - len(rows),
        "dated only by their year": sum(row["date_y"] is not None for row in rows), "with no date": sum(row["date_ymd"] is None and row["date_y"] is None for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--email", required=True, help="email of the account that will own the games")
    parser.add_argument("--dry-run", action="store_true", help="do it all and print what was done, then roll it back")
    parser.add_argument("file", type=Path, help="the file to read")
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        try:
            owner = session.scalars(select(User).where(User.email == args.email)).first()
            if owner is None:
                raise ChessXmlError(f"no account for {args.email}: sign in once first")
            counts = import_chess_xml(session, owner, args.file)
        except (ChessXmlError, ET.ParseError, OSError) as e:
            print(f"import_chess_xml: {e}", file=sys.stderr)
            return 1
        who = f"{owner.email} (account {owner.id})"
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    summary = ", ".join(f"{count} {what}" for what, count in counts.items())
    print(f"{engine.url.render_as_string(hide_password=True)}: chess games of {args.file.name} for {who}: {summary}{' (dry run: rolled back)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
