"""
Reading PGN, the text chess games are kept in: a file of games is split
into its games, and a game into its tags ([White "veltzer"]), its moves as
they were written (SAN: "e4", "Nxf7+", "O-O"), the clock after each where
the site wrote one, and how it ended. Nothing here knows the rules of chess:
the moves are read, not played (the page plays them, and
scripts/import_chess.py does when it imports).
"""

import dataclasses
import datetime
import hashlib
import re
from typing import Any

from myworld import timeutil

RESULTS = ("1-0", "0-1", "1/2-1/2", "*")
WHITE, BLACK = "white", "black"
# the side the user played; "" where it is not known (a game recorded only by how it ended)
COLORS = (WHITE, BLACK, "")
# how a game ended for the user; "" where that is not known
WON, LOST, DRAWN = "won", "lost", "drawn"
OUTCOMES = (WON, LOST, DRAWN, "")
_OUTCOME = {
    (WHITE, "1-0"): WON, (BLACK, "0-1"): WON, (WHITE, "0-1"): LOST, (BLACK, "1-0"): LOST,
    (WHITE, "1/2-1/2"): DRAWN, (BLACK, "1/2-1/2"): DRAWN,
}

# what is not text: control characters (a tab and a line end are), and what a decoder could not read
_NOT_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f�]")
_TAG = re.compile(r'^\[(\w+)\s+"(.*)"\]\s*$')
# a comment in braces or from a ";" to the end of its line, a variation's bracket, a mark ($3), a move number ("12." or "12..."), or a word
_TOKEN = re.compile(r"\{[^}]*\}?|;[^\n]*|\(|\)|\$\d+|\d+\.+|[^\s{}();]+")
_CLOCK = re.compile(r"\[%clk\s+([0-9:.]+)\]")
_COMMAND = re.compile(r"\[%[^\]]*\]")
# between the moves: a mark ($3), a move number, and the "=" mail ends a line it broke with
_NOT_A_MOVE = re.compile(r"\$\d+|\d+\.+|[=#+!?]+")
# a pawn that reaches the last rank and does not say what it becomes ("a1", "dxe8+"): old servers wrote a queen so
_BARE_PROMOTION = re.compile(r"^((?:[a-h]x)?[a-h][18])([+#]?)$")
# the piece placement of a position, the first field of a FEN: eight ranks of pieces and gaps
POSITION = re.compile(r"^[pnbrqkPNBRQK1-8]{1,8}(/[pnbrqkPNBRQK1-8]{1,8}){7}$")
START_POSITION = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
# eboard, the program many of the old games were saved by, sometimes wrote memory after this sentence
_NO_MATERIAL = re.compile(r"(\S+ ran out of time and \S+ has no material to ma)\w*.*", re.DOTALL)


class PgnError(Exception):
    """ Text that is not a game. """


@dataclasses.dataclass(frozen=True)
class Move:
    san: str
    # what the mover's clock showed after it ("0:02:58.4"), "" where none was written
    clock: str = ""


@dataclasses.dataclass(frozen=True)
class Game:
    # the game as it was written, less what is not text
    text: str
    tags: dict[str, str]
    moves: list[Move]
    # the last thing said in braces that is not a clock: how an old game says it ended ("veltzer resigns")
    said: str


def clean(text: str) -> str:
    """ Text as it can be kept: without control characters and unreadable bytes, its lines ending the one way. """
    return _NOT_TEXT.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def decode(data: bytes) -> str:
    """ The text of a PGN file: UTF-8, with what is not (a few old files have memory written into them) left out. """
    return clean(data.decode("utf-8", errors="replace"))


def split(text: str) -> list[str]:
    """ The games of a file, each as its own text: a game starts at its [Event tag. """
    games: list[list[str]] = []
    for line in clean(text).split("\n"):
        # (a game before which nothing was written yet is not begun twice)
        if not games or (line.startswith("[Event ") and any(part.strip() for part in games[-1])):
            games.append([])
        games[-1].append(line)
    return ["\n".join(lines).strip() + "\n" for lines in games if any(line.strip() for line in lines)]


def _san(word: str) -> str:
    """ A move as it is played: castling with the letter O, no "!?" after it, and a pawn on the last rank a queen when it does not say. """
    # (some old games were saved from mail, which wrote "=" as "=3D")
    word = word.rstrip("!?").replace("=3D", "=").replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    return _BARE_PROMOTION.sub(r"\1=Q\2", word)


def parse(text: str) -> Game:
    """ One game: its tags, and its moves in the order they were played (variations left out). """
    text = clean(text).strip() + "\n"
    tags: dict[str, str] = {}
    body: list[str] = []
    for line in text.split("\n"):
        tag = _TAG.match(line)
        if tag and not body:
            tags[tag.group(1)] = tag.group(2).replace('\\"', '"').replace("\\\\", "\\").strip()
        elif line.startswith("%"):
            # a line for the program that wrote the file, not part of the game
            continue
        elif line.strip() or body:
            body.append(line)
    if not tags:
        raise PgnError("not a game: it has no tags ([White \"...\"], [Black \"...\"], ...)")
    moves: list[Move] = []
    said = ""
    depth = 0
    for token in _TOKEN.findall("\n".join(body)):
        if token.startswith(";"):
            continue
        if token.startswith("{"):
            clock = _CLOCK.search(token)
            if clock and moves and depth == 0 and not moves[-1].clock:
                moves[-1] = Move(moves[-1].san, clock.group(1))
            words = " ".join(_COMMAND.sub("", token.strip("{}")).split())
            if words and depth == 0:
                said = words
        elif token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and token not in RESULTS and not _NOT_A_MOVE.fullmatch(token):
            moves.append(Move(_san(token)))
    return Game(text=text, tags=tags, moves=moves, said=_NO_MATERIAL.sub(r"\1te", said))


def outcome(color: str, result: str) -> str:
    """ How a game ended for the user, from the side they played and its result: "" when either is not known. """
    return _OUTCOME.get((color, result), "")


def opponent(color: str, white: str, black: str) -> str:
    """ Whom the user played: the other side's name ("" when the side the user played is not known). """
    return black if color == WHITE else white if color == BLACK else ""


def name(white: str, black: str, opponent: str) -> str:
    """ What a game is called: its two sides, or, recorded without them, whom the user played. """
    return f"{white} vs {black}" if white or black else f"against {opponent}"


def _number(value: str) -> int | None:
    return int(value) if re.fullmatch(r"\d{1,5}", value) else None


def _when(tags: dict[str, str]) -> dict[str, Any]:
    """ When it was played, as precisely as the tags say: the moment (UTCDate and UTCTime), else the day, the month or the year of Date. """
    utc = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", tags.get("UTCDate", ""))
    time = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})", tags.get("UTCTime", ""))
    when: dict[str, Any] = {"date_utcz": None, "date_ymd": None, "date_my": "", "date_y": None}
    try:
        if utc and time:
            year, month, day, hour, minute, second = (int(part) for part in (*utc.groups(), *time.groups()))
            when["date_utcz"] = timeutil.naive_utc(year, month, day, hour, minute, second)
            return when
        date = re.fullmatch(r"(\d{4})\.(\d{2}|\?\?)\.(\d{2}|\?\?)", tags.get("Date", ""))
        if date is None:
            return when
        said_year, said_month, said_day = date.groups()
        if "?" not in said_month and "?" not in said_day:
            when["date_ymd"] = datetime.date(int(said_year), int(said_month), int(said_day))
        elif "?" not in said_month and 1 <= int(said_month) <= 12:
            when["date_my"] = f"{said_month}-{said_year}"
        else:
            when["date_y"] = int(said_year)
    except ValueError:
        # a date no calendar has: not known
        pass
    return when


def _opening(tags: dict[str, str]) -> str:
    """ What the opening is called: as the game says, else as the address of its page at Chess.com does. """
    if tags.get("Opening"):
        return " ".join(part for part in (tags["Opening"], tags.get("Variation", "")) if part)
    page = tags.get("ECOUrl", "").rstrip("/").rsplit("/", 1)[-1] if "/openings/" in tags.get("ECOUrl", "") else ""
    return page.replace("-", " ")


def key(game: Game) -> str:
    """
    What tells a game from every other, so that one imported twice is one:
    its address at the site it was played on when it has one, else a hash of
    who played whom, when, and every move.
    """
    link = re.fullmatch(r"https://www\.chess\.com/game/(\w+)/(\d+)", game.tags.get("Link", ""))
    if link:
        return f"chess.com:{link.group(1)}:{link.group(2)}"
    told = "\n".join([*(game.tags.get(tag, "") for tag in ("Event", "Site", "Date", "Time", "Round", "White", "Black", "Result")), *(move.san for move in game.moves)])
    return "sha256:" + hashlib.sha256(told.encode()).hexdigest()


def fields(game: Game) -> dict[str, Any]:
    """ The columns of a game (models.ChessGame) its text says: all but whose it is, which side they played, and where it ended. """
    tags = game.tags
    result = tags.get("Result", "*")
    return {
        "source_key": key(game),
        **_when(tags),
        "white": tags.get("White", "")[:100],
        "black": tags.get("Black", "")[:100],
        "white_elo": _number(tags.get("WhiteElo", "")),
        "black_elo": _number(tags.get("BlackElo", "")),
        "result": result if result in RESULTS else "*",
        "termination": (tags.get("Termination") or tags.get("ICCResult") or game.said)[:300],
        "time_control": tags.get("TimeControl", "")[:50],
        "eco": tags.get("ECO", "")[:10],
        "opening": _opening(tags)[:300],
        "event": tags.get("Event", "")[:200],
        "site": tags.get("Site", "")[:100],
        "link": tags.get("Link", "")[:500],
        "plies": len(game.moves),
        "pgn": game.text,
    }
