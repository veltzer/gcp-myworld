// The pages of the world: concerts, museums, people, organizations and the rest.

import { $, VISIT, api, pageHref, showError } from "./core.js";
import { state } from "./library.js";
import { rerender } from "./sorting.js";
import { showRow } from "./views.js";

// view -> [page title, API path, singular, sidebar label]; the rows are the signed-in user's own,
// but on the shared pages (SHARED_VIEWS), whose rows are everyone's
export const WORLDS = {
	concerts: ["My Concerts", "/api/concert-visits", "concert", "Concerts"],
	// the user's museum visits, a card for each museum with its visits to it
	museums: ["My Museum visits", "/api/museum-visits", "museum visit", "Museum visits"],
	"audio-courses": ["Audio courses", "/api/audio-courses", "audio course", "Audio courses"],
	youtube: ["YouTube videos", "/api/youtube-videos", "YouTube video", "YouTube"],
	chess: ["Chess games", "/api/chess-games", "chess game", "Chess"],
	places: ["Places", "/api/places", "place", "Places"],
	cities: ["Cities", "/api/cities", "city", "Cities"],
	countries: ["Countries", "/api/countries", "country", "Countries"],
	currencies: ["Currencies", "/api/currencies", "currency", "Currencies"],
	// what a place is (museum, concert venue, ...) and what a visit was (museum visit, ...)
	"place-kinds": ["Place kinds", "/api/place-kinds", "place kind", "Place kinds"],
	"visit-types": ["Visit types", "/api/visit-types", "visit type", "Visit types"],
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

// The pages whose rows are shared by everyone: the same for every account, with nothing personal
// on them, changed by admins only (the server refuses anyone else). The sidebar lists them apart.
export const SHARED_VIEWS = new Set(["places", "cities", "countries", "currencies", "place-kinds", "visit-types", "locales"]);

export function isAdmin() {
	return state.config.user?.role === "admin";
}

// whether the signed-in user may change the shared data by hand now: an admin who turned on
// Edit shared data in Settings (it starts off, so shared data is not changed by accident)
export function editsShared() {
	return isAdmin() && state.config.user?.edit_shared === true;
}

// why the shared rows cannot be changed now: one who is no admin never may; an admin first turns on
// Edit shared data in Settings; in a view nothing is ever changed
export function sharedLockedWhy() {
	if (VISIT) {
		return "This is a view: nothing can be changed here";
	}
	return isAdmin() ? "Shared data is locked: turn on Edit shared data in Settings to change it" : "Shared by everyone: only an admin changes it";
}

// whether the signed-in user may add, change and delete the rows of view
export function canChange(view) {
	if (VISIT) {
		return false;
	}
	return !SHARED_VIEWS.has(view) || editsShared();
}

// A page whose cards are not what it counts: the museum visits, a card per museum with the
// visits to it, count the visits. (items) -> [how many, what they are]; one not here counts its cards
export const COUNTS = {
	museums: (items) => {
		const visits = items.reduce((n, museum) => n + museum.visits.length, 0);
		return [visits, `${visits === 1 ? "visit" : "visits"} to ${items.length.toLocaleString()} ${items.length === 1 ? "museum" : "museums"}`];
	},
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

// how a game ended for the user, as the server keeps it, in words
const OUTCOMES = { won: "Won", lost: "Lost", drawn: "Drawn" };
// the side the user played, in words ("" where it is not known: a game recorded only by how it ended)
export const SIDES = { white: "White", black: "Black", "": "Not known" };

// A chess game as the page uses it: with its name, both ratings by whose they are, and how it ended for the user in words
export function chessGame(game) {
	const white = game.color === "white";
	const known = game.color !== "";
	return {
		...game,
		name: game.white || game.black ? `${game.white} vs ${game.black}` : `against ${game.opponent}`,
		rating: known ? (white ? game.white_elo : game.black_elo) : null,
		opponent_rating: known ? (white ? game.black_elo : game.white_elo) : null,
		outcome: OUTCOMES[game.outcome] || "No result",
	};
}

// the views whose lists may be long (60,000 chess games, the cities of the world): they come with
// the names of their fields said once and each row as its values, and are made rows here
const COMPACT = { chess: chessGame, cities: (city) => city };

// The rows of a view, fetched.
export async function fetchWorld(view) {
	const path = WORLDS[view][1];
	if (!(view in COMPACT)) {
		return api(path);
	}
	const { columns, rows } = await api(`${path}?compact=1`);
	return rows.map((values) => COMPACT[view](Object.fromEntries(columns.map((column, index) => [column, values[index]]))));
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

// whether a view's visitor can open view: one of the data sets it shows (on the library page, every one)
export function inView(view) {
	return !state.config.visit || state.config.visit.datasets.includes(view);
}

export function appendLinks(parent, view, rows) {
	appendLimited(parent, rows.length, (index, into) => {
		const row = rows[index];
		if (!inView(view)) {
			// in a view that does not show them: the name, not a link that leads nowhere
			const name = el("span", "person-name", row.name);
			name.dir = "auto";
			into.appendChild(name);
			return;
		}
		const a = el("a", "person-link", row.name);
		a.dir = "auto";
		a.href = pageHref(`${view}/${row.id}`);
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

// The top right corner of a card: its icons (its website, its place on the map, how a person is connected), in one row.
export function cornerOf(card) {
	let corner = card.querySelector(":scope > .card-corner");
	if (!corner) {
		corner = el("div", "card-corner");
		card.appendChild(corner);
	}
	return corner;
}

// a globe (Material "language")
const WEBSITE_ICON =
	'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95a15.65 15.65 0 0 0-1.38-3.56A8.03 8.03 0 0 1 18.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56A7.987 7.987 0 0 1 5.08 16zm2.95-8H5.08a7.987 7.987 0 0 1 4.33-3.56A15.65 15.65 0 0 0 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 0 1-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z"/></svg>';

// The website of a card's row, as a globe in its corner, opening in a new tab; disabled, in the same place, when it has none.
export function websiteButton(card, url, label = "Website") {
	let button;
	if (url) {
		button = el("a", "icon-button website-button");
		button.href = url;
		button.target = "_blank";
		button.rel = "noopener";
		button.title = `${label}: ${url}`;
	} else {
		button = el("button", "icon-button website-button");
		button.type = "button";
		button.disabled = true;
		button.title = `No ${label.toLowerCase()}: add it in the dialog`;
	}
	button.setAttribute("aria-label", button.title);
	button.innerHTML = WEBSITE_ICON;
	cornerOf(card).appendChild(button);
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
