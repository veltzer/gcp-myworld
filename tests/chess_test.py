"""
The chess games: reading PGN (myworld/pgn.py), the page's routes
(myworld/world.py), the import (scripts/import_chess.py) and the checks.
"""

import datetime
import gzip
from pathlib import Path

import import_chess
import pytest
import webtest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from myworld import checks, pgn
from myworld.models import ChessGame, User
from tests.conftest import sign_in

# a game as Chess.com writes it: a moment, an address, the clocks, where it ended
LIVE = """[Event "Live Chess"]
[Site "Chess.com"]
[Date "2016.06.18"]
[Round "-"]
[White "mark_veltzer"]
[Black "nfloz84"]
[Result "0-1"]
[CurrentPosition "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq -"]
[ECO "A00"]
[ECOUrl "https://www.chess.com/openings/Barnes-Opening-Fools-Mate"]
[UTCDate "2016.06.18"]
[UTCTime "07:26:42"]
[WhiteElo "1031"]
[BlackElo "1156"]
[TimeControl "180"]
[Termination "nfloz84 won by checkmate"]
[Link "https://www.chess.com/game/live/1621079688"]

1. f3 {[%clk 0:02:58.4]} 1... e5 {[%clk 0:02:59.4]} 2. g4 {[%clk 0:02:57.7]} 2... Qh4# {[%clk 0:02:56.4]} 0-1
"""

# one as the old servers logged it: a day, no address, how it ended said in braces
OLD = """[Event "ICS Rated Chess Match"]
[Site "home"]
[Date "2001.03.04"]
[Round "?"]
[White "veltzer"]
[Black "AreaFiftyOne"]
[WhiteElo "1500"]
[Result "1-0"]
[TimeControl "120+12"]

1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#
{AreaFiftyOne checkmated} 1-0
"""

ENGINES = """[Event "GNU Chess game"]
[Site "work"]
[Date "1999.01.02"]
[Round "-"]
[White "GNUChess"]
[Black "GNUChess"]
[Result "1/2-1/2"]

1. e4 e5 1/2-1/2
"""

FOOLS_MATE = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR"
SCHOLARS_MATE = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR"


def test_a_file_is_its_games() -> None:
    games = pgn.split(LIVE + "\n" + OLD + "\n\n" + ENGINES)
    assert [pgn.parse(game).tags["White"] for game in games] == ["mark_veltzer", "veltzer", "GNUChess"]
    assert pgn.split("") == [] and pgn.split("\n\n") == []
    with pytest.raises(pgn.PgnError, match="no tags"):
        pgn.parse("1. e4 e5")


def test_a_game_is_read() -> None:
    live = pgn.parse(LIVE)
    assert [move.san for move in live.moves] == ["f3", "e5", "g4", "Qh4#"]
    assert [move.clock for move in live.moves] == ["0:02:58.4", "0:02:59.4", "0:02:57.7", "0:02:56.4"]
    fields = pgn.fields(live)
    assert fields["source_key"] == "chess.com:live:1621079688"
    assert fields["date_utcz"] == datetime.datetime(2016, 6, 18, 7, 26, 42) and fields["date_ymd"] is None
    assert (fields["white"], fields["black"], fields["white_elo"], fields["black_elo"]) == ("mark_veltzer", "nfloz84", 1031, 1156)
    assert (fields["result"], fields["termination"], fields["time_control"], fields["plies"]) == ("0-1", "nfloz84 won by checkmate", "180", 4)
    assert (fields["eco"], fields["opening"], fields["site"]) == ("A00", "Barnes Opening Fools Mate", "Chess.com")
    assert fields["pgn"] == LIVE
    old = pgn.fields(pgn.parse(OLD))
    # a day, the words in braces for how it ended, and a hash to tell it by
    assert (old["date_ymd"], old["date_utcz"]) == (datetime.date(2001, 3, 4), None)
    assert (old["termination"], old["black_elo"], old["link"], old["plies"]) == ("AreaFiftyOne checkmated", None, "", 7)
    assert old["source_key"].startswith("sha256:") and old["source_key"] == pgn.key(pgn.parse(OLD + "\n\n"))


def test_what_old_files_write() -> None:
    def moves(text: str) -> list[str]:
        return [move.san for move in pgn.parse('[White "a"]\n[Black "b"]\n\n' + text).moves]

    # a pawn on the last rank that does not say what it becomes is a queen; mail wrote "=" as "=3D", and ended a line it broke with "="
    assert moves("57. a1 58. dxe8+ 59. b8=3DN 60. h1=R") == ["a1=Q", "dxe8=Q+", "b8=N", "h1=R"]
    assert moves("13. Qd5 =\nf6 14. =\nRxe8+") == ["Qd5", "f6", "Rxe8+"]
    # castling written with zeros, marks, variations and what is said beside a move are not moves
    assert moves("1. e4! e5?? 2. 0-0 $1 (2. Nf3 Nc6) 2... 0-0-0 {good} ; the rest\n3. Nf3 *") == ["e4", "e5", "O-O", "O-O-O", "Nf3"]
    # a line for the program that saved the file is not the game's, and neither is the memory it wrote after one
    said = pgn.parse('[White "a"]\n[Black "b"]\n\n1. e4\n%eboard:clue:x\n{a ran out of time and b has no material to ma\x88\x12} 1/2-1/2')
    assert (said.said, [move.san for move in said.moves]) == ("a ran out of time and b has no material to mate", ["e4"])
    assert pgn.decode(b"1. e4 {\xd8\xef\x00ok}") == "1. e4 {ok}"
    # a date as far as it is known
    for date, wanted in (("1996.07.??", {"date_my": "07-1996"}), ("1996.??.??", {"date_y": 1996}), ("????.??.??", {}), ("1996.02.30", {})):
        fields = pgn.fields(pgn.parse(f'[White "a"]\n[Date "{date}"]\n\n*'))
        assert {key: value for key, value in fields.items() if key.startswith("date_") and value} == wanted


def test_the_page_of_games(app: webtest.TestApp) -> None:
    sign_in(app)
    added = app.post_json("/api/chess-games", {"pgn": LIVE, "color": "white", "remark": "ouch"}, status=201).json
    assert (added["name"], added["color"], added["result"], added["plies"], added["remark"]) == ("mark_veltzer vs nfloz84", "white", "0-1", 4, "ouch")
    # the moment it was played, and where its site says it ended
    assert (added["date"], added["date_precision"], added["date_timezone"]) == ("2016-06-18T07:26:42Z", "time", "UTC")
    assert added["position"] == FOOLS_MATE
    # one game opened has its text and its moves, with the clock after each
    one = app.get(f"/api/chess-games/{added['id']}").json
    assert (one["pgn"], one["moves"], one["clocks"][0]) == (LIVE, ["f3", "e5", "g4", "Qh4#"], "0:02:58.4")
    # the same game is not added twice, and many are not added at once
    assert app.post_json("/api/chess-games", {"pgn": LIVE, "color": "white"}, status=409).json == {"error": "that game is in your list already"}
    assert "one game at a time" in app.post_json("/api/chess-games", {"pgn": LIVE + OLD, "color": "white"}, status=400).json["error"]
    assert app.post_json("/api/chess-games", {"pgn": "1. e4 e5", "color": "white"}, status=400).json["error"].startswith("pgn: not a game")
    assert app.post_json("/api/chess-games", {"pgn": OLD, "color": "green"}, status=400).json["error"].startswith("color:")
    assert app.post_json("/api/chess-games", {"pgn": 7, "color": "white"}, status=400).json == {"error": "pgn: expected a string"}
    # a game whose text does not say where it ended has no picture until the page, which plays the moves, says
    old = app.post_json("/api/chess-games", {"pgn": OLD, "color": "white"}, status=201).json
    assert (old["position"], old["date"], old["date_precision"], old["termination"]) == ("", "2001-03-04", "day", "AreaFiftyOne checkmated")
    assert app.get(f"/api/chess-games/{old['id']}").json["clocks"] == []
    app.put_json(f"/api/chess-games/{old['id']}", {"color": "white", "final_position": "pieces"}, status=400)
    edited = app.put_json(f"/api/chess-games/{old['id']}", {"color": "white", "remark": "quick", "final_position": SCHOLARS_MATE}).json
    # an edit without the text keeps the game as it is
    assert (edited["position"], edited["remark"], edited["name"], edited["plies"]) == (SCHOLARS_MATE, "quick", "veltzer vs AreaFiftyOne", 7)
    # one with no move made ended where it started
    unplayed = app.post_json("/api/chess-games", {"pgn": '[White "a"]\n[Black "b"]\n\n*', "color": "black"}, status=201).json
    assert (unplayed["position"], unplayed["result"], unplayed["date"]) == (pgn.START_POSITION, "*", None)
    # the list, newest first; compact, it says the fields once and each game as its values
    listed = app.get("/api/chess-games").json
    assert [game["name"] for game in listed] == ["mark_veltzer vs nfloz84", "veltzer vs AreaFiftyOne", "a vs b"]
    assert "pgn" not in listed[0]
    compact = app.get("/api/chess-games?compact=1").json
    assert "name" not in compact["columns"]
    assert [dict(zip(compact["columns"], row, strict=True)) for row in compact["rows"]] == [{key: value for key, value in game.items() if key != "name"} for game in listed]
    stats = app.get("/api/stats").json
    assert stats["chess_games"] == 3
    assert stats["chess_by_outcome"] == [{"name": "Lost", "count": 1}, {"name": "No result", "count": 1}, {"name": "Won", "count": 1}]
    assert stats["chess_by_year"] == [{"year": 2001, "count": 1}, {"year": 2016, "count": 1}]
    # another account sees none of it
    sign_in(app, sub="someone-else")
    assert app.get("/api/chess-games?compact=1").json["rows"] == []
    app.get(f"/api/chess-games/{added['id']}", status=404)
    assert app.get("/api/stats").json["chess_games"] == 0


def owner(session: Session) -> User:
    user = User(email="me@example.com")
    session.add(user)
    session.flush()
    return user


def test_the_import(engine: Engine, tmp_path: Path) -> None:
    (tmp_path / "games.pgn.gz").write_bytes(gzip.compress((OLD + "\n" + ENGINES + "\n" + OLD).encode()))
    (tmp_path / "chesscom.pgn").write_text(LIVE, encoding="UTF8")
    (tmp_path / "notes.txt").write_text("not a game", encoding="UTF8")
    handles = frozenset({"veltzer", "mark_veltzer"})
    with Session(engine) as session:
        me = owner(session)
        paths = import_chess.files(tmp_path)
        assert [path.name for path in paths] == ["chesscom.pgn", "games.pgn.gz"]
        counts = import_chess.import_chess(session, me, paths, handles)
        assert counts == {"games read": 4, "added": 2, "already there": 0, "twice in the files": 1, "not the user's": 1, "with a move that cannot be played": 0}
        games = {game.white: game for game in session.scalars(select(ChessGame).where(ChessGame.owner_id == me.id))}
        # the side the user played, and where the pieces ended: said by the site, or found by playing the moves
        assert (games["mark_veltzer"].color, games["mark_veltzer"].final_position, games["mark_veltzer"].date_timezone) == ("white", FOOLS_MATE, "UTC")
        assert (games["veltzer"].color, games["veltzer"].final_position, games["veltzer"].date_timezone) == ("white", SCHOLARS_MATE, "")
        assert games["veltzer"].pgn == OLD
        # run again, nothing is added, and a remark written since stays
        games["veltzer"].remark = "mine"
        again = import_chess.import_chess(session, me, paths, handles)
        assert (again["added"], again["already there"]) == (0, 2)
        assert session.scalars(select(ChessGame.remark).where(ChessGame.white == "veltzer")).all() == ["mine"]
        # a name is the user's only as it is written
        assert import_chess.import_chess(session, owner_of(session, "other@example.com"), paths, frozenset({"veltzerdoron", "Veltzer"}))["added"] == 0


def owner_of(session: Session, email: str) -> User:
    user = User(email=email)
    session.add(user)
    session.flush()
    return user


def test_what_the_import_refuses(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        me = owner(session)
        with pytest.raises(import_chess.ChessImportError, match="no .pgn or .pgn.gz files"):
            import_chess.files(tmp_path)
        both = tmp_path / "both.pgn"
        both.write_text(OLD.replace("AreaFiftyOne", "mark"), encoding="UTF8")
        with pytest.raises(import_chess.ChessImportError, match="both players are the user"):
            import_chess.import_chess(session, me, [both], frozenset({"veltzer", "mark"}))
        # where the site says it ended is not where its moves end
        wrong = tmp_path / "wrong.pgn"
        wrong.write_text(LIVE.replace("2... Qh4#", "2... Qf6"), encoding="UTF8")
        with pytest.raises(import_chess.ChessImportError, match="the moves end at"):
            import_chess.import_chess(session, me, [wrong], frozenset({"mark_veltzer"}))
        # a move that cannot be played: the game is added as written, ending where its last legal move left it
        broken = tmp_path / "broken.pgn"
        broken.write_text(OLD.replace("4. Qxf7#", "4. Qxa8 Ke7"), encoding="UTF8")
        counts = import_chess.import_chess(session, me, [broken], frozenset({"veltzer"}))
        assert (counts["added"], counts["with a move that cannot be played"]) == (1, 1)
        game = session.scalars(select(ChessGame)).one()
        assert (game.plies, game.final_position) == (8, "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR")


def test_the_checks(engine: Engine) -> None:
    with Session(engine) as session:
        me = owner(session)
        good = {"owner_id": me.id, "color": "white", "pgn": OLD, "date_y": 2001, "final_position": SCHOLARS_MATE}
        session.add_all([
            ChessGame(source_key="1", white="veltzer", black="AreaFiftyOne", **good),
            ChessGame(source_key="2", white="veltzer", black="Undated", **{**good, "date_y": None}),
            ChessGame(source_key="3", white="veltzer", black="", **good),
            ChessGame(source_key="4", white="twin", black="twin", **good),
            ChessGame(source_key="5", white="veltzer", black="Unplayed", **{**good, "final_position": ""}),
            ChessGame(source_key="6", white="veltzer", black="Odd", **{**good, "final_position": "8/8"}),
        ])
        session.commit()

        def found(name: str) -> list[tuple[str, str]]:
            result = checks.CHECKS[name].run(session)
            assert result.checked == 6
            return [(problem.subject.split(" (")[0], problem.message) for problem in result.problems]

        assert found("chess-dates") == [("veltzer vs Undated", "has no date")]
        assert found("chess-players") == [("veltzer vs ", "does not name both players"), ("twin vs twin", "has the same player on both sides")]
        assert found("chess-positions") == [("veltzer vs Unplayed", "has no final position"), ("veltzer vs Odd", "has the final position '8/8', which is not eight ranks of pieces")]
        assert checks.CHECKS["chess-dates"].run(session).problems[0].link == "chess/2"
