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
	// Your audio books: the shared audio books, filtered to those the user heard a version of (with their rating and review);
	// and the versions of them heard (Audible, MP3)
	"audio-books-heard": ["Your audio books", "/api/audio-books-heard", "audio book heard", "Your audio books"],
	"audio-book-listens": ["Audio book listens", "/api/audio-book-listens", "audio book listen", "Audio book listens"],
	// Your podcasts: the shared podcasts, filtered to those the user heard an episode of (with their rating and review);
	// and the episodes of them heard
	"podcasts-heard": ["Your podcasts", "/api/podcasts-heard", "podcast heard", "Your podcasts"],
	"episodes-heard": ["Episodes heard", "/api/episodes-heard", "episode heard", "Episodes heard"],
	// each time the user watched a film (a shared one), or means to
	"film-watches": ["Film watches", "/api/film-watches", "film watch", "Film watches"],
	// and each time they watched a series (a film of another kind), or mean to
	"series-watches": ["Series watches", "/api/series-watches", "series watch", "Series watches"],
	youtube: ["YouTube videos", "/api/youtube-videos", "YouTube video", "YouTube"],
	chess: ["Chess games", "/api/chess-games", "chess game", "Chess"],
	places: ["Places", "/api/places", "place", "Places"],
	// every podcast, and every episode of them its feed has
	podcasts: ["Podcasts", "/api/podcasts", "podcast", "Podcasts"],
	"podcast-episodes": ["Podcast episodes", "/api/podcast-episodes", "podcast episode", "Podcast episodes"],
	// every audio book, and every version of them (Audible, MP3)
	"audio-books": ["Audio books", "/api/audio-books", "audio book", "Audio books"],
	"audio-book-versions": ["Audio book versions", "/api/audio-book-versions", "audio book version", "Audio book versions"],
	// every film
	films: ["Films", "/api/films", "film", "Films"],
	// every series
	series: ["Series", "/api/series", "series", "Series"],
	cities: ["Cities", "/api/cities", "city", "Cities"],
	countries: ["Countries", "/api/countries", "country", "Countries"],
	currencies: ["Currencies", "/api/currencies", "currency", "Currencies"],
	// what a place is (museum, concert venue, ...) and what a visit was (museum visit, ...)
	"place-kinds": ["Place kinds", "/api/place-kinds", "place kind", "Place kinds"],
	"visit-types": ["Visit types", "/api/visit-types", "visit type", "Visit types"],
	people: ["People", "/api/people", "person", "People"],
	groups: ["Groups", "/api/groups", "group", "Groups"],
	organizations: ["Organizations", "/api/organizations", "organization", "Organizations"],
	"organization-types": ["Organization tags", "/api/organization-types", "organization tag", "Organization tags"],
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
export const SHARED_VIEWS = new Set(["places", "podcasts", "podcast-episodes", "audio-books", "audio-book-versions", "films", "series", "cities", "countries", "currencies", "place-kinds", "visit-types", "locales"]);

// The pages that are shared data filtered for the user, not rows of their own: view -> what they are.
// The sidebar marks them with a filter; their rows come by what the user does elsewhere, so + stays, disabled.
export const FILTERED_VIEWS = {
	"podcasts-heard": "The shared Podcasts, filtered to the ones you heard an episode of: hearing an episode (Episodes heard) adds its podcast here",
	"audio-books-heard": "The shared Audio books, filtered to the ones you heard a version of: hearing a version (Audio book listens) adds its book here",
};

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

// the longest value of a card kept on one line
const VALUE_WHOLE = 40;

export function detail(list, label, value) {
	if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
		return;
	}
	const text = Array.isArray(value) ? value.join(", ") : String(value);
	// a label with a short value (a date, a length, a place: "Last heard 2026-03-27") is never broken across lines;
	// with a long text (a review) only the label is kept whole, and the text wraps
	const li = el("li", text.length > VALUE_WHOLE ? "" : "nowrap");
	li.append(el("span", "label nowrap", label), text);
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
	cornerOf(card).appendChild(linkButton(url, label, WEBSITE_ICON, "website-button"));
}

// The sites a card links to, each its own mark in one colour like every corner icon (Simple Icons,
// CC0; Open Library is the Internet Archive's, Simania, which has no mark, its initial, and The Great
// Courses' the flames of its logo): key -> [site, svg]
const brand = (path) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
const SITES = {
	imdb: ["IMDb", brand("M22.378 0H1.622a1.72 1.72 0 0 0-1.62 1.595L0 22.378c.058.876.712 1.543 1.556 1.62l.045.002h20.797l.043-.002A1.723 1.723 0 0 0 24 22.29V1.71A1.72 1.72 0 0 0 22.415.002zm0 .496a1.214 1.214 0 0 1 1.125 1.214v20.58c0 .637-.487 1.16-1.104 1.214H1.602a1.214 1.214 0 0 1-1.106-1.126V1.628c.041-.61.522-1.092 1.126-1.132zM4.795 8.26v7.364H2.89V8.26zm6.537 0v7.364H9.671v-4.97L9 15.624H7.813l-.699-4.862-.006 4.862H5.44V8.26h2.468c.075.448.149.97.23 1.574l.272 1.871.44-3.445zm2.977 1.33q.112.06.142.203c.028.095.035.311.035.644v2.855c0 .488-.035.786-.096.895q-.092.171-.502.17V9.52c.204 0 .346.02.421.068m-.02 6.034c.454 0 .8-.027 1.024-.074q.345-.072.57-.265a.96.96 0 0 0 .324-.522c.061-.224.102-.665.102-1.322v-2.584q-.002-1.047-.074-1.403a1.3 1.3 0 0 0-.313-.644c-.169-.197-.42-.333-.745-.421-.32-.081-.854-.129-1.77-.129h-1.424v7.364zm5.14-1.783q-.001.529-.055.671c-.033.095-.19.142-.305.142-.108 0-.19-.047-.224-.135q-.06-.134-.06-.623v-1.947q.002-.501.054-.624.052-.121.217-.122c.115 0 .27.041.311.142q.061.145.061.604zm-2.475-5.58v7.363h1.715l.115-.468q.233.285.516.428c.182.088.46.135.678.135.304 0 .563-.075.78-.237a1.05 1.05 0 0 0 .42-.563c.054-.217.088-.543.088-.984v-2.067a7 7 0 0 0-.034-.868 1 1 0 0 0-.17-.42 1 1 0 0 0-.427-.333 1.929 1.929 0 0 0-1.342.013 1.6 1.6 0 0 0-.509.4v-2.4z")],
	tmdb: ["TMDB", brand("M6.62 12a2.29 2.29 0 0 1 2.292-2.295h-.013A2.29 2.29 0 0 1 11.189 12a2.29 2.29 0 0 1-2.29 2.291h.013A2.29 2.29 0 0 1 6.62 12m10.72-4.062h4.266a2.29 2.29 0 0 0 2.29-2.291 2.29 2.29 0 0 0-2.29-2.296H17.34a2.29 2.29 0 0 0-2.291 2.296 2.29 2.29 0 0 0 2.29 2.29zM2.688 20.645h8.285a2.29 2.29 0 0 0 2.291-2.292 2.29 2.29 0 0 0-2.29-2.295H2.687a2.29 2.29 0 0 0-2.291 2.295 2.29 2.29 0 0 0 2.29 2.292zm10.881-6.354h.81l1.894-4.586H15.19l-1.154 3.008h-.013l-1.135-3.008h-1.154zm4.208 0h1.011V9.705h-1.011zm2.878 0h3.235v-.93h-2.223v-.933h1.99v-.934h-1.99v-.855h2.107v-.934h-3.112zM1.31 7.941h1.01V4.247h1.31v-.895H0v.895h1.31zm3.747 0h1.011V5.959h1.958v1.984h1.011v-4.59h-1.01v1.711H6.061V3.351H5.057zm5.348 0h3.242v-.933H11.41v-.934h1.99v-.933h-1.99v-.856h2.107v-.934h-3.112zM.162 14.296h1.005v-3.52h.013l1.167 3.52h.765l1.206-3.52h.013v3.52h1.011v-4.59H3.82L2.755 12.7h-.013L1.686 9.705H.156zm14.534 6.353h1.641a3.2 3.2 0 0 0 .98-.149 2.5 2.5 0 0 0 .824-.437 2.1 2.1 0 0 0 .567-.713 2.2 2.2 0 0 0 .223-.983 2.4 2.4 0 0 0-.218-1.07 1.96 1.96 0 0 0-.586-.716 2.4 2.4 0 0 0-.873-.392 4.4 4.4 0 0 0-1.046-.13h-1.519zm1.013-3.656h.596a2.3 2.3 0 0 1 .606.08 1.5 1.5 0 0 1 .503.244 1.2 1.2 0 0 1 .34.412 1.3 1.3 0 0 1 .13.587 1.55 1.55 0 0 1-.13.658 1.1 1.1 0 0 1-.347.433 1.4 1.4 0 0 1-.518.238 2.8 2.8 0 0 1-.649.07h-.538zm4.686 3.656h1.88a3 3 0 0 0 .613-.064 1.7 1.7 0 0 0 .554-.214 1.2 1.2 0 0 0 .402-.39 1.1 1.1 0 0 0 .155-.606 1.2 1.2 0 0 0-.071-.415 1 1 0 0 0-.204-.34 1.1 1.1 0 0 0-.317-.24 1.3 1.3 0 0 0-.413-.13v-.012a1.2 1.2 0 0 0 .575-.366.96.96 0 0 0 .216-.648 1.1 1.1 0 0 0-.149-.603 1 1 0 0 0-.389-.354 1.7 1.7 0 0 0-.54-.169 4.5 4.5 0 0 0-.6-.041h-1.712zm1.011-3.734h.687a1.4 1.4 0 0 1 .24.022.8.8 0 0 1 .22.075.43.43 0 0 1 .16.147.4.4 0 0 1 .061.236.5.5 0 0 1-.055.233.43.43 0 0 1-.146.156.6.6 0 0 1-.204.084 1 1 0 0 1-.23.026h-.745zm0 1.835h.765a2 2 0 0 1 .266.02 1 1 0 0 1 .26.07.5.5 0 0 1 .204.152.4.4 0 0 1 .08.26.5.5 0 0 1-.06.253.5.5 0 0 1-.16.168.6.6 0 0 1-.217.09 1 1 0 0 1-.237.027H21.4z")],
	wikidata: ["Wikidata", brand("M0 4.583v14.833h.865V4.583zm1.788 0v14.833h2.653V4.583zm3.518 0v14.832H7.96V4.583zm3.547 0v14.834h.866V4.583zm1.789 0v14.833h.865V4.583zm1.759 0v14.834h2.653V4.583zm3.518 0v14.834h.923V4.583zm1.788 0v14.833h2.653V4.583zm3.64 0v14.834h.865V4.583zm1.788 0v14.834H24V4.583Z")],
	rotten_tomatoes: ["Rotten Tomatoes", brand("M5.866 0 4.335 1.262l2.082 1.8c-2.629-.989-4.842 1.4-5.012 2.338 1.384-.323 2.24-.422 3.344-.335-7.042 4.634-4.978 13.148-1.434 16.094 5.784 4.612 13.77 3.202 17.91-1.316C27.26 13.363 22.993.65 10.86 2.766c.107-1.17.633-1.503 1.243-1.602-.89-1.493-3.67-.734-4.556 1.374C7.52 2.602 5.866 0 5.866 0M4.422 7.217H6.9c2.673 0 2.898.012 3.55.202 1.06.307 1.868.973 2.313 1.904q.074.158.13.305l7.623.008.027 2.912-2.745-.024v7.549l-2.982-.016v-7.522l-2.127.016a2.9 2.9 0 0 1-1.056 1.134c-.287.176-.3.19-.254.264.127.2 2.125 3.642 2.125 3.659l-3.39.019-2.013-3.376c-.034-.047-.122-.068-.344-.084l-.297-.02.037 3.48-3.075-.038zm3.016 2.288.024.338c.014.186.024.729.024 1.206v.867l.582-.025c.32-.013.695-.049.833-.078.694-.146 1.048-.478 1.087-1.018.027-.378-.063-.636-.303-.87-.318-.309-.761-.416-1.733-.418Z")],
	goodreads: ["Goodreads", brand("M17.346.026c.422-.083.859.037 1.179.325.346.284.55.705.557 1.153-.023.457-.247.88-.612 1.156l-2.182 1.748a.6.6 0 0 0-.255.43.52.52 0 0 0 .11.424 5.89 5.89 0 0 1 .832 6.58c-1.394 2.79-4.503 3.99-7.501 2.927a.8.8 0 0 0-.499-.01c-.224.07-.303.18-.453.383l-.014.02-.941 1.254s-.792.985.457.935c3.027-.119 3.817-.119 5.439-.01 2.641.18 3.806 1.903 3.806 3.275 0 1.623-1.036 3.383-3.809 3.383a118 118 0 0 0-5.517-.03c-.31.005-.597.013-.835.02-.228.006-.41.011-.52.011-.712 0-1.648-.186-1.66-1.068-.008-.729.624-1.12 1.11-1.172.43-.045.815.007 1.24.064.252.034.518.07.815.088.185.011.366.025.552.038.53.038 1.102.08 1.926.087.427.005.759.01 1.025.015.695.012.941.016 1.28-.015 1.248-.112 1.832-.61 1.832-1.376 0-.805-.584-1.264-1.698-1.414-1.564-.213-2.33-.163-3.72-.074a88 88 0 0 1-1.669.095c-.608.029-2.449.026-2.682-1.492-.053-.416-.073-1.116.807-2.325l.75-1.003c.36-.49.582-.898.053-1.559 0 0-.39-.468-.52-.638-1.215-1.587-1.512-4.08-.448-6.114 1.577-3.011 5.4-4.26 8.37-2.581.253.143.438.203.655.163.201-.032.27-.167.363-.344q.03-.06.067-.126c.004-.01.241-.465.535-1.028l.734-1.41a1.5 1.5 0 0 1 1.041-.785M9.193 13.243c1.854.903 3.912.208 5.254-2.47 1.352-2.699.827-5.11-1.041-6.023-2.488-1.213-4.596 1.081-5.389 2.66-1.355 2.698-.717 4.886 1.147 5.818Z")],
	openlibrary: ["Open Library", brand("M22.667 22.884V24H1.333v-1.116zm-.842-1.675v1.396H2.175v-1.396zM4.233 6.14l.234.118.118 1.882.117 3.058v2.941l-.117 3.666-.02 2.47-.332.098H3.062l-.352-.098-.136-2.47-.118-3.646v-2.941l.118-3.078.107-1.892.244-.107zm16.842 0 .235.118.117 1.882.117 3.058v2.941l-.117 3.666-.02 2.47-.332.098h-1.171l-.352-.098-.137-2.47-.117-3.646v-2.941l.117-3.078.108-1.892.244-.107zm-11.79 0 .235.118.117 1.882.117 3.058v2.941l-.117 3.666-.02 2.47-.331.098H8.114l-.352-.098-.136-2.47-.117-3.646v-2.941l.117-3.078.107-1.892.244-.107zm6.457 0 .234.118.117 1.882.118 3.058v2.941l-.118 3.666-.019 2.47-.332.098H14.57l-.351-.098-.137-2.47-.117-3.646v-2.941l.117-3.078.108-1.892.244-.107zm6.083-2.511V5.58H2.175V3.628zM11.798 0l10.307 2.347-.413.723H1.951l-.618-.587Z")],
	audible: ["Audible", brand("M12.008 17.362 24 9.885v2.028l-11.992 7.509L0 11.912V9.886l12.008 7.477zm0-9.378c-2.709 0-5.085 1.363-6.448 3.47.111-.111.175-.175.286-.254 3.374-2.804 8.237-2.17 10.883 1.362l1.758-1.124c-1.394-2.044-3.786-3.454-6.48-3.454m0 3.47a4.4 4.4 0 0 0-3.548 1.821 3.6 3.6 0 0 1 2.139-.697c1.299 0 2.455.666 3.232 1.79l1.679-1.045c-.729-1.157-2.028-1.87-3.501-1.87M3.897 8.412c4.943-3.897 11.929-2.836 15.652 2.344l.031.032 1.822-1.125a11.21 11.21 0 0 0-9.394-5.085c-3.897 0-7.366 1.996-9.394 5.085.364-.412.824-.903 1.283-1.251")],
	// the two flames of The Great Courses' own logo (thegreatcourses.com), without its words
	greatcourses: ["The Great Courses", '<svg viewBox="-3 0 36 36" aria-hidden="true"><path d="M9.28139 14.6428C4.6107 19.9162 5.30031 30.8066 12.7794 35.4997C7.00601 34.3289 0.0932512 32.7946 -2.94356e-05 26.4738C-0.0899786 20.3865 6.24977 16.7208 9.28139 14.6428Z"/><path d="M15.4945 0C15.7611 0.126749 30.4561 9.80969 23.2835 20.4332C16.9504 29.8093 15.3446 32.2476 16.5806 36C12.4896 34.3222 9.00487 28.4518 8.98155 22.8448C8.9449 14.346 18.8593 10.5068 15.4945 0Z"/></svg>'],
	simania: ["Simania", '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M4 2h16a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 2v16h16V4z"/><text x="12" y="17.5" text-anchor="middle" font-size="15" font-weight="700" font-family="sans-serif">\u05e1</text></svg>'],
};

// A card's pages on other sites, as icons in its corner (never a line of text): catalogs is
// [[field, site key of SITES, its page from the id (and the row)], ...]; every one is always
// there, one the row has no id of disabled in its place
export function cornerLinks(card, item, catalogs) {
	const corner = cornerOf(card);
	for (const [key, site, url] of catalogs) {
		const [name, icon] = SITES[site];
		corner.appendChild(linkButton(item[key] ? url(item[key], item) : "", `${name} page`, icon, "catalog-button"));
	}
}

// A link as an icon in a card's corner, opening in a new tab; disabled, in the same place, when there is no url
export function linkButton(url, label, icon, className) {
	let button;
	if (url) {
		button = el("a", `icon-button ${className}`);
		button.href = url;
		button.target = "_blank";
		button.rel = "noopener";
		button.title = `${label}: ${url}`;
	} else {
		button = el("button", `icon-button ${className}`);
		button.type = "button";
		button.disabled = true;
		button.title = `No ${label}: add it in the dialog`;
	}
	button.setAttribute("aria-label", button.title);
	button.innerHTML = icon;
	return button;
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
