// The library: the state of the page, a kind of work (books, films), its entries and their cards.

import { cardShell } from "./cards.js";
import { $, VISIT, api, showError } from "./core.js";
import { fillTypeFilter, pickedTypes, typeMatches } from "./filters.js";
import { navigate } from "./history.js";
import { openDialog } from "./locks.js";
import { localeName } from "./names.js";
import { pageOf, showSection } from "./paging.js";
import { readText } from "./readings.js";
import { rankBySearch, searchMatches } from "./search.js";
import { renderKinds, setCount } from "./sidebar.js";
import { currentSort, sortItems, updateTools } from "./sorting.js";
import { appendLinks, cornerLinks, detail, linksDetail } from "./worlds.js";

// view is a kind of work ("book", ...) or one of WORLDS ("concerts", ...)
// editing is the item open in the dialog, null when adding
// editingView: the view the open dialog belongs to, which its save and delete go to
export const state = { config: null, kind: "book", view: "concerts", entries: [], editing: null, editingView: null, layout: "cards" };

export function fillStatuses(select, selected) {
	select.replaceChildren();
	for (const [value, label] of Object.entries(state.config.statuses)) {
		const option = document.createElement("option");
		option.value = value;
		option.textContent = label;
		option.selected = value === selected;
		select.appendChild(option);
	}
}

// [field, label, url of the work on that catalog, id of the "open" link in the add form (films only)]
const CATALOGS = [
	["imdb_id", "IMDb", (id) => `https://www.imdb.com/title/${id}/`, "imdb-link"],
	["tmdb_id", "TMDB", (id) => `https://www.themoviedb.org/movie/${id}`, "tmdb-link"],
	["rotten_tomatoes_id", "RT", (id) => `https://www.rottentomatoes.com/${id}`, "rt-link"],
	["goodreads_id", "Goodreads", (id) => `https://www.goodreads.com/book/show/${id}`, null],
	["simania_id", "Simania", (id) => `https://simania.co.il/bookdetails.php?item_id=${id}`, null],
	["openlibrary_id", "Open Library", (id) => `https://openlibrary.org/works/${id}`, null],
];

// a book's pages in catalogs, as icons in its card's corner: [field, site (worlds.js), its page]
const BOOK_LINKS = [
	["openlibrary_id", "openlibrary", (id) => `https://openlibrary.org/works/${id}`],
	["goodreads_id", "goodreads", (id) => `https://www.goodreads.com/book/show/${id}`],
	["simania_id", "simania", (id) => `https://simania.co.il/bookdetails.php?item_id=${id}`],
];

// The read-only id fields of the add form: the values come from the search, never typed.
export function showMovieIds(values) {
	const form = $("add-form");
	for (const [key, , url, linkId] of CATALOGS.filter((catalog) => catalog[3])) {
		const value = values[key] ?? "";
		form.elements[key].value = value;
		const link = $(linkId);
		link.hidden = !value;
		link.href = value ? url(value) : "";
	}
}

// Make a card or row open its item in the dialog, by click or by Enter, except
// where the click lands on a link of its own.
export function editable(node, item) {
	// a view's visitor reads the cards: there is nothing to edit
	if (VISIT) {
		return;
	}
	node.classList.add("clickable");
	node.tabIndex = 0;
	node.title = "Click to edit";
	const open = () => openDialog(item).catch((e) => showError(e.message));
	node.onclick = (event) => {
		if (!event.target.closest("a, button")) {
			open();
		}
	};
	node.onkeydown = (event) => {
		if (event.key === "Enter" && event.target === node) {
			open();
		}
	};
}

// A library entry as a card, laid out like every other card view; its cover
// is the image, the catalog links (Goodreads, ...) are icons in its corner.
function libraryCard(entry) {
	const { creator } = state.config.kinds[state.kind];
	// the title and the authors' names in the language it was read in (the server picks them)
	// under the title: each author a link to them in People (a click opens the author, not the book), then the year
	let subtitle = [entry.creator, entry.year].filter(Boolean).join(", ");
	if (entry.authors.length) {
		subtitle = document.createDocumentFragment();
		appendLinks(subtitle, "people", entry.authors);
		if (entry.year) {
			subtitle.append(`, ${entry.year}`);
		}
	}
	const { card, list } = cardShell({ ...entry, name: entry.title }, subtitle, "cover");
	// an entry is known by its work: "book-12", opened by the link #book/12
	card.id = `${state.kind}-${entry.work_id}`;
	// the dialog edits the entry as it is
	editable(card, entry);
	// its pages in catalogs, in its corner
	cornerLinks(card, entry, BOOK_LINKS);
	// the authors as links to them in People; the plain text for an entry with none linked
	if (entry.authors.length) {
		linksDetail(list, creator, "people", entry.authors);
	} else {
		detail(list, creator, entry.creator);
	}
	// a year before the common era is negative: -375 is 375 BCE
	detail(list, "Year", entry.year === null ? "" : entry.year < 0 ? `${-entry.year} BCE` : String(entry.year));
	detail(list, "Original language", entry.original_locale ? localeName(entry.original_locale) : "");
	detail(list, "ISBN", entry.isbn);
	// every time it was read: the day and the language, as far as they are known
	detail(list, entry.reads.length > 1 ? "Readings" : "Reading", entry.reads.map(readText).join("; "));
	// its titles but the one shown, each with its language
	const others = [{ locale: entry.title_locale, title: entry.main_title }, ...entry.titles].filter((t) => t.title !== entry.title);
	detail(list, "Other titles", others.map((t) => `${t.title} (${localeName(t.locale)})`).join("; "));
	detail(list, "Status", state.config.statuses[entry.status] || entry.status);
	if (entry.rating !== null) {
		detail(list, "Rating", `${entry.rating}/${state.config.rating_max}`);
	}
	detail(list, "Started", entry.started_on ?? "");
	detail(list, "Owned in", (entry.owned || []).map(localeName).join(", "));
	detail(list, "Review", entry.review);
	detail(list, "Notes", entry.notes);
	return card;
}

export async function loadEntries() {
	const kind = state.kind;
	const entries = await api(`/api/library-entries?kind=${encodeURIComponent(kind)}`);
	// another view was opened while these loaded: they are not what is on screen
	if (state.view !== kind) {
		return;
	}
	state.entries = entries;
	// the statuses in the filter, with how many entries have each
	await fillTypeFilter(kind);
	if (state.view === kind) {
		renderEntries();
	}
}

// The library's cards: searched and sorted with the same toolbar as every other tab.
// What the list on screen is: a new view, search, sort, filter or layout starts again at the first page
export function listKey(view) {
	const sort = currentSort();
	return JSON.stringify([view, $("world-search").value, sort?.field[0], sort?.direction, [...pickedTypes(view)], state.layout]);
}

export function renderEntries() {
	const { plural } = state.config.kinds[state.kind];
	const shown = rankBySearch(sortItems(state.entries.filter((entry) => typeMatches(entry) && searchMatches(entry))));
	setCount(state.kind, state.entries.length);
	$("library-cards").replaceChildren(...pageOf(shown, listKey(state.kind)).map(libraryCard));
	$("library-cards").hidden = shown.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add one with the + button.`;
	showCount(shown.length, state.entries.length, plural.toLowerCase());
}

export function showCount(shown, total, what) {
	const n = (count) => count.toLocaleString();
	$("world-count").textContent = total === 0 ? "" : shown === total ? `${n(total)} ${what}` : `${n(shown)} of ${n(total)} ${what}`;
}

export async function selectKind(kind, hash = kind) {
	state.kind = kind;
	state.view = kind;
	// the last kind's entries are not this one's: the filter counts start at 0 until they load
	state.entries = [];
	navigate(hash);
	showSection("library-view");
	$("world-search").value = "";
	await fillTypeFilter(kind);
	updateTools();
	const { plural } = state.config.kinds[kind];
	document.title = `${plural} - My World`;
	renderKinds();
	showError("");
	await loadEntries();
}
