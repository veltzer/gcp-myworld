// Sorting a list, and the tools over it.

import { CARDS } from "./cards.js";
import { updateViewChecks } from "./checks.js";
import { $ } from "./core.js";
import { renderEntries, state } from "./library.js";
import { MAPPED } from "./map.js";
import { pagerOff, renderWorld } from "./paging.js";
import { WORLDS, canChange, sharedLockedWhy } from "./worlds.js";

// view -> the fields it can be sorted by: [key, label, value of an item, first direction].
// The first field is the default. A view with none still shows the (disabled) control.
const SORTS = {
	library: [
		["updated", "Recently changed", (e) => e.updated_at, "desc"],
		["title", "Title", (e) => e.title, "asc"],
		["creator", "Creator", (e) => e.creator, "asc"],
		["year", "Year", (e) => e.year, "desc"],
		["status", "Status", (e) => state.config.statuses[e.status] || e.status, "asc"],
		["rating", "Rating", (e) => e.rating, "desc"],
		["started", "Started", (e) => e.started_on, "desc"],
		["finished", "Finished", (e) => e.finished_on, "desc"],
	],
	concerts: [
		["date", "Date", (c) => c.date_sort, "desc"],
		["name", "Name", (c) => c.name, "asc"],
		["place", "Place", (c) => c.place?.name, "asc"],
		["city", "City", (c) => c.place?.city?.name, "asc"],
		["genre", "Genre", (c) => c.genre, "asc"],
		["tickets", "Tickets", (c) => c.tickets, "desc"],
	],
	museums: [
		["date", "Date", (m) => m.date_sort, "desc"],
		["name", "Name", (m) => m.name, "asc"],
		["city", "City", (m) => m.city?.name, "asc"],
		["rating", "Rating", (m) => m.rating, "desc"],
		["visits", "Visits", (m) => m.visits.length, "desc"],
	],
	"audio-courses": [
		["date", "Finished", (c) => c.date_sort, "desc"],
		["name", "Name", (c) => c.name, "asc"],
		["lecturer", "Lecturer", (c) => c.lecturers[0]?.name, "asc"],
		["rating", "Rating", (c) => c.rating, "desc"],
		["started", "Started", (c) => c.started, "desc"],
	],
	"audio-books": [
		// when finished, else when it came into the library
		["date", "Date", (b) => b.date_sort, "desc"],
		["name", "Title", (b) => b.name, "asc"],
		["author", "Author", (b) => b.authors, "asc"],
		["rating", "Rating", (b) => b.rating, "desc"],
		["heard", "Heard", (b) => (b.finished ? 100 : b.percent_heard), "desc"],
		["length", "Length", (b) => b.minutes, "desc"],
		["released", "Released", (b) => b.released, "desc"],
		["source_rating", "Rating there", (b) => b.source_rating, "desc"],
	],
	youtube: [
		["date", "Watched", (v) => v.date_sort, "desc"],
		["name", "Name", (v) => v.name, "asc"],
		["rating", "Rating", (v) => v.rating, "desc"],
		["channel", "Channel", (v) => v.channel, "asc"],
		["views", "Views", (v) => v.views, "desc"],
		["duration", "Length", (v) => v.duration, "desc"],
		["uploaded", "Uploaded", (v) => v.uploaded, "desc"],
	],
	chess: [
		["date", "Played", (g) => g.date, "desc"],
		["opponent", "Opponent", (g) => g.opponent, "asc"],
		["outcome", "Result", (g) => g.outcome, "desc"],
		["rating", "My rating", (g) => g.rating, "desc"],
		["opponent_rating", "Opponent's rating", (g) => g.opponent_rating, "desc"],
		["plies", "Moves", (g) => g.plies, "desc"],
		["opening", "Opening", (g) => g.opening, "asc"],
		["eco", "ECO", (g) => g.eco, "asc"],
		["time_control", "Time control", (g) => g.time_control, "asc"],
		["site", "Site", (g) => g.site, "asc"],
	],
	cities: [
		["name", "Name", (c) => c.name, "asc"],
		["country", "Country", (c) => c.country?.name, "asc"],
		["places", "Places", (c) => c.places.length, "desc"],
		["population", "Population", (c) => c.population, "desc"],
	],
	countries: [
		["name", "Name", (c) => c.name, "asc"],
		["code", "Code", (c) => c.code, "asc"],
		["cities", "Cities", (c) => c.cities.length, "desc"],
	],
	currencies: [
		["code", "Code", (c) => c.code, "asc"],
		["name", "Name", (c) => c.name, "asc"],
		["countries", "Countries", (c) => c.countries.length, "desc"],
	],
	groups: [
		["name", "Name", (g) => g.name, "asc"],
		["members", "Members", (g) => g.members.length, "desc"],
		["concerts", "Concerts", (g) => g.concerts.length, "desc"],
	],
	places: [
		["name", "Name", (p) => p.name, "asc"],
		["city", "City", (p) => p.city?.name, "asc"],
		["country", "Country", (p) => p.city?.country?.name, "asc"],
		["concerts", "Concerts", (p) => p.concerts.length, "desc"],
	],
	people: [
		["first_name", "First name", (p) => p.first_name, "asc"],
		["honorific", "Honorific", (p) => p.honorific, "asc"],
		["middle_name", "Middle name", (p) => p.middle_name, "asc"],
		["surname", "Surname", (p) => p.surname, "asc"],
		["type", "Profession", (p) => p.types[0]?.name, "asc"],
		["organization", "Organization", (p) => p.organizations[0]?.name, "asc"],
	],
	organizations: [
		["name", "Name", (o) => o.name, "asc"],
		["type", "Type", (o) => o.type?.name, "asc"],
		["people", "People", (o) => o.people.length, "desc"],
		["status", "Status", (o) => o.status, "asc"],
		["location", "Location", (o) => o.location, "asc"],
	],
	"organization-types": [
		["name", "Name", (t) => t.name, "asc"],
		["count", "Organizations", (t) => t.count, "desc"],
	],
	"person-types": [
		["name", "Name", (t) => t.name, "asc"],
		["count", "People", (t) => t.count, "desc"],
	],
	"relation-types": [
		["name", "Name", (t) => t.name, "asc"],
		["count", "Organizations", (t) => t.count, "desc"],
	],
	"person-relation-types": [
		["name", "Name", (t) => t.name, "asc"],
		["inverse", "Other way", (t) => t.inverse, "asc"],
		["count", "Relations", (t) => t.count, "desc"],
	],
	"person-organization-types": [
		["name", "Name", (t) => t.name, "asc"],
		["count", "Links", (t) => t.count, "desc"],
	],
	devices: [
		["name", "Name", (t) => t.name, "asc"],
		["count", "Used by", (t) => t.count, "desc"],
	],
	locales: [
		["order", "Order", (l) => l.id, "asc"],
		["name", "Name", (l) => l.name, "asc"],
		["code", "Code", (l) => l.code, "asc"],
		["script", "Script", (l) => l.script, "asc"],
		["count", "Used by", (l) => l.count, "desc"],
	],
};

const SORT_KEY = "myworld.sort";

// views that are a page of their own, outside the tabs: nothing to search, sort or add
const PAGES = new Set(["stats", "imports", "shared-views", "users", "checks", "schema"]);

function sortFields() {
	if (PAGES.has(state.view)) {
		return [];
	}
	return SORTS[state.view in WORLDS ? state.view : "library"] || [];
}

// the chosen field and direction of the view on screen, remembered in this browser
function savedSorts() {
	try {
		return JSON.parse(window.localStorage.getItem(SORT_KEY) || "{}");
	} catch (e) {
		return {};
	}
}

export function currentSort() {
	const fields = sortFields();
	const saved = savedSorts()[state.view];
	const field = fields.find(([key]) => key === saved?.key) || fields[0];
	return field ? { field, direction: saved?.key === field[0] ? saved.direction : field[3] } : null;
}

function saveSort(key, direction) {
	const sorts = savedSorts();
	sorts[state.view] = { key, direction };
	try {
		window.localStorage.setItem(SORT_KEY, JSON.stringify(sorts));
	} catch (e) {
		// private window or blocked storage: the choice lasts until reload
	}
}

const COLLATOR = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

// Sorted by the current field; an item without a value goes last either way.
export function sortItems(items) {
	const sort = currentSort();
	if (!sort) {
		return items;
	}
	const get = sort.field[2];
	const sign = sort.direction === "desc" ? -1 : 1;
	const empty = (v) => v === null || v === undefined || v === "";
	return [...items].sort((a, b) => {
		const x = get(a);
		const y = get(b);
		if (empty(x) || empty(y)) {
			return empty(x) - empty(y);
		}
		const order = typeof x === "number" && typeof y === "number" ? x - y : COLLATOR.compare(String(x), String(y));
		return sign * order;
	});
}

// Material arrow_upward / arrow_downward
const ARROWS = {
	asc: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z"/></svg>',
	desc: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12l-1.41-1.41L13 16.17V4h-2v12.17l-5.58-5.59L4 12l8 8 8-8z"/></svg>',
};

// The toolbar for the view on screen: every control is always there, disabled where it does not apply.
export function updateTools() {
	const select = $("sort-field");
	const fields = sortFields();
	const sort = currentSort();
	select.replaceChildren(...(fields.length ? fields : [["", "Sort"]]).map(([key, label]) => {
		const option = document.createElement("option");
		option.value = key;
		option.textContent = label;
		return option;
	}));
	select.disabled = fields.length === 0;
	select.value = sort ? sort.field[0] : "";
	const direction = sort ? sort.direction : "asc";
	const button = $("sort-direction");
	button.disabled = !sort;
	button.innerHTML = ARROWS[direction];
	button.title = direction === "asc" ? "Ascending: click for descending" : "Descending: click for ascending";
	button.setAttribute("aria-label", button.title);
	// the stats, imports, users and checks pages have nothing to search or add: both stay, disabled
	$("world-search").disabled = PAGES.has(state.view);
	// a shared page (places, cities, ...) is added to by admins only: the button stays, disabled for anyone else
	const shared = !canChange(state.view);
	$("fab").disabled = PAGES.has(state.view) || shared;
	$("fab").title = shared ? sharedLockedWhy() : "Add";
	const cards = state.view in CARDS || state.view in state.config.kinds;
	for (const layout of $("layouts").querySelectorAll("button")) {
		layout.disabled = !cards || (layout.dataset.layout === "map" && !MAPPED.has(state.view));
	}
	$("layouts").setAttribute("aria-disabled", String(!cards));
	if (PAGES.has(state.view)) {
		pagerOff();
	}
	updateViewChecks();
}

// After a change to the search, the filter or the sort: redraw what is on screen.
export function rerender() {
	if (PAGES.has(state.view)) {
		return;
	}
	if (state.view in WORLDS) {
		renderWorld();
	} else {
		renderEntries();
	}
}

export function setupSort() {
	$("sort-field").onchange = () => {
		const field = sortFields().find(([key]) => key === $("sort-field").value);
		saveSort(field[0], field[3]);
		updateTools();
		rerender();
	};
	$("sort-direction").onclick = () => {
		const sort = currentSort();
		saveSort(sort.field[0], sort.direction === "asc" ? "desc" : "asc");
		updateTools();
		rerender();
	};
}
