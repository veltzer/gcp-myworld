// The pages of the world: concerts, museums, people, organizations and the rest.

import { $, api, showError } from "./core.js";
import { state } from "./library.js";
import { rerender } from "./sorting.js";
import { showRow } from "./views.js";

// view -> [page title, API path, singular, sidebar label]; the rows are the signed-in user's own
export const WORLDS = {
	concerts: ["My Concerts", "/api/concert-visits", "concert", "Concerts"],
	museums: ["My Museums", "/api/museum-visits", "museum", "Museums"],
	"audio-courses": ["Audio courses", "/api/audio-courses", "audio course", "Audio courses"],
	youtube: ["YouTube videos", "/api/youtube-videos", "YouTube video", "YouTube"],
	chess: ["Chess games", "/api/chess-games", "chess game", "Chess"],
	places: ["Places", "/api/places", "place", "Places"],
	cities: ["Cities", "/api/cities", "city", "Cities"],
	countries: ["Countries", "/api/countries", "country", "Countries"],
	people: ["People", "/api/people", "person", "People"],
	groups: ["Groups", "/api/groups", "group", "Groups"],
	organizations: ["Organizations", "/api/organizations", "organization", "Organizations"],
	"organization-types": ["Organization types", "/api/organization-types", "organization type", "Org"],
	// what a person does (performer, book author, ...); how they are related to people is a person relation
	"person-types": ["Professions", "/api/person-types", "profession", "Professions"],
	"relation-types": ["Relation types", "/api/relation-types", "relation type", "Org relations"],
	"person-relation-types": ["Person relation types", "/api/person-relation-types", "person relation type", "Person relations"],
	"person-organization-types": ["Person-org relation types", "/api/person-organization-types", "person-org relation type", "Person-org relations"],
	devices: ["Devices", "/api/devices", "device", "Devices"],
	// the locales table: the languages a title, a name, a reading or a copy owned can be in
	locales: ["Languages", "/api/locales", "language", "Languages"],
};

// views whose rows have a type -> the view of their enumeration
export const TYPED = { people: "person-types", organizations: "organization-types" };

// a view's name in ids: a world's noun ("museum-visit"), or a library kind ("book")
export function slug(view) {
	if (!(view in WORLDS)) {
		return view;
	}
	return WORLDS[view][2].toLowerCase().replace(/ /g, "-");
}

export const worldCache = {};

// how a game ended for the user, from the side they played and its result
const OUTCOMES = { "1-0": ["Won", "Lost"], "0-1": ["Lost", "Won"], "1/2-1/2": ["Drawn", "Drawn"] };

// A chess game as the page uses it: with its name, the opponent, both ratings by whose they are, and how it ended for the user
export function chessGame(game) {
	const white = game.color === "white";
	return {
		...game,
		name: `${game.white} vs ${game.black}`,
		opponent: white ? game.black : game.white,
		rating: white ? game.white_elo : game.black_elo,
		opponent_rating: white ? game.black_elo : game.white_elo,
		outcome: (OUTCOMES[game.result] || [])[white ? 0 : 1] || "No result",
	};
}

// The rows of a view, fetched. The chess games, 60,000 of them, come with the names of
// their fields said once and each game as its values, and are made rows here.
export async function fetchWorld(view) {
	const path = WORLDS[view][1];
	if (view !== "chess") {
		return api(path);
	}
	const { columns, rows } = await api(`${path}?compact=1`);
	return rows.map((values) => chessGame(Object.fromEntries(columns.map((column, index) => [column, values[index]]))));
}

export function el(tag, className, text) {
	const node = document.createElement(tag);
	if (className) {
		node.className = className;
	}
	if (text !== undefined && text !== null) {
		node.textContent = text;
	}
	return node;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// A date as precisely as it is known: a year, a month, a day, or a moment shown on
// the calendar of the place it happened.
export function formatDate(item) {
	if (!item.date) {
		return "";
	}
	const parts = item.date.split(/[-T]/);
	if (item.date_precision === "year") {
		return parts[0];
	}
	if (item.date_precision === "month") {
		return `${MONTHS[Number(parts[1]) - 1]} ${parts[0]}`;
	}
	if (item.date_precision === "day") {
		return `${Number(parts[2])} ${MONTHS[Number(parts[1]) - 1]} ${parts[0]}`;
	}
	try {
		return new Date(item.date).toLocaleDateString("en-GB", {
			timeZone: item.date_timezone || undefined,
			day: "numeric",
			month: "short",
			year: "numeric",
		});
	} catch (e) {
		return item.date.slice(0, 10);
	}
}

export function detail(list, label, value) {
	if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
		return;
	}
	const li = el("li");
	li.append(el("span", "label", label), Array.isArray(value) ? value.join(", ") : String(value));
	list.appendChild(li);
}

// Names as links to their place in the People or Organizations view, appended to parent.
// a list of links shows this many; the rest open with a click on "+N more"
const LINKS_SHOWN = 5;

// count values appended to parent by add(index, into), comma separated: the
// first LINKS_SHOWN, then a "+N more" button that shows the rest (and a
// "Show fewer" that folds them again). One left over is shown rather than "+1 more".
function appendLimited(parent, count, add) {
	const first = count <= LINKS_SHOWN + 1 ? count : LINKS_SHOWN;
	const item = (index, into) => {
		if (index > 0) {
			into.append(", ");
		}
		add(index, into);
	};
	for (let index = 0; index < first; index++) {
		item(index, parent);
	}
	if (first === count) {
		return;
	}
	const rest = el("span", "more-links-rest");
	rest.hidden = true;
	for (let index = first; index < count; index++) {
		item(index, rest);
	}
	const more = el("button", "text more-links", `+${(count - first).toLocaleString()} more`);
	more.type = "button";
	more.title = `Show all ${count.toLocaleString()}`;
	more.onclick = () => {
		rest.hidden = !rest.hidden;
		more.textContent = rest.hidden ? `+${(count - first).toLocaleString()} more` : "Show fewer";
		more.title = rest.hidden ? `Show all ${count.toLocaleString()}` : `Show only the first ${first}`;
		// the button follows what it shows
		parent.appendChild(more);
	};
	parent.append(rest, " ", more);
}

export function appendLinks(parent, view, rows) {
	appendLimited(parent, rows.length, (index, into) => {
		const row = rows[index];
		const a = el("a", "person-link", row.name);
		a.dir = "auto";
		a.href = `/library#${view}/${row.id}`;
		a.onclick = (event) => {
			event.preventDefault();
			showRow(view, row.id).catch((e) => showError(e.message));
		};
		into.appendChild(a);
	});
}

export function linksDetail(list, label, view, rows) {
	if (rows.length === 0) {
		return;
	}
	const li = el("li");
	li.appendChild(el("span", "label", label));
	appendLinks(li, view, rows);
	list.appendChild(li);
}

export function websiteDetail(list, url) {
	if (!url) {
		return;
	}
	const li = el("li");
	const a = el("a", null, "Website");
	a.href = url;
	a.target = "_blank";
	a.rel = "noopener";
	li.appendChild(a);
	list.appendChild(li);
}

// How the cards are laid out, picked with the buttons next to the search and
// remembered in this browser. Every layout is the same markup styled by a
// class on #cards, so switching never refetches anything.
const LAYOUTS = {
	list: "List",
	cards: "Cards",
	tiles: "Tiles",
	gallery: "Gallery",
	map: "Map",
};

const LAYOUT_KEY = "myworld.layout";

function savedLayout() {
	try {
		const saved = window.localStorage.getItem(LAYOUT_KEY);
		return saved in LAYOUTS ? saved : "cards";
	} catch (e) {
		return "cards";
	}
}

function applyLayout(layout) {
	state.layout = layout;
	for (const name of Object.keys(LAYOUTS)) {
		for (const box of [$("cards"), $("library-cards")]) {
			box.classList.toggle(`layout-${name}`, name === layout);
		}
	}
	for (const button of $("layouts").querySelectorAll("button")) {
		button.setAttribute("aria-pressed", String(button.dataset.layout === layout));
	}
}

export function setupLayouts() {
	const box = $("layouts");
	for (const [name, label] of Object.entries(LAYOUTS)) {
		const button = el("button", null, label);
		button.type = "button";
		button.dataset.layout = name;
		button.onclick = () => {
			applyLayout(name);
			rerender();
			try {
				window.localStorage.setItem(LAYOUT_KEY, name);
			} catch (e) {
				// private window or blocked storage: the choice lasts until reload
			}
		};
		box.appendChild(button);
	}
	applyLayout(savedLayout());
}
