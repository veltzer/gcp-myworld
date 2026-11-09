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

// [field, label, url of the work on that catalog, id of the "open" link in the add form (films only)]
const CATALOGS = [
	["imdb_id", "IMDb", (id) => `https://www.imdb.com/title/${id}/`, "imdb-link"],
	["tmdb_id", "TMDB", (id) => `https://www.themoviedb.org/movie/${id}`, "tmdb-link"],
	["rotten_tomatoes_id", "RT", (id) => `https://www.rottentomatoes.com/${id}`, "rt-link"],
	["goodreads_id", "Goodreads", (id) => `https://www.goodreads.com/book/show/${id}`, null],
	["simania_id", "Simania", (id) => `https://simania.co.il/bookdetails.php?item_id=${id}`, null],
];

// The read-only id fields of the add form: the values come from the search, never typed.
function showMovieIds(values) {
	const form = $("add-form");
	for (const [key, , url, linkId] of CATALOGS.filter((catalog) => catalog[3])) {
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

// A library entry as a card, laid out like every other card view; its cover
// is the image, the catalog links (IMDb, Goodreads, ...) sit under the title.
function libraryCard(entry) {
	const { creator } = state.config.kinds[state.kind];
	const { card, body, list } = cardShell({ ...entry, name: entry.title }, [entry.creator, entry.year].filter(Boolean).join(", "), "cover");
	// an entry is known by its work: "book-12", opened by the link #book/12
	card.id = `${state.kind}-${entry.work_id}`;
	// the dialog edits the entry as it is
	editable(card, entry);
	const links = catalogLinks(entry);
	if (links) {
		body.insertBefore(links, list);
	}
	// the authors as links to them in People; the plain text for an entry with none linked
	if (entry.authors.length) {
		linksDetail(list, creator, "people", entry.authors);
	} else {
		detail(list, creator, entry.creator);
	}
	detail(list, "Year", entry.year === null ? "" : String(entry.year));
	detail(list, "Status", state.config.statuses[entry.status] || entry.status);
	if (entry.rating !== null) {
		detail(list, "Rating", `${entry.rating}/${state.config.rating_max}`);
	}
	detail(list, "Started", entry.started_on ?? "");
	detail(list, "Finished", entry.finished_on ?? "");
	detail(list, "Notes", entry.notes);
	return card;
}

// the sidebar's groups of views (the library's kinds come first, from the config)
// The library kinds (books) come first in Datasets, ahead of these
const NAV_GROUPS = [
	["Datasets", ["concerts", "museums", "audio-courses", "youtube", "places"]],
	["People", ["people", "groups", "organizations"]],
	["Types", ["organization-types", "person-types", "relation-types", "person-relation-types", "person-organization-types", "devices"]],
];

function sideLink(label, key, open) {
	const a = el("a", "side-link");
	a.href = `/library#${key}`;
	a.append(el("span", "side-label", label), el("span", "side-count"));
	a.onclick = (event) => {
		event.preventDefault();
		closeSidebarOnPhone();
		open();
	};
	return a;
}

function sideGroup(heading, links) {
	const group = el("div", "side-group");
	group.append(el("h2", "side-heading", heading), ...links);
	return group;
}

// The sidebar, made once; after that only which page is active changes
function renderKinds() {
	const nav = $("kinds");
	if (!nav.children.length) {
		const library = Object.entries(state.config.kinds).map(([kind, { plural }]) => {
			const a = sideLink(plural, kind, () => selectKind(kind));
			a.dataset.kind = kind;
			return a;
		});
		const groups = NAV_GROUPS.map(([heading, views], i) => sideGroup(heading, [...(i === 0 ? library : []), ...views.map((view) => {
			const a = sideLink(WORLDS[view][3], view, () => selectWorld(view).catch((e) => showError(e.message)));
			a.dataset.world = view;
			return a;
		})]));
		nav.append(...groups);
	}
	markActive();
}

// How many rows a view or library kind has, next to its name in the sidebar
function setCount(key, count) {
	const span = document.querySelector(`#kinds a[data-world="${key}"] .side-count, #kinds a[data-kind="${key}"] .side-count`);
	if (span) {
		span.textContent = count.toLocaleString();
	}
}

// The counts when the page opens, from the stats; each list keeps its own fresh as it is loaded
async function loadCounts() {
	const stats = await api("/api/stats");
	for (const kind of stats.library) {
		setCount(kind.kind, kind.total);
	}
	const keys = {
		concerts: "concerts", museums: "museum_visits", "audio-courses": "audio_courses", youtube: "youtube_videos",
		places: "places", people: "people", groups: "groups", organizations: "organizations", "organization-types": "organization_types",
		"person-types": "person_types", "relation-types": "relation_types", "person-relation-types": "person_relation_types",
		"person-organization-types": "person_organization_types", devices: "devices",
	};
	for (const [view, key] of Object.entries(keys)) {
		setCount(view, stats[key]);
	}
}

// ─── the sidebar: folded away on a wide screen, slid out over the page on a phone ───

const SIDEBAR_KEY = "myworld.sidebar";
const phone = window.matchMedia("(max-width: 900px)");

function sidebarShown() {
	return phone.matches ? document.body.classList.contains("sidebar-open") : !document.body.classList.contains("sidebar-folded");
}

function syncSidebar() {
	const shown = sidebarShown();
	$("nav-toggle").setAttribute("aria-expanded", String(shown));
	$("sidebar-scrim").hidden = !(phone.matches && shown);
}

function closeSidebarOnPhone() {
	if (phone.matches) {
		document.body.classList.remove("sidebar-open");
		syncSidebar();
	}
}

function setupSidebar() {
	try {
		document.body.classList.toggle("sidebar-folded", localStorage.getItem(SIDEBAR_KEY) === "folded");
	} catch (e) {
		// no storage (a private window): the sidebar starts shown
	}
	$("nav-toggle").onclick = () => {
		if (phone.matches) {
			document.body.classList.toggle("sidebar-open");
		} else {
			const folded = document.body.classList.toggle("sidebar-folded");
			try {
				localStorage.setItem(SIDEBAR_KEY, folded ? "folded" : "shown");
			} catch (e) {
				// remembered for this page only
			}
		}
		syncSidebar();
	};
	$("sidebar-scrim").onclick = closeSidebarOnPhone;
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && phone.matches && sidebarShown()) {
			closeSidebarOnPhone();
		}
	});
	phone.addEventListener("change", () => {
		document.body.classList.remove("sidebar-open");
		syncSidebar();
	});
	syncSidebar();
}

async function loadEntries() {
	state.entries = await api(`/api/library-entries?kind=${encodeURIComponent(state.kind)}`);
	// the statuses in the filter, with how many entries have each
	await fillTypeFilter(state.kind);
	renderEntries();
}

// The library's cards: searched and sorted with the same toolbar as every other tab.
// What the list on screen is: a new view, search, sort, filter or layout starts again at the first page
function listKey(view) {
	const sort = currentSort();
	return JSON.stringify([view, $("world-search").value, sort?.field[0], sort?.direction, [...pickedTypes(view)], state.layout]);
}

function renderEntries() {
	const { plural } = state.config.kinds[state.kind];
	const shown = rankBySearch(sortItems(state.entries.filter((entry) => typeMatches(entry) && searchMatches(entry))));
	setCount(state.kind, state.entries.length);
	$("library-cards").replaceChildren(...pageOf(shown, listKey(state.kind)).map(libraryCard));
	$("library-cards").hidden = shown.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add one with the + button.`;
	showCount(shown.length, state.entries.length, plural.toLowerCase());
}

function showCount(shown, total, what) {
	const n = (count) => count.toLocaleString();
	$("world-count").textContent = total === 0 ? "" : shown === total ? `${n(total)} ${what}` : `${n(shown)} of ${n(total)} ${what}`;
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
		["place", "Place", (c) => c.place?.name, "asc"],
		["city", "City", (c) => c.place?.city, "asc"],
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
	youtube: [
		["date", "Watched", (v) => v.date_sort, "desc"],
		["name", "Name", (v) => v.name, "asc"],
		["rating", "Rating", (v) => v.rating, "desc"],
		["channel", "Channel", (v) => v.channel, "asc"],
		["views", "Views", (v) => v.views, "desc"],
		["duration", "Length", (v) => v.duration, "desc"],
		["uploaded", "Uploaded", (v) => v.uploaded, "desc"],
	],
	groups: [
		["name", "Name", (g) => g.name, "asc"],
		["members", "Members", (g) => g.members.length, "desc"],
		["concerts", "Concerts", (g) => g.concerts.length, "desc"],
	],
	places: [
		["name", "Name", (p) => p.name, "asc"],
		["city", "City", (p) => p.city, "asc"],
		["country", "Country", (p) => p.country, "asc"],
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
};
const SORT_KEY = "myworld.sort";

// views that are a page of their own, outside the tabs: nothing to search, sort or add
const PAGES = new Set(["stats", "users", "checks", "schema"]);

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

async function selectKind(kind, hash = kind) {
	state.kind = kind;
	state.view = kind;
	// the last kind's entries are not this one's: the filter counts start at 0 until they load
	state.entries = [];
	navigate(hash);
	showSection("library-view");
	$("world-search").value = "";
	await fillTypeFilter(kind);
	updateTools();
	const { plural, creator } = state.config.kinds[kind];
	document.title = `${plural} - My World`;
	$("creator-label").textContent = creator;
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
	setupSidebar();
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
			if (el.name && el.type !== "file") {
				body[el.name] = el.value;
			}
		}
		try {
			body.image_id = await uploadPhoto(form);
			if (state.editing) {
				await api(`/api/library-entries/${state.editing.work_id}`, { method: "PUT", body });
			} else {
				await api("/api/library-entries", { method: "POST", body });
			}
			$("add-dialog").close();
			await loadEntries();
		} catch (e) {
			dialogError(e.message);
		}
	};

	setupMovieSearch();
	setupWorlds();
	setupViewChecks();
	setupDatePicks();
	setupPager();
	setupAddDialog();
	renderKinds();
	loadCounts().catch((e) => showError(e.message));
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
	const linked = requested.match(/^([a-z-]+)\/(\d+)$/);
	if (linked && (linked[1] in WORLDS || linked[1] in state.config.kinds)) {
		await showRow(linked[1], Number(linked[2]));
	} else if (requested === "stats") {
		await selectStats();
	} else if (requested === "users" && isAdmin()) {
		await selectUsers();
	} else if (requested === "checks" && isAdmin()) {
		await selectChecks();
	} else if (requested === "schema" && isAdmin()) {
		await selectSchema();
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

// view -> [page title, API path, singular, sidebar label]; the rows are the signed-in user's own
const WORLDS = {
	concerts: ["My Concerts", "/api/concert-visits", "concert", "Concerts"],
	museums: ["My Museums", "/api/museum-visits", "museum", "Museums"],
	"audio-courses": ["Audio courses", "/api/audio-courses", "audio course", "Audio courses"],
	youtube: ["YouTube videos", "/api/youtube-videos", "YouTube video", "YouTube"],
	places: ["Places", "/api/places", "place", "Places"],
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
};

// views whose rows have a type -> the view of their enumeration
const TYPED = { people: "person-types", organizations: "organization-types" };

// a view's name in ids: a world's noun ("museum-visit"), or a library kind ("book")
function slug(view) {
	if (!(view in WORLDS)) {
		return view;
	}
	return WORLDS[view][2].toLowerCase().replace(/ /g, "-");
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

function appendLinks(parent, view, rows) {
	appendLimited(parent, rows.length, (index, into) => {
		const row = rows[index];
		const a = el("a", "person-link", row.name);
		a.href = `/library#${view}/${row.id}`;
		a.onclick = (event) => {
			event.preventDefault();
			showRow(view, row.id).catch((e) => showError(e.message));
		};
		into.appendChild(a);
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
		for (const box of [$("cards"), $("library-cards")]) {
			box.classList.toggle(`layout-${name}`, name === layout);
		}
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
const MAPPED = new Set(["museums", "organizations", "places"]);
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
	} else if (kind === "cover") {
		// a book, film or album without a cover gets a blank one that says so, laid
		// out in every layout like a real cover
		card.classList.add("has-image", "is-cover");
		const slot = el("div", "world-image cover-slot");
		const blank = el("div", "cover-blank");
		blank.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 4h5v8l-2.5-1.5L6 12V4z"/></svg>';
		blank.appendChild(el("span", null, "No cover"));
		slot.appendChild(blank);
		card.appendChild(slot);
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
	// where it was: a link to the place on the Places page
	linksDetail(list, "Where", "places", item.place ? [{ id: item.place.id, name: placeName(item.place) }] : []);
	// a show named after its one performer does not repeat the name
	const performers = item.performers.length === 1 && item.performers[0].name === item.name ? [] : item.performers;
	linksDetail(list, "Groups", "groups", item.groups);
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

// "Tmuna Theater, Tel-Aviv": a place's name with its city, when it has one
function placeName(place) {
	return [place.name, place.city].filter(Boolean).join(", ");
}

function placeCard(item) {
	const { card, list } = cardShell(item, [item.city, item.country].filter(Boolean).join(", "));
	card.appendChild(placeButton(item));
	detail(list, "Address", item.address);
	// how many concerts were there, always shown (0 too), then which
	detail(list, "Concerts", String(item.concerts.length));
	linksDetail(list, "Seen there", "concerts", item.concerts);
	detail(list, "Remark", item.remark);
	websiteDetail(list, item.website);
	return card;
}

function groupCard(item) {
	const { card, list } = cardShell(item, item.description);
	// how many people are in it, always shown (0 too), then who they are
	detail(list, "Members", String(item.members.length));
	linksDetail(list, "Who", "people", item.members);
	linksDetail(list, "Performed at", "concerts", item.concerts);
	websiteDetail(list, item.website);
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
	// each with how they are linked: "Dana Cohen (Worked at)"
	linksDetail(list, "Who", "people", item.person_links.map((link) => ({ id: link.person.id, name: link.name })));
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

// 3725 -> "1:02:05", 391 -> "6:31"
function formatDuration(seconds) {
	if (seconds === null) {
		return "";
	}
	const [h, m, s] = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
	const two = (n) => String(n).padStart(2, "0");
	return h ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

function youtubeCard(item) {
	// YouTube's own thumbnail (a grey one when the video is gone); one YouTube
	// no longer has may have no name: it goes by its id
	const shown = {
		...item,
		name: item.name || `Unavailable video ${item.youtube_id}`,
		image: `https://i.ytimg.com/vi/${item.youtube_id}/hqdefault.jpg`,
	};
	const { card, list } = cardShell(shown, item.channel);
	// the dialog edits the row as it is, with no name made up for it
	editable(card, item);
	if (item.unavailable) {
		detail(list, "Status", "No longer on YouTube");
	}
	detail(list, "Watched", formatDate(item));
	detail(list, "Category", item.category);
	detail(list, "Length", formatDuration(item.duration));
	detail(list, "Uploaded", item.uploaded);
	if (item.views !== null) {
		detail(list, "Views", item.views.toLocaleString());
	}
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
	detail(list, "Where", item.watched_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	websiteDetail(list, `https://www.youtube.com/watch?v=${item.youtube_id}`);
	return card;
}

const CARDS = { concerts: concertCard, museums: museumCard, "audio-courses": audioCourseCard, youtube: youtubeCard, places: placeCard, groups: groupCard, organizations: organizationCard };

// Material "link"
const LINK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>';

// Everything that ties a person to the user, grouped, each entry a link to its card.
async function showConnections(person) {
	const [concerts, museums, courses, books, bands] = await Promise.all([
		worldList("concerts"), worldList("museums"), worldList("audio-courses"), api("/api/library-entries?kind=book"), worldList("groups"),
	]);
	const has = (list) => list.some((p) => p.id === person.id);
	// a book is known by its work: #book/<work id>
	const wrote = books.filter((b) => has(b.authors)).map((b) => ({ id: b.work_id, name: b.title }));
	const groups = [
		["Concerts you went to together", "concerts", concerts.filter((c) => has(c.people))],
		["Concerts they performed at", "concerts", concerts.filter((c) => has(c.performers))],
		["Museums you visited together", "museums", museums.filter((m) => has(m.people))],
		["Audio courses they taught", "audio-courses", courses.filter((c) => has(c.lecturers))],
		["Books they wrote", "book", wrote],
		["Groups they are in", "groups", bands.filter((g) => has(g.members))],
		// how they are related to other people, both ways; each links to the other person
		["Related people", "people", [...person.relations, ...person.related].map((r) => ({ id: r.person.id, name: r.name }))],
		["Organizations", "organizations", person.organization_links.map((link) => ({ id: link.organization.id, name: link.name }))],
	].filter(([, , items]) => items.length > 0);
	$("connections-title").textContent = person.name;
	const body = $("connections-body");
	body.replaceChildren();
	if (groups.length === 0) {
		body.appendChild(el("p", "empty", "No concerts, museums, courses, books, groups or organizations link you yet."));
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
	appendKindLinks(organizations, "organizations", person.organization_links, "organization");
	const relations = el("td");
	appendRelations(relations, person);
	const links = el("td", "actions");
	const button = el("button", "icon-button");
	button.type = "button";
	button.title = `How you are connected to ${person.name}`;
	button.setAttribute("aria-label", button.title);
	button.innerHTML = LINK_ICON;
	button.onclick = () => showConnections(person).catch((e) => showError(e.message));
	links.appendChild(button);
	tr.append(el("td", "title", person.honorific), el("td", "title", person.first_name), el("td", "title", person.middle_name), el("td", "title", person.surname), kind, organizations, relations, el("td", null, person.description), links);
	editable(tr, person);
	return tr;
}

// A row of an enumeration (organization, person and relation types), with how many rows are of it.
function typeRow(kind) {
	const tr = el("tr");
	tr.id = `${slug(state.view)}-${kind.id}`;
	tr.append(el("td", "title", kind.name), el("td", null, kind.description), el("td", "number", kind.count));
	editable(tr, kind);
	return tr;
}

// A person relation type, with how it reads the other way ("Mother of" / "Child of")
function personRelationTypeRow(kind) {
	const tr = el("tr");
	tr.id = `${slug(state.view)}-${kind.id}`;
	tr.append(el("td", "title", kind.name), el("td", "title", kind.inverse || kind.name), el("td", null, kind.description), el("td", "number", kind.count));
	editable(tr, kind);
	return tr;
}

// Links of a kind, each to a row of a view: "Mother of Dana, Child of Ruth", "Worked at Schema"
function appendKindLinks(parent, view, links, field) {
	appendLimited(parent, links.length, (index, into) => {
		const link = links[index];
		const tie = el("span", "nowrap", `${link.type} `);
		appendLinks(tie, view, [link[field]]);
		into.appendChild(tie);
	});
}

// A person's relations to other people, both ways
function appendRelations(parent, person) {
	appendKindLinks(parent, "people", [...person.relations, ...person.related], "person");
}

// views shown as a table rather than cards: view -> [table id, tbody id, row maker]
const TABLES = {
	people: ["people", "people-rows", personRow],
	"organization-types": ["types", "type-rows", typeRow],
	"person-types": ["person-types-table", "person-type-rows", typeRow],
	"relation-types": ["relation-types-table", "relation-type-rows", typeRow],
	"person-relation-types": ["person-relation-types-table", "person-relation-type-rows", personRelationTypeRow],
	"person-organization-types": ["person-organization-types-table", "person-organization-type-rows", typeRow],
	devices: ["devices-table", "device-rows", typeRow],
};

// The filter next to the search, in groups. On a view whose rows have a
// type (people, organizations) one group picks types; on a library kind
// one picks statuses (Done, Want to, ...) and one whether it has a cover.
// Kept per view as a set of "group:value" ("type:none" for the rows without
// a type), empty for everything. A row matches when, in every group with
// something picked, it has one of the picked values.
const typeFilters = {};

function pickedTypes(view) {
	if (!typeFilters[view]) {
		typeFilters[view] = new Set();
	}
	return typeFilters[view];
}

// What a view is filtered by: what the button says with nothing picked, and
// its groups ({key, heading, options: [{value, name, count}]}). Null: nothing to filter by.
async function filterSpec(view) {
	if (TYPED[view]) {
		const types = await worldList(TYPED[view]);
		const options = types.map((t) => ({ value: String(t.id), name: t.name, count: t.count }));
		return { all: "All types", groups: [{ key: "type", heading: "", options: [...options, { value: "none", name: "No type", count: null }] }] };
	}
	if (state.config.kinds[view]) {
		const count = (test) => state.entries.filter(test).length;
		const statuses = Object.entries(state.config.statuses).map(([value, name]) => ({ value, name, count: count((e) => e.status === value) }));
		const covers = [
			{ value: "yes", name: "With a cover", count: count((e) => e.image) },
			{ value: "no", name: "No cover", count: count((e) => !e.image) },
		];
		return {
			all: `All ${state.config.kinds[view].plural.toLowerCase()}`,
			groups: [{ key: "status", heading: "Status", options: statuses }, { key: "cover", heading: "Cover", options: covers }],
		};
	}
	return null;
}

// a row's values in a filter group
function filterValues(group, item) {
	if (group === "status") {
		return [item.status];
	}
	if (group === "cover") {
		return [item.image ? "yes" : "no"];
	}
	// a person has a list of types, an organization one
	const types = item.types || (item.type ? [item.type] : []);
	return types.length ? types.map((t) => String(t.id)) : ["none"];
}

// The button names what is picked: "All types", the names, or how many.
function typeFilterLabel(view, spec) {
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return spec.all;
	}
	const names = spec.groups.flatMap((group) => group.options.filter((o) => picked.has(`${group.key}:${o.value}`)).map((o) => o.name));
	return names.length <= 2 ? names.join(", ") : `${names.length} picked`;
}

async function fillTypeFilter(view) {
	const button = $("type-filter");
	const menu = $("type-filter-menu");
	const spec = await filterSpec(view);
	menu.hidden = true;
	button.setAttribute("aria-expanded", "false");
	// a view with nothing to filter by keeps the control, disabled
	button.disabled = !spec;
	if (!spec) {
		button.textContent = "All types";
		menu.replaceChildren();
		return;
	}
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
			button.textContent = typeFilterLabel(view, spec);
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
		button.textContent = typeFilterLabel(view, spec);
		rerender();
	};
	menu.replaceChildren(
		...spec.groups.flatMap((group) => [
			...(group.heading ? [el("span", "type-filter-heading", group.heading)] : []),
			...group.options.map((o) => box(`${group.key}:${o.value}`, o.count === null ? o.name : `${o.name} (${o.count})`)),
		]),
		clear,
	);
	button.textContent = typeFilterLabel(view, spec);
}

// the filter groups a view has, by key
const FILTER_GROUPS = { type: (view) => Boolean(TYPED[view]), status: (view) => view in state.config.kinds, cover: (view) => view in state.config.kinds };

function typeMatches(item) {
	const view = state.view;
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return true;
	}
	// within a group any picked value will do; every group with a pick must match
	return Object.entries(FILTER_GROUPS).every(([group, applies]) => {
		if (!applies(view)) {
			return true;
		}
		const wanted = [...picked].filter((value) => value.startsWith(`${group}:`));
		return wanted.length === 0 || filterValues(group, item).some((value) => wanted.includes(`${group}:${value}`));
	});
}

// Everything a search can match on, as one lowercase string.
// what a row is searched by, worked out once per row: there can be 30,000 of them
const haystacks = new WeakMap();

function haystack(item) {
	if (!haystacks.has(item)) {
		haystacks.set(item, buildHaystack(item));
	}
	return haystacks.get(item);
}

function buildHaystack(item) {
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

// ─── pages: every list (cards, tables, books) a page at a time ──────────────

const PAGE_SIZES = [25, 50, 100, 200];
const PAGE_SIZE_KEY = "myworld.page-size";
// key: what the list on screen is (view, search, sort, filter, layout): a new one starts at the first page
const paging = { key: "", page: 0, size: savedPageSize(), shown: [] };

function savedPageSize() {
	try {
		const saved = Number(window.localStorage.getItem(PAGE_SIZE_KEY));
		return PAGE_SIZES.includes(saved) ? saved : 50;
	} catch (e) {
		return 50;
	}
}

// The rows of the page on screen out of shown (the whole list, filtered and sorted), and the pager set for it;
// a list that is not paged (the map shows everything) gets them all, with the pager disabled.
function pageOf(shown, key, paged = true) {
	if (key !== paging.key) {
		paging.key = key;
		paging.page = 0;
	}
	paging.shown = shown;
	const pages = Math.max(1, Math.ceil(shown.length / paging.size));
	paging.page = Math.min(paging.page, pages - 1);
	const on = paged && pages > 1;
	$("page-first").disabled = !on || paging.page === 0;
	$("page-previous").disabled = !on || paging.page === 0;
	$("page-next").disabled = !on || paging.page === pages - 1;
	$("page-last").disabled = !on || paging.page === pages - 1;
	$("page-size").disabled = !paged || shown.length <= PAGE_SIZES[0];
	$("page-label").textContent = paged ? `Page ${(paging.page + 1).toLocaleString()} of ${pages.toLocaleString()}` : "All shown";
	if (!paged) {
		return shown;
	}
	return shown.slice(paging.page * paging.size, (paging.page + 1) * paging.size);
}

// the pager on a page that has no list (stats, checks, ...): there, disabled
function pagerOff() {
	for (const id of ["page-first", "page-previous", "page-next", "page-last", "page-size"]) {
		$(id).disabled = true;
	}
	$("page-label").textContent = "Page 1 of 1";
}

function goToPage(page) {
	paging.page = page;
	rerender();
	window.scrollTo(0, 0);
}

function setupPager() {
	$("page-size").replaceChildren(...PAGE_SIZES.map((size) => {
		const option = document.createElement("option");
		option.value = size;
		option.textContent = `${size} per page`;
		return option;
	}));
	$("page-size").value = paging.size;
	$("page-size").onchange = () => {
		// keep the first row on screen in view
		const first = paging.page * paging.size;
		paging.size = Number($("page-size").value);
		try {
			window.localStorage.setItem(PAGE_SIZE_KEY, String(paging.size));
		} catch (e) {
			// the size is then only for this visit
		}
		goToPage(Math.floor(first / paging.size));
	};
	$("page-first").onclick = () => goToPage(0);
	$("page-previous").onclick = () => goToPage(paging.page - 1);
	$("page-next").onclick = () => goToPage(paging.page + 1);
	$("page-last").onclick = () => goToPage(Math.ceil(paging.shown.length / paging.size) - 1);
}

function renderWorld() {
	const view = state.view;
	const items = worldCache[view] || [];
	const shown = rankBySearch(sortItems(items.filter((item) => typeMatches(item) && searchMatches(item))));
	const table = TABLES[view];
	const map = !table && showsMap();
	// a page at a time, but the map shows every place
	const page = pageOf(shown, listKey(view), !map);
	$("cards").hidden = Boolean(table) || map;
	$("cards").replaceChildren(...(table || map ? [] : page.map(CARDS[view])));
	$("world-map").hidden = !map;
	for (const [name, [tableId, rowsId, row]] of Object.entries(TABLES)) {
		$(tableId).hidden = name !== view || shown.length === 0;
		$(rowsId).replaceChildren(...(name === view ? page.map(row) : []));
	}
	// "Audio courses" -> "audio courses"; a name with capitals inside ("YouTube videos") stays
	const title = WORLDS[view][0].replace(/^My /, "");
	const what = /^.+[A-Z]/.test(title) ? title : title.toLowerCase();
	setCount(view, items.length);
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
	for (const a of document.querySelectorAll("#kinds a")) {
		const active = a.dataset.world ? a.dataset.world === state.view : a.dataset.kind === state.view;
		a.classList.toggle("active", active);
	}
	$("stats-link").classList.toggle("active", state.view === "stats");
	$("users-link").classList.toggle("active", state.view === "users");
	$("checks-link").classList.toggle("active", state.view === "checks");
	$("schema-link").classList.toggle("active", state.view === "schema");
}

// One of the page bodies: the library table, the cards and tables, the stats, the users, the checks.
function showSection(id) {
	for (const section of ["library-view", "world-view", "stats-view", "users-view", "checks-view", "schema-view"]) {
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
	const checks = await loadChecks();
	if (state.view === "checks") {
		$("world-count").textContent = `${checks.length} check${checks.length === 1 ? "" : "s"}`;
		$("checks-list").replaceChildren(...checkGroups(checks));
	}
}

// The checks there are (admins only), fetched once: the Checks page and each page's own checks use them.
let checksLoading = null;

function loadChecks() {
	if (!checksLoading) {
		checksLoading = api("/api/checks").catch((e) => {
			checksLoading = null;
			throw e;
		});
	}
	return checksLoading;
}

// The Checks page, a group per dataset (Books, Museums, ...): a heading with its own Run all, then its checks.
function checkGroups(checks) {
	const groups = [];
	for (const check of checks) {
		let group = groups.at(-1);
		if (!group || group.dataset.dataset !== check.dataset) {
			group = el("section", "check-group");
			group.dataset.dataset = check.dataset;
			const heading = el("h2", "schema-heading", check.dataset_name);
			const run = el("button", "text", "Run all");
			run.type = "button";
			const list = el("div", "checks");
			run.onclick = () => runChecks(list, run).catch((e) => showError(e.message));
			heading.appendChild(run);
			group.append(heading, list);
			groups.push(group);
		}
		group.querySelector(".checks").appendChild(checkCard(check));
	}
	return groups;
}

// ─── the checks of the page on screen ───────────────────────────────────────

// The views that have checks, once an admin's checks are loaded: the toolbar button is enabled on those.
let checkedViews = new Set();

function updateViewChecks() {
	const button = $("view-checks-button");
	const has = isAdmin() && checkedViews.has(state.view);
	button.disabled = !has;
	button.title = !isAdmin() ? "Only an admin can run the checks" : has ? "Run the checks of this page" : "This page has no checks";
	// the panel belongs to the page it was opened on
	const panel = $("view-checks");
	if (panel.dataset.view !== state.view) {
		panel.hidden = true;
		button.setAttribute("aria-expanded", "false");
	}
}

async function openViewChecks() {
	const view = state.view;
	const checks = (await loadChecks()).filter((check) => check.dataset === view);
	if (state.view !== view || checks.length === 0) {
		return;
	}
	const panel = $("view-checks");
	panel.dataset.view = view;
	$("view-checks-title").textContent = `Checks of ${checks[0].dataset_name}`;
	$("view-checks-list").replaceChildren(...checks.map(checkCard));
	panel.hidden = false;
	$("view-checks-button").setAttribute("aria-expanded", "true");
	await runChecks($("view-checks-list"), $("view-checks-run"));
}

function setupViewChecks() {
	$("view-checks-button").onclick = () => {
		if ($("view-checks").hidden) {
			openViewChecks().catch((e) => showError(e.message));
		} else {
			$("view-checks").hidden = true;
			$("view-checks-button").setAttribute("aria-expanded", "false");
		}
	};
	$("view-checks-run").onclick = () => runChecks($("view-checks-list"), $("view-checks-run")).catch((e) => showError(e.message));
	$("view-checks-close").onclick = () => {
		$("view-checks").hidden = true;
		$("view-checks-button").setAttribute("aria-expanded", "false");
	};
	if (isAdmin()) {
		loadChecks().then((checks) => {
			checkedViews = new Set(checks.map((check) => check.dataset));
			updateViewChecks();
		}).catch((e) => showError(e.message));
	}
	updateViewChecks();
}

// ─── the structure of the database ──────────────────────────────────────────

// Mermaid draws the diagram; loaded the first time the page is opened, like Leaflet
const MERMAID = ["https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js", "sha512-6a80OTZVmEJhqYJUmYd5z8yHUCDlYnj6q9XwB/gKOEyNQV/Q8u+XeSG59a2ZKFEHGTYzgfOQKYEBtrZV7vBr+Q=="];
let mermaidLoading = null;

function loadMermaid() {
	if (!mermaidLoading) {
		mermaidLoading = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			[script.src, script.integrity] = MERMAID;
			script.crossOrigin = "anonymous";
			script.onload = () => {
				const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
				// full size, scrolling in its box: shrunk to the page's width the names cannot be read
				window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral", er: { useMaxWidth: false } });
				resolve(window.mermaid);
			};
			script.onerror = () => {
				mermaidLoading = null;
				reject(new Error("The diagram library could not be loaded"));
			};
			document.head.appendChild(script);
		});
	}
	return mermaidLoading;
}

// The tables and how they point at each other, as a Mermaid ER diagram: each
// table with its keys only (the cards below have every column)
function schemaDiagram(tables) {
	const word = (text) => text.replace(/[^A-Za-z0-9_]/g, "_");
	const lines = ["erDiagram"];
	for (const table of tables) {
		const fks = new Set(table.foreign_keys.flatMap((fk) => fk.columns));
		const keys = table.columns.filter((c) => c.primary_key || fks.has(c.name));
		lines.push(`  ${word(table.name)} {`);
		for (const column of keys) {
			const marks = [column.primary_key ? "PK" : "", fks.has(column.name) ? "FK" : ""].filter(Boolean).join(", ");
			lines.push(`    ${word(column.type.split("(")[0])} ${word(column.name)} ${marks}`);
		}
		lines.push("  }");
	}
	for (const table of tables) {
		for (const fk of table.foreign_keys) {
			// many of this table to one of that; "zero or one" when the key may be empty
			const optional = fk.columns.some((name) => table.columns.find((c) => c.name === name)?.nullable);
			lines.push(`  ${word(table.name)} }o--${optional ? "o|" : "||"} ${word(fk.table)} : "${word(fk.columns.join(", "))}"`);
		}
	}
	return lines.join("\n");
}

function schemaCard(table) {
	const card = el("article", "schema-table");
	card.id = `schema-${table.name}`;
	const head = el("h3", "schema-name", table.name);
	head.appendChild(el("span", "schema-rows", ` ${table.rows.toLocaleString()} row${table.rows === 1 ? "" : "s"}`));
	card.appendChild(head);
	const columns = el("table", "entries schema-columns");
	const header = el("tr");
	for (const name of ["Column", "Type", "Empty", "Default", "Key"]) {
		header.appendChild(el("th", "", name));
	}
	columns.appendChild(el("thead")).appendChild(header);
	const body = columns.appendChild(el("tbody"));
	const fkOf = new Map(table.foreign_keys.flatMap((fk) => fk.columns.map((c, i) => [c, `${fk.table}.${fk.referred[i]}`])));
	for (const column of table.columns) {
		const row = el("tr");
		const key = [column.primary_key ? "primary" : "", fkOf.has(column.name) ? `\u2192 ${fkOf.get(column.name)}` : ""].filter(Boolean).join(", ");
		for (const value of [column.name, column.type, column.nullable ? "yes" : "no", column.default, key]) {
			row.appendChild(el("td", "", value));
		}
		if (table.only_in_database.includes(column.name)) {
			row.classList.add("drift");
			row.title = "In the database but not in the code's model";
		}
		body.appendChild(row);
	}
	card.appendChild(columns);
	const facts = el("ul", "schema-facts");
	for (const fk of table.foreign_keys) {
		facts.appendChild(el("li", "", `Foreign key ${fk.columns.join(", ")} \u2192 ${fk.table} (${fk.referred.join(", ")})${fk.on_delete ? `, on delete ${fk.on_delete.toLowerCase()}` : ""}`));
	}
	for (const unique of table.unique) {
		facts.appendChild(el("li", "", `Unique ${unique.columns.join(", ")}${unique.name ? ` (${unique.name})` : ""}`));
	}
	for (const index of table.indexes) {
		facts.appendChild(el("li", "", `${index.unique ? "Unique index" : "Index"} ${index.name} on ${index.columns.join(", ")}`));
	}
	for (const check of table.checks) {
		facts.appendChild(el("li", "", `Check ${check.name}: ${check.sql}`));
	}
	if (facts.children.length) {
		card.appendChild(facts);
	}
	return card;
}

async function selectSchema() {
	state.view = "schema";
	navigate("schema");
	document.title = "Schema - My World";
	showSection("schema-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("schema");
	updateTools();
	$("world-count").textContent = "";
	const schema = await api("/api/schema");
	if (state.view !== "schema") {
		return;
	}
	const rows = schema.tables.reduce((sum, t) => sum + t.rows, 0);
	$("world-count").textContent = `${schema.tables.length} tables`;
	$("schema-summary").textContent = `Read from the database itself (${schema.dialect} ${schema.server_version}): ${schema.tables.length} tables, ${rows.toLocaleString()} rows in all.`;
	// where the database and the code's models differ: a migration still to run, or one that left something behind
	const drift = [
		...schema.missing.map((name) => `Table ${name} is in the code but not in the database (the app makes it when it starts)`),
		...schema.tables.filter((t) => !t.in_model).map((t) => `Table ${t.name} is in the database but not in the code`),
		...schema.tables.flatMap((t) => t.only_in_model.map((c) => `Column ${t.name}.${c} is in the code but not in the database: run scripts/migrate.sh`)),
		...schema.tables.flatMap((t) => t.only_in_database.map((c) => `Column ${t.name}.${c} is in the database but not in the code`)),
	];
	$("schema-drift").replaceChildren(...drift.map((text) => el("li", "", text)));
	$("schema-drift").hidden = drift.length === 0;
	$("schema-tables").replaceChildren(...schema.tables.map(schemaCard));
	const diagram = $("schema-diagram");
	diagram.textContent = "Drawing\u2026";
	try {
		const mermaid = await loadMermaid();
		const { svg } = await mermaid.render("schema-diagram-svg", schemaDiagram(schema.tables));
		diagram.innerHTML = svg;
	} catch (e) {
		diagram.textContent = e.message;
	}
}

// One check: what it looks at, a button to run it, and the last result under it.
// One row per check, all the same height: the name (what it checks in full
// is its tooltip), the result once run, and Run. A failing check's problems
// are under a closed disclosure, so a long list does not push the rest away.
function checkCard(check) {
	const card = el("div", "check");
	card.dataset.check = check.name;
	// on or off for this admin, saved in the database: Run all skips one that is off
	const enabled = document.createElement("input");
	enabled.type = "checkbox";
	enabled.className = "check-enabled";
	enabled.setAttribute("aria-label", `Run ${check.title} with Run all`);
	const title = el("span", "check-title", check.title);
	title.title = check.description;
	const run = el("button", "text check-run", "Run");
	run.type = "button";
	run.onclick = () => runCheck(card).catch((e) => showError(e.message));
	const show = () => {
		enabled.checked = check.enabled;
		enabled.title = check.enabled ? "On: Run all runs it. Untick to turn it off" : "Off: Run all skips it. Tick to turn it on";
		card.classList.toggle("check-off", !check.enabled);
		run.disabled = !check.enabled;
		card.dataset.enabled = String(check.enabled);
	};
	enabled.onchange = async () => {
		const on = enabled.checked;
		enabled.disabled = true;
		try {
			await api(`/api/disabled-checks/${check.name}`, { method: on ? "DELETE" : "PUT" });
			check.enabled = on;
			// the same check may be on the Checks page and in a page's own checks
			for (const other of document.querySelectorAll(`.check[data-check="${check.name}"]`)) {
				other.dispatchEvent(new Event("check-toggled"));
			}
		} catch (e) {
			showError(e.message);
		} finally {
			enabled.disabled = false;
			show();
		}
	};
	card.addEventListener("check-toggled", show);
	card.append(enabled, title, el("span", "check-result"), run);
	show();
	if (!check.enabled) {
		card.querySelector(".check-result").textContent = "Off";
	}
	return card;
}

// What a problem is about: a link to the row when it has a place in the app
// and is the viewer's own (the app opens only those), plain text otherwise.
function problemSubject(problem) {
	const match = problem.link.match(/^([a-z-]+)\/(\d+)$/);
	if (!match || problem.owner !== state.config.user.id || !(match[1] in WORLDS || match[1] in state.config.kinds)) {
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
	const button = card.querySelector(".check-run");
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
			// the server sends the first few hundred of a long list
			const count = result.problem_count;
			if (count > result.problems.length) {
				list.appendChild(el("li", "check-more", `and ${(count - result.problems.length).toLocaleString()} more`));
			}
			const toggle = el("button", "text check-toggle", `${count.toLocaleString()} problem${count === 1 ? "" : "s"} in ${result.checked.toLocaleString()} ${result.noun}`);
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

// Run every check under box in turn, its Run all button disabled meanwhile.
async function runChecks(box, button) {
	button.disabled = true;
	try {
		for (const card of box.querySelectorAll(".check")) {
			// one turned off is skipped, and says so
			if (card.dataset.enabled === "false") {
				card.querySelector(".check-details")?.remove();
				const out = card.querySelector(".check-result");
				out.className = "check-result";
				out.textContent = "Off";
				continue;
			}
			await runCheck(card);
		}
	} finally {
		button.disabled = false;
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
		statTile("YouTube videos", stats.youtube_videos, "", "youtube"),
		statTile("Places", stats.places, "", "places"),
		statTile("People", stats.people, "", "people"),
		statTile("Groups", stats.groups, "", "groups"),
		statTile("Organizations", stats.organizations, "", "organizations"),
		statTile("Organization types", stats.organization_types, "", "organization-types"),
		statTile("Professions", stats.person_types, "", "person-types"),
		statTile("Org relation types", stats.relation_types, "", "relation-types"),
		statTile("Person relation types", stats.person_relation_types, "", "person-relation-types"),
		statTile("Person-org relation types", stats.person_organization_types, "", "person-organization-types"),
		statTile("Devices", stats.devices, "", "devices"),
		statTile("Photos and logos", stats.images, "", null),
	);
	const charts = el("div", "stat-charts");
	charts.append(
		barChart("People by profession (one with several counts in each)", stats.people_by_type),
		barChart("Organizations by type", stats.organizations_by_type),
		barChart("Organizations by relation (one with several relations counts in each)", stats.organizations_by_relation),
		yearChart("Concerts per year", stats.concerts_by_year, "concerts"),
		yearChart("Museum visits per year", stats.museums_by_year, "visits"),
		barChart("YouTube videos by channel (the most watched)", stats.youtube_by_channel),
		barChart("YouTube videos by category", stats.youtube_by_category),
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
// Open one row of a view, or one entry of a library kind (id: its work), marked and scrolled to.
async function showRow(view, id) {
	if (view in state.config.kinds) {
		await selectKind(view, `${view}/${id}`);
		// a book on another page: go to its page
		const at = paging.shown.findIndex((entry) => entry.work_id === id);
		if (!$(`${view}-${id}`) && at >= 0) {
			paging.page = Math.floor(at / paging.size);
			renderEntries();
		}
		markRow($(`${view}-${id}`));
		return;
	}
	await selectWorld(view, `${view}/${id}`);
	// a row on another page: go to its page
	const at = paging.shown.findIndex((item) => item.id === id);
	if (!$(`${slug(view)}-${id}`) && at >= 0) {
		paging.page = Math.floor(at / paging.size);
		renderWorld();
	}
	markRow($(`${slug(view)}-${id}`));
}

function markRow(row) {
	if (!row) {
		return;
	}
	for (const old of document.querySelectorAll(".highlight")) {
		old.classList.remove("highlight");
	}
	row.classList.add("highlight");
	row.scrollIntoView({ block: "center" });
}

function setupWorlds() {
	$("stats-link").onclick = (event) => {
		event.preventDefault();
		closeSidebarOnPhone();
		selectStats().catch((e) => showError(e.message));
	};
	// the admin pages: for everyone else the links stay, disabled
	for (const [id, select, title] of [
		["users-link", selectUsers, "Only an admin can see the accounts"],
		["checks-link", selectChecks, "Only an admin can run the checks"],
		["schema-link", selectSchema, "Only an admin can see the structure of the database"],
	]) {
		const link = $(id);
		if (!isAdmin()) {
			link.setAttribute("aria-disabled", "true");
			link.tabIndex = -1;
			link.title = title;
		}
		link.onclick = (event) => {
			event.preventDefault();
			closeSidebarOnPhone();
			if (isAdmin()) {
				select().catch((e) => showError(e.message));
			}
		};
	}
	$("checks-run-all").onclick = () => runChecks($("checks-list"), $("checks-run-all")).catch((e) => showError(e.message));
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
const DIALOG_FORMS = ["add-form", "concert-form", "museum-form", "audio-course-form", "youtube-video-form", "place-form", "person-form", "group-form", "organization-form", "organization-type-form", "profession-form", "relation-type-form", "person-relation-type-form", "person-org-relation-type-form", "device-form"];
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

// ─── pickers over long lists: Tom Select (https://tom-select.js.org/) ───────

// The grey line under a person in a picker: their types and description,
// since two people may share a name. A person with no name is called by the
// description already, so it is not repeated.
function pickerNote(row) {
	if (!("first_name" in row)) {
		return "";
	}
	const named = row.first_name || row.middle_name || row.surname;
	return [row.is_self && "you", (row.types || []).map((t) => t.name).join("/"), named && row.description?.slice(0, 60)].filter(Boolean).join(" · ");
}

// lists this long or shorter open on focus; longer ones only once something is typed
const PICKER_OPEN_ON_FOCUS = 15;

// A picker on a select: only rows that exist can be picked, the best few
// matches of what is typed are offered (a name before a note), and a
// multiple select gives removable chips.
function makePicker(select, onChange) {
	const multiple = select.multiple;
	return new TomSelect(select, {
		maxItems: multiple ? null : 1,
		placeholder: select.dataset.placeholder,
		maxOptions: 8,
		// the rows are all in memory: filter on every key, so Enter right after typing picks from what was typed
		refreshThrottle: 0,
		create: false,
		hideSelected: true,
		closeAfterSelect: !multiple,
		searchField: [{ field: "text", weight: 2 }, { field: "sub", weight: 0.5 }],
		plugins: multiple ? ["remove_button"] : ["clear_button"],
		render: {
			option: (data, esc) => `<div class="picker-option"><span>${esc(data.text)}</span>${data.sub ? `<small>${esc(data.sub)}</small>` : ""}</div>`,
			item: (data, esc) => `<div>${esc(data.text)}</div>`,
			no_results: (data, esc) => `<div class="no-results">No one matches “${esc(data.input)}”</div>`,
		},
		onChange: () => onChange?.(),
	});
}

// What a picker offers: rows of a view, by name (or label), each with its note
function setPickerRows(select, rows, label = (row) => row.name) {
	const picker = select.tomselect;
	picker.clear(true);
	picker.clearOptions();
	picker.addOptions(rows.map((row) => ({ value: String(row.id), text: label(row), sub: pickerNote(row) })));
	picker.settings.openOnFocus = rows.length <= PICKER_OPEN_ON_FOCUS;
	picker.refreshOptions(false);
}

function setPickerValue(select, ids) {
	select.tomselect.setValue(ids.map(String), true);
}

// "I went alone" and the With picker exclude each other: with people chosen the
// box is disabled, and with the box ticked the picker is.
function syncAlone(form) {
	const alone = form?.elements.alone;
	if (!alone) {
		return;
	}
	const picker = form.querySelector("[data-field=people]").tomselect;
	alone.disabled = picker.items.length > 0;
	if (alone.checked) {
		picker.disable();
	} else {
		picker.enable();
	}
}

// ─── a person's links, in the person form: to people and to organizations ──

// A list of links of the person being edited, each a kind and a row of a view
// ("Mother of" Dana, "Worked at" Schema), shown as removable chips; a row
// picked in the picker is added with the kind chosen beside it.
// field names the row in each link ("person", "organization").
const editingLinks = { relations: [], organization_links: [] };

function renderLinks(key, boxId, field) {
	const box = $(boxId);
	box.replaceChildren();
	if (editingLinks[key].length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingLinks[key].forEach((link, index) => {
		const chip = el("span", "chip", `${link.type} ${link[field].name}`);
		const remove = el("button", "chip-remove", "\u00d7");
		remove.type = "button";
		remove.setAttribute("aria-label", `Remove ${link.type} ${link[field].name}`);
		remove.onclick = () => {
			editingLinks[key].splice(index, 1);
			renderLinks(key, boxId, field);
		};
		chip.appendChild(remove);
		box.appendChild(chip);
	});
}

async function prepareLinks({ key, boxId, kindId, pickerId, kindsView, rowsView, field, current, exclude = null, label = (row) => row.name }) {
	const [kinds, rows] = await Promise.all([worldList(kindsView), worldList(rowsView)]);
	editingLinks[key] = (current || []).map((link) => ({ ...link }));
	$(kindId).replaceChildren(...kinds.map((k) => {
		const option = document.createElement("option");
		option.value = k.id;
		option.textContent = k.name;
		return option;
	}));
	const offered = rows.filter((row) => row.id !== exclude);
	const select = $(pickerId);
	setPickerRows(select, offered, label);
	const picker = select.tomselect;
	if (kinds.length) {
		picker.enable();
	} else {
		picker.disable();
	}
	picker.off("change");
	picker.on("change", (value) => {
		const row = offered.find((r) => String(r.id) === value);
		const kind = kinds.find((k) => String(k.id) === $(kindId).value);
		if (!row || !kind) {
			return;
		}
		if (!editingLinks[key].some((link) => link.type_id === kind.id && link[field].id === row.id)) {
			editingLinks[key].push({ type_id: kind.id, type: kind.name, [field]: { id: row.id, name: row.name } });
		}
		picker.clear(true);
		renderLinks(key, boxId, field);
	});
	renderLinks(key, boxId, field);
}

// The person form's two link editors: relations to people (never to oneself) and links to organizations
async function preparePersonLinks(item) {
	await prepareLinks({
		key: "relations", boxId: "person-relations", kindId: "relation-type", pickerId: "relation-person",
		kindsView: "person-relation-types", rowsView: "people", field: "person", current: item?.relations, exclude: item?.id,
	});
	await prepareLinks({
		key: "organization_links", boxId: "person-organization-links", kindId: "organization-link-type", pickerId: "organization-link-organization",
		kindsView: "person-organization-types", rowsView: "organizations", field: "organization", current: item?.organization_links,
	});
}

// The date pickers of a form, from the date in their hidden field (YYYY,
// YYYY-MM, YYYY-MM-DD or a timestamp): the picker always holds a real day,
// and the precision says how much of it is known.
function syncDatePicks(form) {
	for (const box of form.querySelectorAll(".date-pick")) {
		const value = box.querySelector("input[type=hidden]").value;
		const [year, month, day] = value.split(/[-T]/);
		box.dataset.original = value;
		box.querySelector(".date-precision").value = !value || day ? "day" : month ? "month" : "year";
		box.querySelector(".date-day").value = value ? `${year}-${month || "01"}-${day || "01"}` : "";
	}
}

// Picking a day, or changing how much of it is known, writes the hidden
// field: only ever a legal date. A date left as it was keeps its time.
function setupDatePicks() {
	for (const box of document.querySelectorAll(".date-pick")) {
		const hidden = box.querySelector("input[type=hidden]");
		const picker = box.querySelector(".date-day");
		const precision = box.querySelector(".date-precision");
		const update = () => {
			const [year, month] = picker.value.split("-");
			const value = !picker.value ? "" : { year, month: `${year}-${month}`, day: picker.value }[precision.value];
			hidden.value = value && value === box.dataset.original?.slice(0, 10) ? box.dataset.original : value;
		};
		picker.addEventListener("input", update);
		precision.addEventListener("change", update);
	}
}

function resetForm(form) {
	form.reset();
	for (const select of form.querySelectorAll("[data-chips]")) {
		select.tomselect.clear(true);
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
	return form.querySelector(`[data-field=${field}]`).tomselect.getValue().map(Number);
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
	youtube: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			youtube_id: value("youtube_id"),
			name: value("name"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			review: value("review"),
			device_id: value("device_id"),
			watched_at: value("watched_at"),
		};
	},
	concerts: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			event: value("event"),
			performers: chosen(form, "performers"),
			groups: chosen(form, "groups"),
			genre: value("genre"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			place_id: value("place_id"),
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
	groups: async (form) => ({
		name: form.elements.name.value,
		members: chosen(form, "members"),
		description: form.elements.description.value,
		website: form.elements.website.value,
	}),
	places: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			city: value("city"),
			country: value("country"),
			address: value("address"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			website: value("website"),
			remark: value("remark"),
		};
	},
	people: async (form) => ({
		honorific: form.elements.honorific.value,
		first_name: form.elements.first_name.value,
		middle_name: form.elements.middle_name.value,
		surname: form.elements.surname.value,
		type_ids: chosen(form, "types"),
		relations: editingLinks.relations.map((r) => ({ type_id: r.type_id, person_id: r.person.id })),
		organization_links: editingLinks.organization_links.map((l) => ({ type_id: l.type_id, organization_id: l.organization.id })),
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
	"person-organization-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"person-relation-types": async (form) => ({
		name: form.elements.name.value,
		inverse: form.elements.inverse.value,
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
	for (const select of form.querySelectorAll("[data-chips]")) {
		setPickerValue(select, item[select.dataset.field].map((row) => row.id));
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
	form.elements.photo.value = "";
	for (const name of MOVIE_FIELDS) {
		form.elements[name].readOnly = Boolean(entry);
	}
}

// The organization dialog's type list: the user's own organization types, and "none".
async function fillTypes(select, typesView, label = (t) => t.name) {
	const types = await worldList(typesView);
	const none = document.createElement("option");
	none.value = "";
	none.textContent = "(none)";
	select.replaceChildren(none, ...types.map((t) => {
		const option = document.createElement("option");
		option.value = t.id;
		option.textContent = label(t);
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
		for (const select of form.querySelectorAll("[data-chips]")) {
			setPickerRows(select, await worldList(select.dataset.chips));
		}
		if (form.elements.type_id) {
			await fillTypes(form.elements.type_id, TYPED[state.view]);
		}
		if (form.elements.device_id) {
			await fillTypes(form.elements.device_id, "devices");
		}
		if (form.elements.place_id) {
			setPickerRows(form.elements.place_id, await worldList("places"), placeName);
		}
		resetForm(form);
		if (state.view === "organizations" && !item) {
			const company = worldCache["organization-types"].find((t) => t.name === "Company");
			form.elements.type_id.value = company ? company.id : "";
		}
		if (item) {
			fillWorldForm(form, item);
		}
		syncDatePicks(form);
		if (form.elements.device_id) {
			form.elements.device_id.value = item?.device ? item.device.id : "";
		}
		if (form.elements.place_id) {
			setPickerValue(form.elements.place_id, item?.place ? [item.place.id] : []);
		}
		if (form.id === "person-form") {
			await preparePersonLinks(item);
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
		await api(`/api/library-entries/${state.editing.work_id}`, { method: "DELETE" });
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
	for (const select of dialog.querySelectorAll("[data-chips]")) {
		makePicker(select, () => syncAlone(select.closest("form")));
	}
	for (const select of dialog.querySelectorAll("[data-picker], #relation-person, #organization-link-organization")) {
		makePicker(select);
	}
	// In a picker, Escape closes its list and Enter picks the highlighted row;
	// neither ever closes the dialog or saves the form, even when the list has
	// already closed by itself (the edits would be lost, or saved half done)
	dialog.addEventListener("keydown", (event) => {
		if ((event.key === "Escape" || event.key === "Enter") && event.target.closest?.(".ts-wrapper")) {
			event.preventDefault();
		}
	}, true);
	$("museum-form").elements.alone.onchange = () => syncAlone($("museum-form"));
	const { rating_min, rating_max } = state.config;
	$("museum-form").elements.rating.min = rating_min;
	$("museum-form").elements.rating.max = rating_max;
	$("audio-course-form").elements.rating.min = rating_min;
	$("audio-course-form").elements.rating.max = rating_max;
	$("youtube-video-form").elements.rating.min = rating_min;
	$("youtube-video-form").elements.rating.max = rating_max;
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
