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

async function showBuild() {
	try {
		const info = await api("/app/version");
		$("build").textContent = `build ${info.git_describe} (${info.revision})`;
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
	const { plural } = state.config.kinds[state.kind];
	$("rows").replaceChildren(...state.entries.map(renderRow));
	$("entries").hidden = state.entries.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add one with the + button.`;
}

async function selectKind(kind) {
	state.kind = kind;
	state.view = kind;
	window.location.hash = kind;
	$("library-view").hidden = false;
	$("world-view").hidden = true;
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
	const linked = requested.match(/^(people|organizations|organization-types)\/(\d+)$/);
	if (linked) {
		await showRow(linked[1], Number(linked[2]));
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
};

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
	linksDetail(list, "People", "people", item.people);
	detail(list, "Remark", item.remark);
	websiteDetail(list, item.website);
	return card;
}

const CARDS = { concerts: concertCard, museums: museumCard, organizations: organizationCard };

function personRow(person) {
	const tr = el("tr");
	tr.id = `person-${person.id}`;
	const organizations = el("td");
	appendLinks(organizations, "organizations", person.organizations);
	tr.append(el("td", "title", person.name), organizations, el("td", null, person.description));
	editable(tr, person);
	return tr;
}

// The enumeration of what an organization can be, and how many are of each.
function typeRow(kind) {
	const tr = el("tr");
	tr.id = `organization-type-${kind.id}`;
	tr.append(el("td", "title", kind.name), el("td", null, kind.description), el("td", "number", kind.organizations));
	editable(tr, kind);
	return tr;
}

// views shown as a table rather than cards: view -> [table id, tbody id, row maker]
const TABLES = {
	people: ["people", "people-rows", personRow],
	"organization-types": ["types", "type-rows", typeRow],
};

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
	const words = $("world-search").value.toLowerCase().split(/\s+/).filter(Boolean);
	const shown = items.filter((item) => {
		const text = haystack(item);
		return words.every((w) => text.includes(w));
	});
	const table = TABLES[view];
	$("cards").hidden = Boolean(table);
	$("layouts").hidden = Boolean(table);
	$("cards").replaceChildren(...(table ? [] : shown.map(CARDS[view])));
	for (const [name, [tableId, rowsId, row]] of Object.entries(TABLES)) {
		$(tableId).hidden = name !== view || shown.length === 0;
		$(rowsId).replaceChildren(...(name === view ? shown.map(row) : []));
	}
	const what = WORLDS[view][0].replace(/^My /, "").toLowerCase();
	if (items.length === 0) {
		$("world-count").textContent = `Nothing here yet: no ${what} for this account.`;
	} else {
		$("world-count").textContent = shown.length === items.length ? `${items.length} ${what}` : `${shown.length} of ${items.length} ${what}`;
	}
}

function markActive() {
	for (const a of document.querySelectorAll(".kinds a")) {
		const active = a.dataset.world ? a.dataset.world === state.view : a.dataset.kind === state.view;
		a.classList.toggle("active", active);
	}
}

async function selectWorld(view) {
	state.view = view;
	window.location.hash = view;
	const [heading, path] = WORLDS[view];
	document.title = `${heading.replace(/^My /, "")} - My World`;
	$("library-view").hidden = true;
	$("world-view").hidden = false;
	markActive();
	showError("");
	$("world-search").value = "";
	if (!worldCache[view]) {
		$("world-count").textContent = "Loading...";
		$("cards").replaceChildren();
		$("people").hidden = true;
		worldCache[view] = await api(path);
	}
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
	$("world-search").oninput = renderWorld;
	setupLayouts();
}

// ─── the add dialog ─────────────────────────────────────────────────────────

// One dialog, opened by the + button, showing the form of whatever is on screen.
const DIALOG_FORMS = ["add-form", "concert-form", "museum-form", "person-form", "organization-form", "organization-type-form"];
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
	const pick = (quiet) => {
		const name = input.value.trim();
		if (!name) {
			return;
		}
		const view = box.dataset.chips;
		const person = (worldCache[view] || []).find((p) => p.name.toLowerCase() === name.toLowerCase());
		if (!person) {
			if (!quiet) {
				dialogError(`${name} is not in ${WORLDS[view][0]} yet: add it there first.`);
			}
			return;
		}
		dialogError("");
		addChip(box, person);
		input.value = "";
	};
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
	input.onblur = () => pick(true);
}

function resetForm(form) {
	form.reset();
	for (const box of form.querySelectorAll("[data-chips]")) {
		box.selected.clear();
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
		name: form.elements.name.value,
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
async function fillTypes(select) {
	const types = await worldList("organization-types");
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
				option.value = row.name;
				return option;
			}));
		}
		if (form.elements.type_id) {
			await fillTypes(form.elements.type_id);
		}
		resetForm(form);
		if (form.elements.type_id && !item) {
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
