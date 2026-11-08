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
const state = { config: null, kind: "book", view: "concerts", entries: [], editing: null };

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
	const shown = sortItems(state.entries.filter(searchMatches));
	$("rows").replaceChildren(...shown.map(renderRow));
	$("entries").hidden = shown.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add one with the + button.`;
	showCount(shown.length, state.entries.length, plural.toLowerCase());
}

function showCount(shown, total, what) {
	$("world-count").textContent = total === 0 ? "" : shown === total ? `${total} ${what}` : `${shown} of ${total} ${what}`;
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
};
const SORT_KEY = "myworld.sort";

function sortFields() {
	if (state.view === "stats") {
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
	// the stats page has nothing to search or add: both stay, disabled
	$("world-search").disabled = state.view === "stats";
	$("fab").disabled = state.view === "stats";
	const cards = state.view in CARDS;
	for (const layout of $("layouts").querySelectorAll("button")) {
		layout.disabled = !cards;
	}
	$("layouts").setAttribute("aria-disabled", String(!cards));
}

// After a change to the search, the filter or the sort: redraw what is on screen.
function rerender() {
	if (state.view === "stats") {
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
	window.location.hash = kind;
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
	const requested = window.location.hash.slice(1);
	const linked = requested.match(/^(concerts|museums|people|organizations|organization-types|person-types)\/(\d+)$/);
	if (linked) {
		await showRow(linked[1], Number(linked[2]));
	} else if (requested === "stats") {
		await selectStats();
	} else if (requested in state.config.kinds) {
		await selectKind(requested);
	} else {
		await selectWorld(requested in WORLDS ? requested : "concerts");
	}
}

// ─── concerts, museums, people, organizations ──────────────────────────────

// view -> [page title, API path, singular, tab label]; the rows are the signed-in user's own
const WORLDS = {
	concerts: ["My Concerts", "/api/concerts", "concert", "Concerts"],
	museums: ["My Museums", "/api/museums", "museum", "Museums"],
	people: ["People", "/api/people", "person", "People"],
	organizations: ["Organizations", "/api/organizations", "organization", "Organizations"],
	"organization-types": ["Organization types", "/api/organization-types", "organization type", "Org types"],
	"person-types": ["Person types", "/api/person-types", "person type", "Person types"],
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
	detail(list, "Date", formatDate(item));
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	linksDetail(list, "With", "people", item.people);
	detail(list, "Tickets", item.tickets);
	detail(list, "Review", item.review);
	detail(list, "Remark", item.remark);
	websiteDetail(list, item.url);
	return card;
}

// what the organization was to me, in words
const FUNCTIONS = {
	teaching: "I taught there",
	"training-provider": "Hired me to teach",
	consulting: "I consulted",
	certification: "Certified me",
	publisher: "Publisher",
	education: "I studied there",
};

function organizationCard(item) {
	const { card, list } = cardShell(item, item.location, "logo");
	linksDetail(list, "Type", "organization-types", item.type ? [item.type] : []);
	detail(list, "Was", item.functions.map((f) => FUNCTIONS[f] || f));
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

const CARDS = { concerts: concertCard, museums: museumCard, organizations: organizationCard };

// Material "link"
const LINK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>';

// Everything that ties a person to the user, grouped, each entry a link to its card.
async function showConnections(person) {
	const [concerts, museums] = await Promise.all([worldList("concerts"), worldList("museums")]);
	const has = (list) => list.some((p) => p.id === person.id);
	const groups = [
		["Concerts you went to together", "concerts", concerts.filter((c) => has(c.people))],
		["Concerts they performed at", "concerts", concerts.filter((c) => has(c.performers))],
		["Museums you visited together", "museums", museums.filter((m) => has(m.people))],
		["Organizations", "organizations", person.organizations],
	].filter(([, , items]) => items.length > 0);
	$("connections-title").textContent = person.name;
	const body = $("connections-body");
	body.replaceChildren();
	if (groups.length === 0) {
		body.appendChild(el("p", "empty", "No concerts, museums or organizations link you yet."));
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

// The enumeration of what an organization can be, and how many are of each.
// A row of an enumeration (Org types, Person types), with how many rows are of it.
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
};

// The type filter next to the search, for views whose rows have a type: "" is
// everything, "none" the rows without one, else a type id. Kept per view.
const typeFilters = {};

async function fillTypeFilter(view) {
	const select = $("type-filter");
	const typesView = TYPED[view];
	const option = (value, label) => {
		const node = document.createElement("option");
		node.value = value;
		node.textContent = label;
		return node;
	};
	// a view without types keeps the control, disabled
	select.disabled = !typesView;
	if (!typesView) {
		select.replaceChildren(option("", "All types"));
		return;
	}
	const types = await worldList(typesView);
	select.replaceChildren(
		option("", "All types"),
		...types.map((t) => option(String(t.id), `${t.name} (${t.count})`)),
		option("none", "No type"),
	);
	select.value = typeFilters[view] || "";
}

function typeMatches(item) {
	const wanted = typeFilters[state.view] || "";
	if (!TYPED[state.view] || wanted === "") {
		return true;
	}
	// a person has a list of types, an organization one
	const types = item.types || (item.type ? [item.type] : []);
	return wanted === "none" ? types.length === 0 : types.some((t) => String(t.id) === wanted);
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
	const shown = sortItems(items.filter((item) => typeMatches(item) && searchMatches(item)));
	const table = TABLES[view];
	$("cards").hidden = Boolean(table);
	$("cards").replaceChildren(...(table ? [] : shown.map(CARDS[view])));
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
}

function markActive() {
	for (const a of document.querySelectorAll(".kinds a")) {
		const active = a.dataset.world ? a.dataset.world === state.view : a.dataset.kind === state.view;
		a.classList.toggle("active", active);
	}
	$("stats-link").classList.toggle("active", state.view === "stats");
}

// One of the three page bodies: the library table, the cards and tables, the stats.
function showSection(id) {
	for (const section of ["library-view", "world-view", "stats-view"]) {
		$(section).hidden = section !== id;
	}
}

// ─── stats ──────────────────────────────────────────────────────────────────

async function selectStats() {
	state.view = "stats";
	window.location.hash = "stats";
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
		statTile("People", stats.people, "", "people"),
		statTile("Organizations", stats.organizations, "", "organizations"),
		statTile("Organization types", stats.organization_types, "", "organization-types"),
		statTile("Person types", stats.person_types, "", "person-types"),
		statTile("Photos and logos", stats.images, "", null),
	);
	const charts = el("div", "stat-charts");
	charts.append(
		barChart("People by type (one with several types counts in each)", stats.people_by_type),
		barChart("Organizations by type", stats.organizations_by_type),
		yearChart("Concerts per year", stats.concerts_by_year, "concerts"),
		yearChart("Museum visits per year", stats.museums_by_year, "visits"),
	);
	$("stats-view").replaceChildren(tiles, charts);
}

async function selectWorld(view) {
	state.view = view;
	window.location.hash = view;
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
	}
	await fillTypeFilter(view);
	if (state.view === view) {
		renderWorld();
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
	await selectWorld(view);
	window.location.hash = `${view}/${id}`;
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
	$("world-search").oninput = rerender;
	setupSort();
	$("connections-close").onclick = () => $("connections-dialog").close();
	$("type-filter").onchange = () => {
		typeFilters[state.view] = $("type-filter").value;
		rerender();
	};
	setupLayouts();
}

// ─── the add dialog ─────────────────────────────────────────────────────────

// One dialog, opened by the + button, showing the form of whatever is on screen.
const DIALOG_FORMS = ["add-form", "concert-form", "museum-form", "person-form", "organization-form", "organization-type-form", "person-type-form"];
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
// description too, since two people may share a name.
function chipLabel(row) {
	const more = [(row.types || []).map((t) => t.name).join("/"), row.description?.slice(0, 40)].filter(Boolean);
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
	};
	chip.appendChild(remove);
	box.insertBefore(chip, box.querySelector("input"));
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
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			tickets: value("tickets"),
			url: value("url"),
			people: chosen(form, "people"),
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
			functions: value("functions").split(",").map((f) => f.trim()).filter(Boolean),
			status: value("status"),
			website: value("website"),
			location: value("location"),
			address: value("address"),
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
		resetForm(form);
		if (state.view === "organizations" && !item) {
			const company = worldCache["organization-types"].find((t) => t.name === "Company");
			form.elements.type_id.value = company ? company.id : "";
		}
		if (item) {
			fillWorldForm(form, item);
		}
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
	const { rating_min, rating_max } = state.config;
	$("museum-form").elements.rating.min = rating_min;
	$("museum-form").elements.rating.max = rating_max;
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
