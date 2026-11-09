/* jshint esversion: 11, browser: true */
/* globals google */

"use strict";

// Browser side of My World: talks to the JSON API in src/myworld/views.py.

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
	const init = { method: options.method || "GET", headers: {} };
	if (options.body !== undefined) {
		init.headers["Content-Type"] = "application/json";
		init.body = JSON.stringify(options.body);
	}
	const response = await fetch(path, init);
	// a 401 from the library API means the session is gone; from a sign-in route it is the answer
	if (response.status === 401 && !path.startsWith("/auth/")) {
		window.location.href = "/";
		throw new Error("not signed in");
	}
	if (response.status === 204) {
		return null;
	}
	const data = await response.json();
	if (!response.ok) {
		throw new Error(data.error || response.statusText);
	}
	return data;
}

function showError(message) {
	const box = $("error");
	box.textContent = message;
	box.hidden = !message;
}

// The footer's provenance, in the spirit of veltzer.github.io: the year and
// the commit come from the deploy stamp, so the same deploy always says the same.
async function showBuild() {
	try {
		const info = await api("/app/version");
		const deployed = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(info.deploy_date || "") ? info.deploy_date : null;
		for (const year of document.querySelectorAll(".copyright-year")) {
			year.textContent = (deployed || new Date().toISOString()).slice(0, 4);
		}
		const build = $("build");
		const commit = (info.git_describe || "").match(/(?:-g)?([0-9a-f]{7,40})(?:-dirty)?$/);
		build.append("Built");
		if (commit) {
			const repo = el("a", null, "veltzer/gcp-myworld");
			repo.href = "https://github.com/veltzer/gcp-myworld";
			const link = el("a");
			link.href = `https://github.com/veltzer/gcp-myworld/commit/${commit[1]}`;
			link.appendChild(el("code", null, commit[1]));
			build.append(" from ", repo, " commit ", link);
		}
		if (deployed) {
			const time = el("time", null, `${deployed.slice(0, 16).replace("T", " ")} UTC`);
			time.dateTime = deployed;
			build.append(" on ", time);
		}
		build.append(info.revision && info.revision !== "local" ? `, serving as ${info.revision}` : " (local)");
	} catch (e) {
		// cosmetic only
	}
}

// ─── landing page ───────────────────────────────────────────────────────────

function loadGoogleSignIn(clientId) {
	const script = document.createElement("script");
	script.src = "https://accounts.google.com/gsi/client";
	script.async = true;
	script.onload = () => {
		google.accounts.id.initialize({
			client_id: clientId,
			ux_mode: "redirect",
			login_uri: `${window.location.origin}/auth/login`,
		});
		google.accounts.id.renderButton($("signin"), {
			type: "standard",
			size: "large",
			theme: "outline",
			text: "continue_with",
			shape: "pill",
			logo_alignment: "left",
			width: Math.min(360, $("signin").clientWidth || 360),
		});
		$("signin-loading").hidden = true;
	};
	script.onerror = () => {
		$("signin-loading").hidden = true;
		showError("Could not load Google sign-in. Check your connection and reload.");
	};
	document.head.appendChild(script);
}

function setupProviders(configured) {
	for (const link of document.querySelectorAll(".provider[data-provider]")) {
		if (configured[link.dataset.provider]) {
			continue;
		}
		link.classList.add("off");
		link.setAttribute("aria-disabled", "true");
		link.title = "Not configured on this server";
		link.onclick = (event) => event.preventDefault();
	}
}

function setupEmailForm(minLength) {
	const form = $("email-form");
	const password = form.elements.password;
	const submit = $("email-submit");
	let mode = "login";

	const applyMode = () => {
		const signup = mode === "register";
		submit.textContent = signup ? "Create account" : "Sign in";
		$("email-switch-text").textContent = signup ? "Already have an account?" : "New here?";
		$("email-mode").textContent = signup ? "Sign in" : "Create an account";
		password.autocomplete = signup ? "new-password" : "current-password";
		password.minLength = signup ? minLength : 0;
		showError("");
	};
	$("email-mode").onclick = () => {
		mode = mode === "login" ? "register" : "login";
		applyMode();
	};
	$("toggle-password").onclick = () => {
		const hidden = password.type === "password";
		password.type = hidden ? "text" : "password";
		$("toggle-password").textContent = hidden ? "Hide" : "Show";
	};
	form.onsubmit = async (event) => {
		event.preventDefault();
		showError("");
		const email = form.elements.email.value.trim();
		if (!email || !email.includes("@")) {
			showError("Enter your email address.");
			form.elements.email.focus();
			return;
		}
		if (mode === "register" && password.value.length < minLength) {
			showError(`Use at least ${minLength} characters for the password.`);
			password.focus();
			return;
		}
		submit.disabled = true;
		try {
			const result = await api(`/auth/email/${mode}`, { method: "POST", body: { email, password: password.value } });
			window.location.href = result.next;
		} catch (e) {
			showError(e.message);
			submit.disabled = false;
		}
	};
	applyMode();
}

async function indexPage() {
	const config = await api("/api/config");
	if (config.user) {
		window.location.href = "/library";
		return;
	}
	const error = new URLSearchParams(window.location.search).get("error");
	if (error) {
		showError(error);
		window.history.replaceState(null, "", "/");
	}
	if (config.google_client_id) {
		loadGoogleSignIn(config.google_client_id);
	} else {
		$("signin-loading").hidden = true;
		$("signin-missing").hidden = false;
	}
	setupProviders(config.providers);
	setupEmailForm(config.password_min_length);
	$("dev-login").hidden = !config.dev_login;
}

// ─── library page ───────────────────────────────────────────────────────────

// view is a kind of work ("book", ...) or one of WORLDS ("concerts", ...)
// editing is the item open in the dialog, null when adding
const state = { config: null, kind: "book", view: "concerts", entries: [], editing: null, layout: "cards" };

function fillStatuses(select, selected) {
	select.replaceChildren();
	for (const [value, label] of Object.entries(state.config.statuses)) {
		const option = document.createElement("option");
		option.value = value;
		option.textContent = label;
		option.selected = value === selected;
		select.appendChild(option);
	}
}

function cell(parent, className) {
	const td = document.createElement("td");
	if (className) {
		td.className = className;
	}
	parent.appendChild(td);
	return td;
}

// [field, label, url of the work on that catalog, id of the "open" link in the add form]
const CATALOGS = [
	["imdb_id", "IMDb", (id) => `https://www.imdb.com/title/${id}/`, "imdb-link"],
	["tmdb_id", "TMDB", (id) => `https://www.themoviedb.org/movie/${id}`, "tmdb-link"],
	["rotten_tomatoes_id", "RT", (id) => `https://www.rottentomatoes.com/${id}`, "rt-link"],
];

// The read-only id fields of the add form: the values come from the search, never typed.
function showMovieIds(values) {
	const form = $("add-form");
	for (const [key, , url, linkId] of CATALOGS) {
		const value = values[key] ?? "";
		form.elements[key].value = value;
		const link = $(linkId);
		link.hidden = !value;
		link.href = value ? url(value) : "";
	}
}

function catalogLinks(entry) {
	const links = CATALOGS.filter(([key]) => entry[key]);
	if (links.length === 0) {
		return null;
	}
	const span = document.createElement("span");
	span.className = "ids";
	for (const [key, label, url] of links) {
		const a = document.createElement("a");
		a.href = url(entry[key]);
		a.target = "_blank";
		a.rel = "noopener";
		a.textContent = label;
		a.title = `${label}: ${entry[key]}`;
		span.appendChild(a);
	}
	return span;
}

// ─── film search ────────────────────────────────────────────────────────────

const MOVIE_FIELDS = ["title", "creator", "year"];

// After a pick, the title, director, year and ids are what the catalog says; the
// user reads them rather than edits them, until they ask to enter the film by hand.
function lockMovieFields(locked) {
	const form = $("add-form");
	for (const name of MOVIE_FIELDS) {
		form.elements[name].readOnly = locked;
	}
	$("movie-locked").hidden = !locked;
}

function movieIdsReset() {
	showMovieIds({});
	lockMovieFields(false);
}

function renderMovieResult(movie, onPick) {
	const li = document.createElement("li");
	li.tabIndex = 0;
	if (movie.poster) {
		const img = document.createElement("img");
		img.src = movie.poster;
		img.alt = "";
		li.appendChild(img);
	} else {
		const box = document.createElement("span");
		box.className = "no-poster";
		li.appendChild(box);
	}
	const text = document.createElement("div");
	const title = document.createElement("div");
	title.className = "movie-title";
	title.textContent = movie.year ? `${movie.title} (${movie.year})` : movie.title;
	text.appendChild(title);
	if (movie.original_title && movie.original_title !== movie.title) {
		const meta = document.createElement("div");
		meta.className = "movie-meta";
		meta.textContent = movie.original_title;
		text.appendChild(meta);
	}
	if (movie.overview) {
		const overview = document.createElement("p");
		overview.className = "movie-overview";
		overview.textContent = movie.overview;
		text.appendChild(overview);
	}
	li.appendChild(text);
	const pick = document.createElement("button");
	pick.type = "button";
	pick.className = "pick";
	pick.textContent = "Use";
	li.appendChild(pick);
	const choose = () => onPick(movie);
	pick.onclick = choose;
	li.onkeydown = (event) => {
		if (event.key === "Enter" && event.target === li) {
			choose();
		}
	};
	return li;
}

async function pickMovie(movie) {
	const form = $("add-form");
	const hint = $("movie-hint");
	hint.hidden = false;
	hint.textContent = `Fetching details for ${movie.title}...`;
	try {
		const film = await api(`/api/movies/${movie.tmdb_id}`);
		form.elements.title.value = film.title;
		form.elements.creator.value = film.creator;
		form.elements.year.value = film.year ?? "";
		showMovieIds(film);
		lockMovieFields(true);
		$("movie-results").hidden = true;
		const extras = [];
		if (film.runtime) {
			extras.push(`${film.runtime} min`);
		}
		if (film.genres && film.genres.length) {
			extras.push(film.genres.join(", "));
		}
		hint.textContent = `Filled in from The Movie Database${extras.length ? ` (${extras.join(" · ")})` : ""}.`;
		form.elements.status.focus();
	} catch (e) {
		hint.textContent = e.message;
	}
}

async function findMovies() {
	const query = $("movie-query").value.trim();
	const results = $("movie-results");
	const hint = $("movie-hint");
	if (!query) {
		$("movie-query").focus();
		return;
	}
	hint.hidden = false;
	hint.textContent = "Searching...";
	results.hidden = true;
	try {
		const movies = await api(`/api/movies/search?q=${encodeURIComponent(query)}`);
		results.replaceChildren(...movies.map((m) => renderMovieResult(m, pickMovie)));
		results.hidden = movies.length === 0;
		hint.textContent = movies.length ? "Pick the right one:" : "Nothing found, try another spelling or the original title.";
	} catch (e) {
		hint.textContent = e.message;
	}
}

function setupMovieSearch() {
	const box = $("movie-search");
	if (!state.config.tmdb) {
		return;
	}
	$("movie-find").onclick = findMovies;
	$("movie-query").onkeydown = (event) => {
		if (event.key === "Enter") {
			event.preventDefault();
			findMovies();
		}
	};
	$("movie-unlock").onclick = () => {
		movieIdsReset();
		$("movie-hint").hidden = true;
		$("add-form").elements.title.focus();
	};
	box.hidden = state.kind !== "film";
}

// Make a card or row open its item in the dialog, by click or by Enter, except
// where the click lands on a link of its own.
function editable(node, item) {
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

function renderRow(entry) {
	const tr = document.createElement("tr");
	const title = cell(tr, "title");
	title.textContent = entry.title;
	const links = catalogLinks(entry);
	if (links) {
		title.appendChild(links);
	}
	cell(tr).textContent = entry.creator;
	cell(tr).textContent = entry.year ?? "";
	cell(tr).textContent = state.config.statuses[entry.status] || entry.status;
	cell(tr).textContent = entry.rating ?? "";
	cell(tr).textContent = entry.started_on ?? "";
	cell(tr).textContent = entry.finished_on ?? "";
	cell(tr).textContent = entry.notes;
	editable(tr, entry);
	return tr;
}

function renderKinds() {
	const nav = $("kinds");
	nav.replaceChildren();
	for (const [kind, { plural }] of Object.entries(state.config.kinds)) {
		const a = document.createElement("a");
		a.href = `/library#${kind}`;
		a.textContent = plural;
		a.dataset.kind = kind;
		a.onclick = (event) => {
			event.preventDefault();
			selectKind(kind);
		};
		nav.appendChild(a);
	}
	for (const [view, [, , , label]] of Object.entries(WORLDS)) {
		const a = document.createElement("a");
		a.href = `/library#${view}`;
		a.textContent = label;
		a.dataset.world = view;
		a.onclick = (event) => {
			event.preventDefault();
			selectWorld(view).catch((e) => showError(e.message));
		};
		nav.appendChild(a);
	}
	markActive();
}

async function loadEntries() {
	state.entries = await api(`/api/library?kind=${encodeURIComponent(state.kind)}`);
	renderEntries();
}

// The library table: searched and sorted with the same toolbar as every other tab.
function renderEntries() {
	const { plural } = state.config.kinds[state.kind];
	const shown = rankBySearch(sortItems(state.entries.filter(searchMatches)));
	$("rows").replaceChildren(...shown.map(renderRow));
	$("entries").hidden = shown.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add one with the + button.`;
	showCount(shown.length, state.entries.length, plural.toLowerCase());
}

function showCount(shown, total, what) {
	$("world-count").textContent = total === 0 ? "" : shown === total ? `${total} ${what}` : `${shown} of ${total} ${what}`;
}

function searchWords() {
	return $("world-search").value.toLowerCase().split(/\s+/).filter(Boolean);
}

// How well a row matches the search, best first: its name is the search,
// starts with it, has every word at the start of one of its words, has every
// word in it; then every word starts a word somewhere else in the row; then
// only inside other words ("mer" in "America"). Rows of the same rank keep the
// order picked with Sort.
function searchRank(item, words) {
	const name = String(item.name ?? item.title ?? "").toLowerCase();
	const query = words.join(" ");
	if (name === query) {
		return 0;
	}
	if (name.startsWith(query)) {
		return 1;
	}
	const wordStart = (text, word) => new RegExp(`(^|[^\\p{L}\\p{N}])${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "u").test(text);
	if (words.every((word) => wordStart(name, word))) {
		return 2;
	}
	if (words.every((word) => name.includes(word))) {
		return 3;
	}
	const text = haystack(item);
	return words.every((word) => wordStart(text, word)) ? 4 : 5;
}

function rankBySearch(items) {
	const words = searchWords();
	if (words.length === 0) {
		return items;
	}
	const ranks = new Map(items.map((item) => [item, searchRank(item, words)]));
	// a stable sort: within a rank, the Sort order stays
	return [...items].sort((a, b) => ranks.get(a) - ranks.get(b));
}

function searchMatches(item) {
	const words = $("world-search").value.toLowerCase().split(/\s+/).filter(Boolean);
	const text = haystack(item);
	return words.every((w) => text.includes(w));
}

// ─── sorting ────────────────────────────────────────────────────────────────

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
		["venue", "Venue", (c) => c.venue, "asc"],
		["city", "City", (c) => c.city, "asc"],
		["genre", "Genre", (c) => c.genre, "asc"],
		["tickets", "Tickets", (c) => c.tickets, "desc"],
	],
	museums: [
		["date", "Date", (m) => m.date_sort, "desc"],
		["name", "Name", (m) => m.name, "asc"],
		["city", "City", (m) => m.city, "asc"],
		["rating", "Rating", (m) => m.rating, "desc"],
		["tickets", "Tickets", (m) => m.tickets, "desc"],
	],
	"audio-courses": [
		["date", "Finished", (c) => c.date_sort, "desc"],
		["name", "Name", (c) => c.name, "asc"],
		["lecturer", "Lecturer", (c) => c.lecturers[0]?.name, "asc"],
		["rating", "Rating", (c) => c.rating, "desc"],
		["started", "Started", (c) => c.started, "desc"],
	],
	people: [
		["first_name", "First name", (p) => p.first_name, "asc"],
		["surname", "Surname", (p) => p.surname, "asc"],
		["type", "Type", (p) => p.types[0]?.name, "asc"],
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
	devices: [
		["name", "Name", (t) => t.name, "asc"],
		["count", "Audio courses", (t) => t.count, "desc"],
	],
};
const SORT_KEY = "myworld.sort";

// views that are a page of their own, outside the tabs: nothing to search, sort or add
const PAGES = new Set(["stats", "users", "checks"]);

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

function currentSort() {
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
function sortItems(items) {
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
function updateTools() {
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
	// the stats, users and checks pages have nothing to search or add: both stay, disabled
	$("world-search").disabled = PAGES.has(state.view);
	$("fab").disabled = PAGES.has(state.view);
	const cards = state.view in CARDS;
	for (const layout of $("layouts").querySelectorAll("button")) {
		layout.disabled = !cards || (layout.dataset.layout === "map" && !MAPPED.has(state.view));
	}
	$("layouts").setAttribute("aria-disabled", String(!cards));
}

// After a change to the search, the filter or the sort: redraw what is on screen.
function rerender() {
	if (PAGES.has(state.view)) {
		return;
	}
	if (state.view in WORLDS) {
		renderWorld();
	} else {
		renderEntries();
	}
}

function setupSort() {
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

async function selectKind(kind) {
	state.kind = kind;
	state.view = kind;
	navigate(kind);
	showSection("library-view");
	$("world-search").value = "";
	await fillTypeFilter(kind);
	updateTools();
	const { plural, creator } = state.config.kinds[kind];
	document.title = `${plural} - My World`;
	$("creator-label").textContent = creator;
	$("creator-column").textContent = creator;
	renderKinds();
	showError("");
	await loadEntries();
}

// how each sign-in method is named, and what its own id for the user is called
const PROVIDERS = {
	google: ["Google", "Google ID"],
	github: ["GitHub", "GitHub user ID"],
	email: ["Email and password", "Email"],
	dev: ["Development login", "Email"],
};

// The menu under the avatar and name: how the user signed in and as whom.
function setupAccountMenu(user) {
	const [method, idLabel] = PROVIDERS[user.provider] || [user.provider, "ID"];
	const rows = [
		["Signed in with", method],
		[idLabel, user.provider_id],
		["Email", user.email],
		["Account", `#${user.id}`],
		["Role", user.role === "admin" ? "Admin" : "User"],
	];
	// an email account's id is its email: said once
	const seen = new Set();
	$("account-details").replaceChildren(...rows.filter(([label, value]) => {
		const key = `${label}=${value}`;
		const repeat = seen.has(key);
		seen.add(key);
		return value && !repeat;
	}).flatMap(([label, value]) => [el("dt", null, label), el("dd", null, value)]));
	const button = $("account-button");
	const menu = $("account-menu");
	const show = (open) => {
		menu.hidden = !open;
		button.setAttribute("aria-expanded", String(open));
	};
	button.onclick = () => show(menu.hidden);
	document.addEventListener("click", (event) => {
		if (!menu.hidden && !event.target.closest(".account")) {
			show(false);
		}
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && !menu.hidden) {
			show(false);
			button.focus();
		}
	});
}

async function libraryPage() {
	state.config = await api("/api/config");
	if (!state.config.user) {
		window.location.href = "/";
		return;
	}
	const { user, rating_min, rating_max } = state.config;
	$("who").textContent = user.name || user.email;
	if (user.picture) {
		$("avatar").src = user.picture;
	}
	setupAccountMenu(user);
	$("logout").onclick = async () => {
		await fetch("/auth/logout", { method: "POST" });
		window.location.href = "/";
	};

	const form = $("add-form");
	fillStatuses(form.elements.status, "done");
	form.elements.rating.min = rating_min;
	form.elements.rating.max = rating_max;
	form.elements.finished_on.value = new Date().toISOString().slice(0, 10);
	form.onsubmit = async (event) => {
		event.preventDefault();
		dialogError("");
		const body = { kind: state.kind };
		for (const el of form.elements) {
			if (el.name) {
				body[el.name] = el.value;
			}
		}
		try {
			if (state.editing) {
				await api(`/api/library/${state.editing.work_id}`, { method: "PUT", body });
			} else {
				await api("/api/library", { method: "POST", body });
			}
			$("add-dialog").close();
			await loadEntries();
		} catch (e) {
			dialogError(e.message);
		}
	};

	setupMovieSearch();
	setupWorlds();
	setupAddDialog();
	renderKinds();
	startHistory();
	setupFreshness();
	await openHash();
}

// Open what the address bar says, without adding a history entry.
async function openHash() {
	nav.replacing = true;
	try {
		await route(window.location.hash.slice(1));
	} finally {
		nav.replacing = false;
	}
}

// Open what an address-bar hash names: a tab, a page, or one row of a view.
async function route(requested) {
	const linked = requested.match(/^(concerts|museums|audio-courses|people|organizations|organization-types|person-types|relation-types|devices)\/(\d+)$/);
	if (linked) {
		await showRow(linked[1], Number(linked[2]));
	} else if (requested === "stats") {
		await selectStats();
	} else if (requested === "users" && isAdmin()) {
		await selectUsers();
	} else if (requested === "checks" && isAdmin()) {
		await selectChecks();
	} else if (requested in state.config.kinds) {
		await selectKind(requested);
	} else {
		await selectWorld(requested in WORLDS ? requested : "concerts");
	}
}

// ─── history: Back and Forward inside the page ─────────────────────────────

// The app is one page: each view, and each row a link opened, is a history
// entry with its own #hash, so the browser's Back and Forward and the two
// arrows in the toolbar walk through them. The entries are numbered (in
// history.state) to know when there is nothing further back or forward.
const NAV_TOP_KEY = "myworld.nav-top";
// replacing: while the page opens what the address bar already says (at start,
// on Back or Forward), a view that fills in its own hash ("" -> "#concerts")
// corrects the entry it is on rather than adding one
const nav = { index: 0, top: 0, replacing: false };

function navigate(hash) {
	if (window.location.hash === `#${hash}`) {
		return;
	}
	if (nav.replacing) {
		window.history.replaceState({ nav: nav.index }, "", `#${hash}`);
		return;
	}
	nav.index += 1;
	nav.top = nav.index;
	saveNavTop();
	window.history.pushState({ nav: nav.index }, "", `#${hash}`);
	updateNavButtons();
}

function saveNavTop() {
	try {
		window.sessionStorage.setItem(NAV_TOP_KEY, String(nav.top));
	} catch (e) {
		// blocked storage: after a reload Forward may stay disabled; Back still works
	}
}

// Back to this tab after a while: the data may have changed meanwhile.
function setupFreshness() {
	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState === "visible" && state.view in WORLDS) {
			reloadWorld(state.view).catch((e) => showError(e.message));
		}
	});
}

function startHistory() {
	const known = window.history.state && Number.isInteger(window.history.state.nav);
	nav.index = known ? window.history.state.nav : 0;
	let top = 0;
	try {
		top = Number(window.sessionStorage.getItem(NAV_TOP_KEY)) || 0;
	} catch (e) {
		top = 0;
	}
	nav.top = Math.max(top, nav.index);
	if (!known) {
		window.history.replaceState({ nav: nav.index }, "", window.location.href);
	}
	window.addEventListener("popstate", (event) => {
		nav.index = event.state && Number.isInteger(event.state.nav) ? event.state.nav : 0;
		updateNavButtons();
		openHash().catch((e) => showError(e.message));
	});
	$("nav-back").onclick = () => window.history.back();
	$("nav-forward").onclick = () => window.history.forward();
	updateNavButtons();
}

function updateNavButtons() {
	$("nav-back").disabled = nav.index <= 0;
	$("nav-forward").disabled = nav.index >= nav.top;
}

// ─── concerts, museums, people, organizations ──────────────────────────────

// view -> [page title, API path, singular, tab label]; the rows are the signed-in user's own
const WORLDS = {
	concerts: ["My Concerts", "/api/concerts", "concert", "Concerts"],
	museums: ["My Museums", "/api/museums", "museum", "Museums"],
	"audio-courses": ["Audio courses", "/api/audio-courses", "audio course", "Audio courses"],
	people: ["People", "/api/people", "person", "People"],
	organizations: ["Organizations", "/api/organizations", "organization", "Organizations"],
	"organization-types": ["Organization types", "/api/organization-types", "organization type", "Org types"],
	"person-types": ["Person types", "/api/person-types", "person type", "Person types"],
	"relation-types": ["Relation types", "/api/relation-types", "relation type", "Relations"],
	devices: ["Devices", "/api/devices", "device", "Devices"],
};

// views whose rows have a type -> the view of their enumeration
const TYPED = { people: "person-types", organizations: "organization-types" };

// the id of the form, row or card of a view: "organization type" -> "organization-type"
function slug(view) {
	return WORLDS[view][2].replace(/ /g, "-");
}

const worldCache = {};

function el(tag, className, text) {
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
function formatDate(item) {
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

function detail(list, label, value) {
	if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) {
		return;
	}
	const li = el("li");
	li.append(el("span", "label", label), Array.isArray(value) ? value.join(", ") : String(value));
	list.appendChild(li);
}

// Names as links to their place in the People or Organizations view, appended to parent.
function appendLinks(parent, view, rows) {
	rows.forEach((row, index) => {
		if (index > 0) {
			parent.append(", ");
		}
		const a = el("a", "person-link", row.name);
		a.href = `/library#${view}/${row.id}`;
		a.onclick = (event) => {
			event.preventDefault();
			showRow(view, row.id).catch((e) => showError(e.message));
		};
		parent.appendChild(a);
	});
}

function linksDetail(list, label, view, rows) {
	if (rows.length === 0) {
		return;
	}
	const li = el("li");
	li.appendChild(el("span", "label", label));
	appendLinks(li, view, rows);
	list.appendChild(li);
}

function websiteDetail(list, url) {
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
		$("cards").classList.toggle(`layout-${name}`, name === layout);
	}
	for (const button of $("layouts").querySelectorAll("button")) {
		button.setAttribute("aria-pressed", String(button.dataset.layout === layout));
	}
}

function setupLayouts() {
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

// kind is "photo" or "logo" (a logo is always shown whole, never cropped)
// ─── the map layout ─────────────────────────────────────────────────────────

// The views whose items have a latitude and longitude; on the others the Map button is disabled.
const MAPPED = new Set(["museums", "organizations"]);
// Leaflet, from cdnjs, loaded the first time a map is shown
const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";
const LEAFLET_JS = ["leaflet.js", "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"];
const LEAFLET_CSS = ["leaflet.css", "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"];
let leafletLoading = null;
let worldMap = null;
let mapMarkers = null;

function showsMap() {
	return state.layout === "map" && MAPPED.has(state.view);
}

function loadLeaflet() {
	if (!leafletLoading) {
		leafletLoading = new Promise((resolve, reject) => {
			const css = document.createElement("link");
			css.rel = "stylesheet";
			css.href = LEAFLET + LEAFLET_CSS[0];
			css.integrity = LEAFLET_CSS[1];
			css.crossOrigin = "anonymous";
			document.head.appendChild(css);
			const script = document.createElement("script");
			script.src = LEAFLET + LEAFLET_JS[0];
			script.integrity = LEAFLET_JS[1];
			script.crossOrigin = "anonymous";
			script.onload = () => resolve(window.L);
			script.onerror = () => {
				leafletLoading = null;
				reject(new Error("The map library could not be loaded"));
			};
			document.head.appendChild(script);
		});
	}
	return leafletLoading;
}

// One marker per place: two visits of the same museum share a pin, and its popup lists both.
async function renderMap(items) {
	const L = await loadLeaflet();
	if (!showsMap()) {
		return;
	}
	if (!worldMap) {
		worldMap = L.map("world-map", { worldCopyJump: true });
		L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
			maxZoom: 19,
			attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
		}).addTo(worldMap);
		mapMarkers = L.layerGroup().addTo(worldMap);
	}
	// the box was hidden while the map was made or last drawn: let Leaflet measure it again
	worldMap.invalidateSize();
	mapMarkers.clearLayers();
	const places = new Map();
	for (const item of items) {
		if (item.latitude === null || item.longitude === null) {
			continue;
		}
		const key = `${item.latitude},${item.longitude}`;
		if (!places.has(key)) {
			places.set(key, []);
		}
		places.get(key).push(item);
	}
	const points = [];
	for (const group of places.values()) {
		const point = [group[0].latitude, group[0].longitude];
		points.push(point);
		const marker = L.circleMarker(point, { radius: 8, weight: 2, color: "#1d4ed8", fillColor: "#3b82f6", fillOpacity: 0.85 });
		marker.bindTooltip(group[0].name);
		marker.bindPopup(() => mapPopup(group));
		mapMarkers.addLayer(marker);
	}
	if (points.length > 0) {
		worldMap.fitBounds(points, { padding: [32, 32], maxZoom: 15 });
	} else {
		worldMap.setView([20, 0], 2);
	}
	const unplaced = items.filter((item) => item.latitude === null || item.longitude === null).length;
	if (unplaced > 0) {
		$("world-count").textContent += ` (${unplaced} with no location, not on the map)`;
	}
}

// Material "place"
const PIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>';

// The pin on a museum or organization card: opens a map of that one place.
// Without coordinates it is there, disabled.
function placeButton(item) {
	const button = el("button", "icon-button place-button");
	button.type = "button";
	button.innerHTML = PIN;
	const placed = item.latitude !== null && item.longitude !== null;
	button.disabled = !placed;
	button.title = placed ? `${item.name} on the map` : "No location: add an address and its latitude and longitude";
	button.setAttribute("aria-label", button.title);
	button.onclick = () => openPlace(item).catch((e) => showError(e.message));
	return button;
}

let placeMap = null;
let placeMarker = null;

async function openPlace(item) {
	const L = await loadLeaflet();
	const point = [item.latitude, item.longitude];
	$("place-title").textContent = item.name;
	$("place-address").textContent = item.address || item.location || item.city || "";
	$("place-osm").href = `https://www.openstreetmap.org/?mlat=${item.latitude}&mlon=${item.longitude}#map=17/${item.latitude}/${item.longitude}`;
	$("place-dialog").showModal();
	if (!placeMap) {
		placeMap = L.map("place-map");
		L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
			maxZoom: 19,
			attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
		}).addTo(placeMap);
		$("place-close").onclick = () => $("place-dialog").close();
	}
	// the box was not laid out until the dialog opened: let Leaflet measure it
	placeMap.invalidateSize();
	placeMap.setView(point, 16);
	if (placeMarker) {
		placeMarker.remove();
	}
	placeMarker = L.circleMarker(point, { radius: 10, weight: 3, color: "#1d4ed8", fillColor: "#3b82f6", fillOpacity: 0.85 }).addTo(placeMap);
	placeMarker.bindTooltip(item.name, { permanent: true, direction: "top", offset: [0, -10] });
}

function mapPopup(group) {
	const box = el("div", "map-popup");
	const first = group[0];
	box.appendChild(el("strong", null, first.name));
	const where = first.address || first.city || first.location;
	if (where) {
		box.appendChild(el("p", null, where));
	}
	for (const item of group) {
		const open = el("button", "text", group.length > 1 ? `Edit: ${formatDate(item) || item.name}` : "Edit");
		open.type = "button";
		open.onclick = () => openDialog(item).catch((e) => showError(e.message));
		box.appendChild(open);
	}
	return box;
}

function cardShell(item, subtitle, kind = "photo") {
	const card = el("article", "world-card");
	card.id = `${slug(state.view)}-${item.id}`;
	card.title = item.name;
	if (item.image) {
		card.classList.add("has-image", `is-${kind}`);
		const img = el("img", "world-image");
		img.src = item.image;
		img.alt = "";
		img.loading = "lazy";
		card.appendChild(img);
	} else {
		// an empty slot where the image would be: the list layout keeps every row the same shape
		card.appendChild(el("div", "world-image no-image"));
	}
	const body = el("div", "world-body");
	body.appendChild(el("h2", "world-title", item.name));
	if (subtitle) {
		body.appendChild(el("p", "world-subtitle", subtitle));
	}
	const list = el("ul", "world-details");
	body.appendChild(list);
	card.appendChild(body);
	editable(card, item);
	return { card, body, list };
}

function concertCard(item) {
	const { body, card, list } = cardShell(item, item.event);
	detail(list, "Date", formatDate(item));
	detail(list, "Where", [item.venue, item.city, item.country].filter(Boolean).join(", "));
	// a show named after its one performer does not repeat the name
	const performers = item.performers.length === 1 && item.performers[0].name === item.name ? [] : item.performers;
	linksDetail(list, "Performers", "people", performers);
	detail(list, "Genre", item.genre);
	linksDetail(list, "With", "people", item.people);
	detail(list, "Tickets", item.tickets);
	if (item.broadcast) {
		detail(list, "Seen", "on TV");
	}
	detail(list, "Review", item.review);
	detail(list, "Remark", item.remark);
	if (item.image && item.image_source) {
		const credit = el("p", "credit");
		const a = el("a", null, "Photo");
		a.href = item.image_source;
		a.target = "_blank";
		a.rel = "noopener";
		const who = [item.image_author, item.image_license].filter(Boolean).join(", ");
		credit.append(a, who ? `: ${who}` : "");
		body.appendChild(credit);
	}
	return card;
}

function museumCard(item) {
	const { card, list } = cardShell(item, item.city);
	card.appendChild(placeButton(item));
	detail(list, "Date", formatDate(item));
	detail(list, "Address", item.address);
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	if (item.alone) {
		detail(list, "With", "alone");
	}
	linksDetail(list, "With", "people", item.people);
	detail(list, "Tickets", item.tickets);
	detail(list, "Review", item.review);
	detail(list, "Remark", item.remark);
	websiteDetail(list, item.url);
	return card;
}

function organizationCard(item) {
	const { card, list } = cardShell(item, item.location, "logo");
	card.appendChild(placeButton(item));
	linksDetail(list, "Type", "organization-types", item.type ? [item.type] : []);
	// how it is related to me: links to the Relation types page
	linksDetail(list, "Relation", "relation-types", item.relations);
	detail(list, "Status", item.status);
	detail(list, "What happened", item.what_happened);
	detail(list, "Address", item.address);
	// how many people are at it, always shown (0 too), then who they are
	detail(list, "People", String(item.people.length));
	linksDetail(list, "Who", "people", item.people);
	detail(list, "Remark", item.remark);
	websiteDetail(list, item.website);
	return card;
}

function audioCourseCard(item) {
	const { card, list } = cardShell(item, item.lecturers.map((p) => p.name).join(", "));
	linksDetail(list, "Lecturer", "people", item.lecturers);
	if (item.status === "in_progress") {
		detail(list, "Status", ["In progress", item.progress].filter(Boolean).join(", "));
		detail(list, "Started", item.started.slice(0, 10));
	} else {
		detail(list, "Finished", formatDate(item));
	}
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
	detail(list, "Where", item.listened_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	websiteDetail(list, item.url);
	return card;
}

const CARDS = { concerts: concertCard, museums: museumCard, "audio-courses": audioCourseCard, organizations: organizationCard };

// Material "link"
const LINK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>';

// Everything that ties a person to the user, grouped, each entry a link to its card.
async function showConnections(person) {
	const [concerts, museums, courses] = await Promise.all([worldList("concerts"), worldList("museums"), worldList("audio-courses")]);
	const has = (list) => list.some((p) => p.id === person.id);
	const groups = [
		["Concerts you went to together", "concerts", concerts.filter((c) => has(c.people))],
		["Concerts they performed at", "concerts", concerts.filter((c) => has(c.performers))],
		["Museums you visited together", "museums", museums.filter((m) => has(m.people))],
		["Audio courses they taught", "audio-courses", courses.filter((c) => has(c.lecturers))],
		["Organizations", "organizations", person.organizations],
	].filter(([, , items]) => items.length > 0);
	$("connections-title").textContent = person.name;
	const body = $("connections-body");
	body.replaceChildren();
	if (groups.length === 0) {
		body.appendChild(el("p", "empty", "No concerts, museums, courses or organizations link you yet."));
	}
	for (const [label, view, items] of groups) {
		body.appendChild(el("h3", null, `${label} (${items.length})`));
		const ul = el("ul");
		for (const item of items) {
			const li = el("li");
			const when = formatDate(item);
			if (when) {
				li.appendChild(el("span", "when", when));
			}
			const a = el("a", "person-link", item.name);
			a.href = `/library#${view}/${item.id}`;
			a.onclick = (event) => {
				event.preventDefault();
				$("connections-dialog").close();
				showRow(view, item.id).catch((e) => showError(e.message));
			};
			li.appendChild(a);
			ul.appendChild(li);
		}
		body.appendChild(ul);
	}
	$("connections-dialog").showModal();
}

function personRow(person) {
	const tr = el("tr");
	tr.id = `person-${person.id}`;
	const kind = el("td");
	appendLinks(kind, "person-types", person.types);
	const organizations = el("td");
	appendLinks(organizations, "organizations", person.organizations);
	const links = el("td", "actions");
	const button = el("button", "icon-button");
	button.type = "button";
	button.title = `How you are connected to ${person.name}`;
	button.setAttribute("aria-label", button.title);
	button.innerHTML = LINK_ICON;
	button.onclick = () => showConnections(person).catch((e) => showError(e.message));
	links.appendChild(button);
	tr.append(el("td", "title", person.first_name), el("td", "title", person.surname), kind, organizations, el("td", null, person.description), links);
	editable(tr, person);
	return tr;
}

// A row of an enumeration (Org types, Person types, Relation types), with how many rows are of it.
function typeRow(kind) {
	const tr = el("tr");
	tr.id = `${slug(state.view)}-${kind.id}`;
	tr.append(el("td", "title", kind.name), el("td", null, kind.description), el("td", "number", kind.count));
	editable(tr, kind);
	return tr;
}

// views shown as a table rather than cards: view -> [table id, tbody id, row maker]
const TABLES = {
	people: ["people", "people-rows", personRow],
	"organization-types": ["types", "type-rows", typeRow],
	"person-types": ["person-types-table", "person-type-rows", typeRow],
	"relation-types": ["relation-types-table", "relation-type-rows", typeRow],
	devices: ["devices-table", "device-rows", typeRow],
};

// The type filter next to the search, for views whose rows have a type: a set
// of the picked values ("none" for the rows without a type, else type ids),
// empty for everything. A row matches when it has any picked type. Kept per view.
const typeFilters = {};

function pickedTypes(view) {
	if (!typeFilters[view]) {
		typeFilters[view] = new Set();
	}
	return typeFilters[view];
}

// The button names what is picked: "All types", the names, or how many.
function typeFilterLabel(view, types) {
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return "All types";
	}
	const names = [...picked].map((value) => (value === "none" ? "No type" : types.find((t) => String(t.id) === value)?.name)).filter(Boolean);
	return names.length <= 2 ? names.join(", ") : `${names.length} types`;
}

async function fillTypeFilter(view) {
	const button = $("type-filter");
	const menu = $("type-filter-menu");
	const typesView = TYPED[view];
	menu.hidden = true;
	button.setAttribute("aria-expanded", "false");
	// a view without types keeps the control, disabled
	button.disabled = !typesView;
	if (!typesView) {
		button.textContent = "All types";
		menu.replaceChildren();
		return;
	}
	const types = await worldList(typesView);
	const picked = pickedTypes(view);
	const box = (value, label) => {
		const line = el("label", "type-filter-option");
		const input = document.createElement("input");
		input.type = "checkbox";
		input.value = value;
		input.checked = picked.has(value);
		input.onchange = () => {
			if (input.checked) {
				picked.add(value);
			} else {
				picked.delete(value);
			}
			button.textContent = typeFilterLabel(view, types);
			rerender();
		};
		line.append(input, ` ${label}`);
		return line;
	};
	const clear = el("button", "text", "Show all");
	clear.type = "button";
	clear.onclick = () => {
		picked.clear();
		for (const input of menu.querySelectorAll("input")) {
			input.checked = false;
		}
		button.textContent = typeFilterLabel(view, types);
		rerender();
	};
	menu.replaceChildren(
		...types.map((t) => box(String(t.id), `${t.name} (${t.count})`)),
		box("none", "No type"),
		clear,
	);
	button.textContent = typeFilterLabel(view, types);
}

function typeMatches(item) {
	const picked = pickedTypes(state.view);
	if (!TYPED[state.view] || picked.size === 0) {
		return true;
	}
	// a person has a list of types, an organization one
	const types = item.types || (item.type ? [item.type] : []);
	return types.length === 0 ? picked.has("none") : types.some((t) => picked.has(String(t.id)));
}

// Everything a search can match on, as one lowercase string.
function haystack(item) {
	const values = [];
	for (const value of Object.values(item)) {
		if (typeof value === "string") {
			values.push(value);
		} else if (Array.isArray(value)) {
			values.push(...value.map((v) => (typeof v === "string" ? v : v.name)));
		} else if (value && typeof value === "object" && typeof value.name === "string") {
			values.push(value.name);
		}
	}
	values.push(formatDate(item));
	return values.join(" ").toLowerCase();
}

function renderWorld() {
	const view = state.view;
	const items = worldCache[view] || [];
	const shown = rankBySearch(sortItems(items.filter((item) => typeMatches(item) && searchMatches(item))));
	const table = TABLES[view];
	const map = !table && showsMap();
	$("cards").hidden = Boolean(table) || map;
	$("cards").replaceChildren(...(table || map ? [] : shown.map(CARDS[view])));
	$("world-map").hidden = !map;
	for (const [name, [tableId, rowsId, row]] of Object.entries(TABLES)) {
		$(tableId).hidden = name !== view || shown.length === 0;
		$(rowsId).replaceChildren(...(name === view ? shown.map(row) : []));
	}
	const what = WORLDS[view][0].replace(/^My /, "").toLowerCase();
	if (items.length === 0) {
		$("world-count").textContent = `Nothing here yet: no ${what} for this account.`;
	} else {
		showCount(shown.length, items.length, what);
	}
	if (map) {
		renderMap(shown).catch((e) => showError(e.message));
	}
}

function markActive() {
	for (const a of document.querySelectorAll(".kinds a")) {
		const active = a.dataset.world ? a.dataset.world === state.view : a.dataset.kind === state.view;
		a.classList.toggle("active", active);
	}
	$("stats-link").classList.toggle("active", state.view === "stats");
	$("users-link").classList.toggle("active", state.view === "users");
	$("checks-link").classList.toggle("active", state.view === "checks");
}

// One of the page bodies: the library table, the cards and tables, the stats, the users, the checks.
function showSection(id) {
	for (const section of ["library-view", "world-view", "stats-view", "users-view", "checks-view"]) {
		$(section).hidden = section !== id;
	}
}

// ─── stats ──────────────────────────────────────────────────────────────────

async function selectStats() {
	state.view = "stats";
	navigate("stats");
	document.title = "Stats - My World";
	showSection("stats-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("stats");
	updateTools();
	$("world-count").textContent = "";
	const stats = await api("/api/stats");
	if (state.view === "stats") {
		renderStats(stats);
	}
}

// ─── users (admins only) ────────────────────────────────────────────────────

function isAdmin() {
	return state.config.user.role === "admin";
}

async function selectUsers() {
	state.view = "users";
	navigate("users");
	document.title = "Users - My World";
	showSection("users-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("users");
	updateTools();
	const users = await api("/api/users");
	if (state.view === "users") {
		renderUsers(users);
	}
}

// Every account; an admin gives or takes the admin role with the select, and
// the server refuses to demote the last admin.
function renderUsers(users) {
	const admins = users.filter((u) => u.role === "admin").length;
	$("world-count").textContent = `${users.length} account${users.length === 1 ? "" : "s"}, ${admins} admin${admins === 1 ? "" : "s"}`;
	$("users-rows").replaceChildren(...users.map((user) => {
		const tr = el("tr");
		const role = el("select");
		role.setAttribute("aria-label", `Role of ${user.email}`);
		for (const value of ["user", "admin"]) {
			const option = el("option", null, value === "admin" ? "Admin" : "User");
			option.value = value;
			role.appendChild(option);
		}
		role.value = user.role;
		role.onchange = async () => {
			showError("");
			try {
				await api(`/api/users/${user.id}`, { method: "PUT", body: { role: role.value } });
			} catch (e) {
				role.value = user.role;
				showError(e.message);
				return;
			}
			// an admin who made themselves a user can no longer see this page
			state.config = await api("/api/config");
			if (!isAdmin()) {
				window.location.href = "/library";
				return;
			}
			await selectUsers();
		};
		tr.append(
			el("td", "title", user.name),
			el("td", null, user.email),
			el("td", null, user.provider),
			el("td", null, user.created_at.slice(0, 10)),
			el("td", null),
		);
		tr.lastChild.appendChild(role);
		return tr;
	}));
}

// ─── checks (admins only) ───────────────────────────────────────────────────

async function selectChecks() {
	state.view = "checks";
	navigate("checks");
	document.title = "Checks - My World";
	showSection("checks-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("checks");
	updateTools();
	const checks = await api("/api/checks");
	if (state.view === "checks") {
		$("world-count").textContent = `${checks.length} check${checks.length === 1 ? "" : "s"}`;
		$("checks-list").replaceChildren(...checks.map(checkCard));
	}
}

// One check: what it looks at, a button to run it, and the last result under it.
// One row per check, all the same height: the name (what it checks in full
// is its tooltip), the result once run, and Run. A failing check's problems
// are under a closed disclosure, so a long list does not push the rest away.
function checkCard(check) {
	const card = el("div", "check");
	card.dataset.check = check.name;
	const title = el("span", "check-title", check.title);
	title.title = check.description;
	const run = el("button", "text", "Run");
	run.type = "button";
	run.onclick = () => runCheck(card).catch((e) => showError(e.message));
	card.append(title, el("span", "check-result"), run);
	return card;
}

// What a problem is about: a link to the row when it has a place in the app
// and is the viewer's own (the app opens only those), plain text otherwise.
function problemSubject(problem) {
	const match = problem.link.match(/^([a-z-]+)\/(\d+)$/);
	if (!match || problem.owner !== state.config.user.id || !(match[1] in WORLDS)) {
		return el("span", "check-subject", problem.subject);
	}
	const a = el("a", "check-subject", problem.subject);
	a.href = `/library#${problem.link}`;
	a.onclick = (event) => {
		event.preventDefault();
		showRow(match[1], Number(match[2])).catch((e) => showError(e.message));
	};
	return a;
}

async function runCheck(card) {
	const button = card.querySelector("button");
	const out = card.querySelector(".check-result");
	button.disabled = true;
	card.querySelector(".check-details")?.remove();
	out.className = "check-result";
	out.textContent = "Running\u2026";
	try {
		const result = await api(`/api/checks/${card.dataset.check}`);
		out.classList.add(result.ok ? "pass" : "fail");
		if (result.ok) {
			out.textContent = `All ${result.checked} ${result.noun} pass`;
		} else {
			// the count is the toggle of the list, which opens under the whole row
			const list = el("ul", "check-problems check-details");
			list.hidden = true;
			for (const problem of result.problems) {
				const item = el("li");
				item.append(problemSubject(problem), document.createTextNode(`: ${problem.message}`));
				list.appendChild(item);
			}
			const toggle = el("button", "text check-toggle", `${result.problems.length} problem${result.problems.length === 1 ? "" : "s"} in ${result.checked} ${result.noun}`);
			toggle.type = "button";
			toggle.setAttribute("aria-expanded", "false");
			toggle.onclick = () => {
				list.hidden = !list.hidden;
				toggle.setAttribute("aria-expanded", String(!list.hidden));
			};
			out.replaceChildren(toggle);
			card.appendChild(list);
		}
	} catch (e) {
		out.classList.add("fail");
		out.textContent = e.message;
	} finally {
		button.disabled = false;
	}
}

async function runAllChecks() {
	$("checks-run-all").disabled = true;
	try {
		for (const card of $("checks-list").querySelectorAll(".check")) {
			await runCheck(card);
		}
	} finally {
		$("checks-run-all").disabled = false;
	}
}

// A number with what it counts, a link to its tab when there is one.
function statTile(label, value, sub, target) {
	const tile = el(target ? "a" : "div", "stat-tile");
	if (target) {
		tile.href = `/library#${target}`;
		tile.onclick = (event) => {
			event.preventDefault();
			(target in WORLDS ? selectWorld(target) : selectKind(target)).catch((e) => showError(e.message));
		};
	}
	tile.append(el("span", "stat-value", value.toLocaleString()), el("span", "stat-label", label));
	if (sub) {
		tile.appendChild(el("span", "stat-sub", sub));
	}
	return tile;
}

// One series of named counts as horizontal bars, the count written beside each.
function barChart(title, rows) {
	const card = el("section", "chart-card");
	card.appendChild(el("h2", null, title));
	const max = Math.max(1, ...rows.map((r) => r.count));
	const list = el("div", "bar-list");
	for (const row of rows) {
		const line = el("div", "bar-row");
		line.title = `${row.name}: ${row.count}`;
		const track = el("span", "bar-track");
		const fill = el("span", "bar-fill");
		fill.style.width = `${(100 * row.count) / max}%`;
		track.appendChild(fill);
		line.append(el("span", "bar-name", row.name), track, el("span", "bar-value", row.count));
		list.appendChild(line);
	}
	card.appendChild(list);
	return card;
}

// Counts per year as columns, every year in the range shown (empty ones too).
function yearChart(title, rows, noun) {
	const card = el("section", "chart-card");
	card.appendChild(el("h2", null, title));
	if (rows.length === 0) {
		card.appendChild(el("p", "empty", "Nothing dated yet."));
		return card;
	}
	const counts = new Map(rows.map((r) => [r.year, r.count]));
	const first = rows[0].year;
	const last = rows[rows.length - 1].year;
	const max = Math.max(...rows.map((r) => r.count));
	const plot = el("div", "columns");
	const axis = el("div", "column-years");
	const step = Math.max(1, Math.ceil((last - first + 1) / 8));
	for (let year = first; year <= last; year++) {
		const n = counts.get(year) || 0;
		const column = el("span", "column");
		column.title = `${year}: ${n} ${noun}`;
		const fill = el("span", "column-fill");
		fill.style.height = `${(100 * n) / max}%`;
		column.appendChild(fill);
		plot.appendChild(column);
		axis.appendChild(el("span", null, (year - first) % step === 0 ? String(year) : ""));
	}
	card.append(plot, axis, el("p", "chart-note", `Most: ${max} ${noun} in a year. Hover a column for its year.`));
	return card;
}

function renderStats(stats) {
	const tiles = el("div", "stat-tiles");
	for (const kind of stats.library) {
		const sub = Object.entries(kind.by_status).map(([status, n]) => `${n} ${status.toLowerCase()}`).join(" · ");
		tiles.appendChild(statTile(kind.label, kind.total, sub, kind.kind));
	}
	tiles.append(
		statTile("Concerts", stats.concerts, `${stats.performers} performers`, "concerts"),
		statTile("Museum visits", stats.museum_visits, `${stats.museums} museums`, "museums"),
		statTile("Audio courses", stats.audio_courses, "", "audio-courses"),
		statTile("People", stats.people, "", "people"),
		statTile("Organizations", stats.organizations, "", "organizations"),
		statTile("Organization types", stats.organization_types, "", "organization-types"),
		statTile("Person types", stats.person_types, "", "person-types"),
		statTile("Relation types", stats.relation_types, "", "relation-types"),
		statTile("Devices", stats.devices, "", "devices"),
		statTile("Photos and logos", stats.images, "", null),
	);
	const charts = el("div", "stat-charts");
	charts.append(
		barChart("People by type (one with several types counts in each)", stats.people_by_type),
		barChart("Organizations by type", stats.organizations_by_type),
		barChart("Organizations by relation (one with several relations counts in each)", stats.organizations_by_relation),
		yearChart("Concerts per year", stats.concerts_by_year, "concerts"),
		yearChart("Museum visits per year", stats.museums_by_year, "visits"),
	);
	$("stats-view").replaceChildren(tiles, charts);
}

// hash: where the address bar points, the view itself unless one of its rows is wanted
async function selectWorld(view, hash = view) {
	state.view = view;
	navigate(hash);
	const [heading, path] = WORLDS[view];
	document.title = `${heading.replace(/^My /, "")} - My World`;
	showSection("world-view");
	markActive();
	updateTools();
	showError("");
	$("world-search").value = "";
	if (!worldCache[view]) {
		$("world-count").textContent = "Loading...";
		$("cards").replaceChildren();
		for (const [tableId] of Object.values(TABLES)) {
			$(tableId).hidden = true;
		}
		worldCache[view] = await api(path);
		await fillTypeFilter(view);
		if (state.view === view) {
			renderWorld();
		}
		return;
	}
	// what was fetched before is shown at once, then fetched again: a row
	// added, changed or removed elsewhere (another tab, a script) shows up
	await fillTypeFilter(view);
	if (state.view === view) {
		renderWorld();
	}
	await reloadWorld(view);
}

// Fetch a view again and redraw it if it is still on screen, keeping the
// search, the filter and the scroll; the other views' rows are dropped, to be
// fetched again when they are opened.
async function reloadWorld(view) {
	for (const key of Object.keys(worldCache)) {
		if (key !== view) {
			delete worldCache[key];
		}
	}
	const rows = await api(WORLDS[view][1]);
	worldCache[view] = rows;
	if (state.view === view && !$("add-dialog").open) {
		await fillTypeFilter(view);
		const y = window.scrollY;
		renderWorld();
		window.scrollTo(0, y);
	}
}

// After a change: everything is fetched again (people and their outings link
// each other), and the view on screen is redrawn with its search kept.
async function refreshWorld() {
	for (const key of Object.keys(worldCache)) {
		delete worldCache[key];
	}
	const view = state.view;
	worldCache[view] = await api(WORLDS[view][1]);
	await fillTypeFilter(view);
	renderWorld();
}

// Open the People or Organizations view at one row or card, scrolled to and highlighted.
async function showRow(view, id) {
	await selectWorld(view, `${view}/${id}`);
	const row = $(`${slug(view)}-${id}`);
	if (!row) {
		return;
	}
	for (const old of document.querySelectorAll("#world-view .highlight")) {
		old.classList.remove("highlight");
	}
	row.classList.add("highlight");
	row.scrollIntoView({ block: "center" });
}

function setupWorlds() {
	$("stats-link").onclick = (event) => {
		event.preventDefault();
		selectStats().catch((e) => showError(e.message));
	};
	// the admin pages: for everyone else the links stay, disabled
	for (const [id, select, title] of [
		["users-link", selectUsers, "Only an admin can see the accounts"],
		["checks-link", selectChecks, "Only an admin can run the checks"],
	]) {
		const link = $(id);
		if (!isAdmin()) {
			link.setAttribute("aria-disabled", "true");
			link.tabIndex = -1;
			link.title = title;
		}
		link.onclick = (event) => {
			event.preventDefault();
			if (isAdmin()) {
				select().catch((e) => showError(e.message));
			}
		};
	}
	$("checks-run-all").onclick = () => runAllChecks().catch((e) => showError(e.message));
	$("world-search").oninput = rerender;
	setupSort();
	$("connections-close").onclick = () => $("connections-dialog").close();
	// the type filter's checkbox menu opens under its button and closes on a click elsewhere or Escape
	$("type-filter").onclick = () => {
		const menu = $("type-filter-menu");
		menu.hidden = !menu.hidden;
		$("type-filter").setAttribute("aria-expanded", String(!menu.hidden));
	};
	document.addEventListener("click", (event) => {
		if (!event.target.closest(".type-filter")) {
			$("type-filter-menu").hidden = true;
			$("type-filter").setAttribute("aria-expanded", "false");
		}
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape") {
			$("type-filter-menu").hidden = true;
			$("type-filter").setAttribute("aria-expanded", "false");
		}
	});
	setupLayouts();
}

// ─── the add dialog ─────────────────────────────────────────────────────────

// One dialog, opened by the + button, showing the form of whatever is on screen.
const DIALOG_FORMS = ["add-form", "concert-form", "museum-form", "audio-course-form", "person-form", "organization-form", "organization-type-form", "person-type-form", "relation-type-form", "device-form"];
const PHOTO_MAX_BYTES = 8 * 1024 * 1024;

function dialogError(message) {
	const box = $("dialog-error");
	box.textContent = message;
	box.hidden = !message;
}

async function worldList(view) {
	if (!worldCache[view]) {
		worldCache[view] = await api(WORLDS[view][1]);
	}
	return worldCache[view];
}

// What a picker suggests for a row: the name, and for people the type and
// description too, since two people may share a name. A person with no name
// is called by the description already, so it is not repeated.
function chipLabel(row) {
	const named = row.first_name || row.surname;
	const more = [(row.types || []).map((t) => t.name).join("/"), named && row.description?.slice(0, 40)].filter(Boolean);
	return more.length && "first_name" in row ? `${row.name} (${more.join(", ")})` : row.name;
}

// A picker (data-chips="people" or "organizations"): names from that view become
// removable chips; the ids are sent.
function addChip(box, person) {
	if (box.selected.has(person.id)) {
		return;
	}
	box.selected.set(person.id, person.name);
	const chip = el("span", "chip", person.name);
	const remove = el("button", "chip-remove", "\u00d7");
	remove.type = "button";
	remove.setAttribute("aria-label", `Remove ${person.name}`);
	remove.onclick = () => {
		box.selected.delete(person.id);
		chip.remove();
		syncAlone(box.closest("form"));
	};
	chip.appendChild(remove);
	box.insertBefore(chip, box.querySelector("input"));
	syncAlone(box.closest("form"));
}

// "I went alone" and the With picker exclude each other: with people chosen the
// box is disabled, and with the box ticked the picker is.
function syncAlone(form) {
	const alone = form?.elements.alone;
	if (!alone) {
		return;
	}
	const box = form.querySelector("[data-field=people]");
	alone.disabled = box.selected.size > 0;
	box.querySelector("input").disabled = alone.checked;
	box.classList.toggle("disabled", alone.checked);
}

function setupChips(box) {
	box.selected = new Map();
	const input = box.querySelector("input");
	// Only rows that exist can be picked: text that names none stays, marked
	// invalid, and the form will not save while it is there (pendingChipsOk).
	const pick = (quiet) => {
		const name = input.value.trim();
		input.classList.remove("invalid");
		if (!name) {
			return true;
		}
		const view = box.dataset.chips;
		const rows = worldCache[view] || [];
		const wanted = name.toLowerCase();
		// a suggestion names one row exactly; a bare name only when no one else has it
		let matches = rows.filter((row) => chipLabel(row).toLowerCase() === wanted);
		if (matches.length === 0) {
			matches = rows.filter((row) => row.name.toLowerCase() === wanted);
		}
		if (matches.length !== 1) {
			input.classList.add("invalid");
			if (!quiet) {
				dialogError(matches.length
					? `${matches.length} are called ${name}: pick one from the suggestions.`
					: `${name} is not in ${WORLDS[view][0]}: pick one from the suggestions, or add it to ${WORLDS[view][0]} first.`);
			}
			return false;
		}
		const person = matches[0];
		dialogError("");
		addChip(box, person);
		input.value = "";
		return true;
	};
	box.pick = pick;
	input.onkeydown = (event) => {
		if (event.key === "Enter" || event.key === ",") {
			event.preventDefault();
			pick(false);
		} else if (event.key === "Backspace" && !input.value && box.selected.size) {
			const chips = box.querySelectorAll(".chip");
			chips[chips.length - 1].querySelector("button").click();
		}
	};
	// a pick from the suggestion list arrives as a replacement of the whole text
	input.oninput = (event) => {
		if (!(event instanceof InputEvent) || event.inputType === "insertReplacementText") {
			pick(true);
		}
	};
	// leaving the box with a name that matches nothing says so at once
	input.onblur = () => pick(false);
}

// Before saving: every picker's leftover text must turn into a chip; false
// (with the reason shown) when some text names nothing that exists.
function pendingChipsOk(form) {
	return [...form.querySelectorAll("[data-chips]")].every((box) => box.pick(false));
}

function resetForm(form) {
	form.reset();
	for (const box of form.querySelectorAll("[data-chips]")) {
		box.selected.clear();
		box.querySelector("input").classList.remove("invalid");
		for (const chip of box.querySelectorAll(".chip")) {
			chip.remove();
		}
	}
	syncAlone(form);
}

async function uploadPhoto(form) {
	const file = form.elements.photo.files[0];
	if (!file) {
		return null;
	}
	if (file.size > PHOTO_MAX_BYTES) {
		throw new Error("The photo is larger than 8 MB.");
	}
	const data = new FormData();
	data.append("file", file);
	const response = await fetch("/api/images", { method: "POST", body: data });
	const result = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(result.error || response.statusText);
	}
	return result.id;
}

// the ids picked in the chips box of field ("people", "performers", "organizations")
function chosen(form, field) {
	return [...form.querySelector(`[data-field=${field}]`).selected.keys()];
}

function where() {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
	} catch (e) {
		return "";
	}
}

// view -> what its form posts
const WORLD_BODIES = {
	"audio-courses": async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			lecturers: chosen(form, "lecturers"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			review: value("review"),
			device_id: value("device_id"),
			listened_at: value("listened_at"),
			started: value("started"),
			ended: state.editing?.ended || "",
			progress: value("progress"),
			great_courses_id: value("great_courses_id"),
			great_courses_slug: value("great_courses_slug"),
			audible_asin: value("audible_asin"),
			link: value("link"),
			image_id: await uploadPhoto(form),
		};
	},
	concerts: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			event: value("event"),
			performers: chosen(form, "performers"),
			genre: value("genre"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			venue: value("venue"),
			city: value("city"),
			country: value("country"),
			people: chosen(form, "people"),
			tickets: value("tickets"),
			broadcast: form.elements.broadcast.checked,
			review: value("review"),
			remark: value("remark"),
			image_id: await uploadPhoto(form),
			image_source: value("image_source"),
			image_license: value("image_license"),
			image_author: value("image_author"),
		};
	},
	museums: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			city: value("city"),
			address: value("address"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			tickets: value("tickets"),
			url: value("url"),
			people: chosen(form, "people"),
			alone: form.elements.alone.checked,
			review: value("review"),
			remark: value("remark"),
			image_id: await uploadPhoto(form),
		};
	},
	people: async (form) => ({
		first_name: form.elements.first_name.value,
		surname: form.elements.surname.value,
		type_ids: chosen(form, "types"),
		organizations: chosen(form, "organizations"),
		description: form.elements.description.value,
	}),
	organizations: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			type_id: value("type_id"),
			relation_ids: chosen(form, "relations"),
			status: value("status"),
			website: value("website"),
			location: value("location"),
			address: value("address"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			what_happened: value("what_happened"),
			remark: value("remark"),
			image_id: await uploadPhoto(form),
		};
	},
	"organization-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"person-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"relation-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	devices: async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
};

function setupWorldForm(view) {
	const path = WORLDS[view][1];
	const form = $(`${slug(view)}-form`);
	form.onsubmit = async (event) => {
		event.preventDefault();
		dialogError("");
		if (!pendingChipsOk(form)) {
			return;
		}
		const submit = form.querySelector("button[type=submit]");
		submit.disabled = true;
		try {
			const body = await WORLD_BODIES[view](form);
			if (state.editing) {
				await api(`${path}/${state.editing.id}`, { method: "PUT", body });
			} else {
				await api(path, { method: "POST", body });
			}
			$("add-dialog").close();
			await refreshWorld();
		} catch (e) {
			dialogError(e.message);
		} finally {
			submit.disabled = false;
		}
	};
}

function fillWorldForm(form, item) {
	for (const element of form.elements) {
		if (!element.name || element.type === "file") {
			continue;
		}
		const value = item[element.name];
		if (element.type === "checkbox") {
			element.checked = Boolean(value);
		} else if (Array.isArray(value)) {
			element.value = value.join(", ");
		} else {
			element.value = value ?? "";
		}
	}
	for (const box of form.querySelectorAll("[data-chips]")) {
		for (const row of item[box.dataset.field]) {
			addChip(box, row);
		}
	}
	if (form.elements.type_id) {
		form.elements.type_id.value = item.type ? item.type.id : "";
	}
}

// The work form: a new entry starts empty (with the film search for films); an
// existing one shows its work, which is shared with other users and so read only.
function prepareWorkForm(form, entry) {
	const film = state.config.tmdb && state.kind === "film" && !entry;
	if (state.config.tmdb) {
		movieIdsReset();
	}
	$("movie-search").hidden = !film;
	$("movie-ids").hidden = !film;
	$("movie-results").hidden = true;
	$("movie-hint").hidden = true;
	$("movie-query").value = "";
	const values = entry || { title: "", creator: "", year: "", status: "done", rating: "", started_on: "", notes: "", finished_on: new Date().toISOString().slice(0, 10) };
	for (const name of ["title", "creator", "year", "status", "rating", "started_on", "finished_on", "notes"]) {
		form.elements[name].value = values[name] ?? "";
	}
	for (const name of MOVIE_FIELDS) {
		form.elements[name].readOnly = Boolean(entry);
	}
}

// The organization dialog's type list: the user's own Org types, and "none".
async function fillTypes(select, typesView) {
	const types = await worldList(typesView);
	const none = document.createElement("option");
	none.value = "";
	none.textContent = "(none)";
	select.replaceChildren(none, ...types.map((t) => {
		const option = document.createElement("option");
		option.value = t.id;
		option.textContent = t.name;
		return option;
	}));
}

// The + button (item null) or a click on an item: the dialog with the form of the view on screen.
async function openDialog(item) {
	state.editing = item;
	const world = WORLDS[state.view];
	const form = world ? $(`${slug(state.view)}-form`) : $("add-form");
	for (const id of DIALOG_FORMS) {
		$(id).hidden = $(id) !== form;
	}
	const noun = world ? world[2] : state.config.kinds[state.kind].name.toLowerCase();
	$("dialog-title").textContent = item ? `Edit ${noun}` : `Add ${/^[aeiou]/.test(noun) ? "an" : "a"} ${noun}`;
	form.querySelector("button[type=submit]").textContent = item ? "Save" : "Add";
	const remove = form.querySelector("button.delete");
	remove.hidden = !item;
	remove.textContent = "Delete";
	delete remove.dataset.armed;
	dialogError("");
	if (world) {
		for (const box of form.querySelectorAll("[data-chips]")) {
			const rows = await worldList(box.dataset.chips);
			$(box.querySelector("input").getAttribute("list")).replaceChildren(...rows.map((row) => {
				const option = document.createElement("option");
				option.value = chipLabel(row);
				return option;
			}));
		}
		if (form.elements.type_id) {
			await fillTypes(form.elements.type_id, TYPED[state.view]);
		}
		if (form.elements.device_id) {
			await fillTypes(form.elements.device_id, "devices");
		}
		resetForm(form);
		if (state.view === "organizations" && !item) {
			const company = worldCache["organization-types"].find((t) => t.name === "Company");
			form.elements.type_id.value = company ? company.id : "";
		}
		if (item) {
			fillWorldForm(form, item);
		}
		if (form.elements.device_id) {
			form.elements.device_id.value = item?.device ? item.device.id : "";
		}
		syncAlone(form);
	} else {
		prepareWorkForm(form, item);
	}
	$("add-dialog").showModal();
	const first = [...form.querySelectorAll("input")].find((i) => i.offsetParent !== null && !i.readOnly);
	if (first) {
		first.focus();
	}
}

// Delete asks twice, in the button itself: the first click arms it.
async function deleteEditing(button) {
	if (!button.dataset.armed) {
		button.dataset.armed = "1";
		button.textContent = "Delete for good?";
		return;
	}
	const world = WORLDS[state.view];
	if (world) {
		await api(`${world[1]}/${state.editing.id}`, { method: "DELETE" });
		$("add-dialog").close();
		await refreshWorld();
	} else {
		await api(`/api/library/${state.editing.work_id}`, { method: "DELETE" });
		$("add-dialog").close();
		await loadEntries();
	}
}

function setupAddDialog() {
	const dialog = $("add-dialog");
	for (const button of dialog.querySelectorAll("button.cancel")) {
		button.onclick = () => dialog.close();
	}
	for (const button of dialog.querySelectorAll("button.delete")) {
		button.onclick = () => deleteEditing(button).catch((e) => dialogError(e.message));
	}
	for (const box of dialog.querySelectorAll("[data-chips]")) {
		setupChips(box);
	}
	$("museum-form").elements.alone.onchange = () => syncAlone($("museum-form"));
	const { rating_min, rating_max } = state.config;
	$("museum-form").elements.rating.min = rating_min;
	$("museum-form").elements.rating.max = rating_max;
	$("audio-course-form").elements.rating.min = rating_min;
	$("audio-course-form").elements.rating.max = rating_max;
	for (const view of Object.keys(WORLDS)) {
		setupWorldForm(view);
	}
	$("fab").onclick = () => {
		openDialog(null).catch((e) => showError(e.message));
	};
}

// ─── entry point ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
	showBuild();
	const page = document.body.dataset.page;
	const run = page === "library" ? libraryPage : indexPage;
	run().catch((e) => showError(e.message));
});
