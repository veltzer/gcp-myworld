/* globals Chess */
// A chess board: the picture of a position, and a game played through in its dialog.

import { $ } from "./core.js";
import { el } from "./worlds.js";

// the pieces as text (the FE0E after each keeps a phone from drawing it as an emoji)
const GLYPHS = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
const LIGHT = "#f0d9b5";
const DARK = "#b58863";
const MARKED = "#f6f669";
const FILES = "abcdefgh";
export const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR";

// The board as SVG. position: where the pieces stand, the first field of a FEN;
// flipped: seen from Black's side; marked: squares to light up ("e2", "e4": the move just made).
function boardSvg(position, flipped, marked = []) {
	const parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'];
	const ranks = position.split("/");
	for (let rank = 0; rank < 8; rank++) {
		// a rank as its eight squares: a digit is that many empty ones
		const squares = [...(ranks[rank] || "8")].flatMap((c) => (/\d/.test(c) ? Array(Number(c)).fill("") : [c]));
		for (let file = 0; file < 8; file++) {
			const x = (flipped ? 7 - file : file) * 10;
			const y = (flipped ? 7 - rank : rank) * 10;
			const name = `${FILES[file]}${8 - rank}`;
			const fill = marked.includes(name) ? MARKED : (rank + file) % 2 === 0 ? LIGHT : DARK;
			parts.push(`<rect x="${x}" y="${y}" width="10" height="10" fill="${fill}"/>`);
			const piece = squares[file];
			if (piece) {
				const white = piece === piece.toUpperCase();
				parts.push(
					`<text x="${x + 5}" y="${y + 8.1}" font-size="8.6" text-anchor="middle" font-family="'DejaVu Sans','Segoe UI Symbol','Noto Sans Symbols2','Arial Unicode MS',sans-serif" `
					+ `fill="${white ? "#fff" : "#111"}" stroke="${white ? "#111" : "#fff"}" stroke-width="${white ? 0.4 : 0.2}" paint-order="stroke">${GLYPHS[piece.toLowerCase()]}︎</text>`,
				);
			}
		}
	}
	parts.push("</svg>");
	return parts.join("");
}

// the pictures made so far: a page of cards asks for the same few hundred again and again
const images = new Map();

// The picture of a position, as the address of an image
export function boardImage(position, flipped = false, marked = []) {
	const key = `${position} ${flipped} ${marked.join("")}`;
	if (!images.has(key)) {
		if (images.size > 2000) {
			images.clear();
		}
		images.set(key, `data:image/svg+xml;charset=utf-8,${encodeURIComponent(boardSvg(position, flipped, marked))}`);
	}
	return images.get(key);
}

// Moves played from the start: the position after each (the start first), the squares each went
// between, and how many could be played (a game written wrongly stops being playable part way).
export function play(moves) {
	const chess = new Chess();
	const positions = [START];
	const squares = [[]];
	for (const san of moves) {
		const made = chess.move(san, { sloppy: true });
		if (!made) {
			break;
		}
		positions.push(chess.fen().split(" ")[0]);
		squares.push([made.from, made.to]);
	}
	return { positions, squares, played: positions.length - 1 };
}

// the game in the dialog: its moves and clocks, the position after each, the one shown, and the side it is seen from
const viewer = { moves: [], clocks: [], positions: [START], squares: [[]], at: 0, flipped: false };

function showMove(at) {
	viewer.at = Math.max(0, Math.min(at, viewer.positions.length - 1));
	const { moves, clocks, positions, squares, flipped } = viewer;
	const shown = viewer.at;
	$("chess-board").src = boardImage(positions[shown], flipped, squares[shown]);
	const number = Math.ceil(shown / 2);
	const side = shown % 2 === 1 ? "White" : "Black";
	const clock = clocks[shown - 1] ? `, ${clocks[shown - 1].replace(/^0:/, "")} left on the clock` : "";
	$("chess-board").alt = shown === 0 ? "The board before the first move" : `The board after ${side}'s move ${number}, ${moves[shown - 1]}`;
	let status = moves.length === 0 ? "The moves of this game were not recorded." : shown === 0 ? `Before the first move of ${Math.ceil(moves.length / 2)}.` : `Move ${number} of ${Math.ceil(moves.length / 2)}: ${side} played ${moves[shown - 1]}${clock}.`;
	if (positions.length - 1 < moves.length && shown === positions.length - 1) {
		status += ` The next move as written, ${moves[shown]}, cannot be played: the game is shown up to here.`;
	}
	$("chess-status").textContent = status;
	const last = positions.length - 1;
	$("chess-first").disabled = shown === 0;
	$("chess-previous").disabled = shown === 0;
	$("chess-next").disabled = shown === last;
	$("chess-last").disabled = shown === last;
	$("chess-flip").disabled = false;
	for (const button of $("chess-moves").querySelectorAll("button")) {
		const current = Number(button.dataset.at) === shown;
		button.classList.toggle("current", current);
		if (current) {
			// once the dialog is on screen: it is filled before it opens
			requestAnimationFrame(() => button.scrollIntoView({ block: "nearest" }));
		}
	}
}

// The board of the dialog: a game's moves to play through, opened at its end as its card shows it;
// with no game (one being added) the pieces as they start, and nothing to step through.
export function prepareBoard(game) {
	viewer.moves = game?.moves || [];
	viewer.clocks = game?.clocks || [];
	viewer.flipped = game?.color === "black";
	const { positions, squares } = play(viewer.moves);
	viewer.positions = positions;
	viewer.squares = squares;
	const list = $("chess-moves");
	list.replaceChildren();
	viewer.moves.forEach((san, index) => {
		if (index % 2 === 0) {
			list.appendChild(el("span", "chess-move-number", `${index / 2 + 1}.`));
		}
		const button = el("button", "chess-move", san);
		button.type = "button";
		button.dataset.at = index + 1;
		// a move after one that cannot be played is only read
		button.disabled = index + 1 > positions.length - 1;
		button.onclick = () => showMove(index + 1);
		list.appendChild(button);
	});
	if (viewer.moves.length === 0) {
		list.appendChild(el("span", "empty", game ? "No moves recorded" : "The moves show here once the game is added"));
	}
	showMove(positions.length - 1);
	if (!game) {
		$("chess-flip").disabled = true;
		$("chess-status").textContent = "Paste one game's PGN below.";
	}
}

export function setupBoard() {
	$("chess-first").onclick = () => showMove(0);
	$("chess-previous").onclick = () => showMove(viewer.at - 1);
	$("chess-next").onclick = () => showMove(viewer.at + 1);
	$("chess-last").onclick = () => showMove(viewer.positions.length - 1);
	$("chess-flip").onclick = () => {
		viewer.flipped = !viewer.flipped;
		showMove(viewer.at);
	};
	// the arrow keys step through the game while the board, its buttons or its moves have the focus
	$("chess-viewer").addEventListener("keydown", (event) => {
		const steps = { ArrowLeft: viewer.at - 1, ArrowRight: viewer.at + 1, Home: 0, End: viewer.positions.length - 1 };
		if (event.key in steps) {
			event.preventDefault();
			showMove(steps[event.key]);
		}
	});
}
