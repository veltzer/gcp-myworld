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
const state = { config: null, kind: "book", view: "concerts", entries: [] };

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

function input(parent, name, type, value, extra = {}) {
	const el = document.createElement("input");
	el.name = name;
	el.type = type;
	el.value = value ?? "";
	Object.assign(el, extra);
	parent.appendChild(el);
	return el;
}

function entryPayload(row) {
	const value = (name) => row.querySelector(`[name="${name}"]`).value;
	return {
		status: value("status"),
		rating: value("rating"),
		started_on: value("started_on"),
		finished_on: value("finished_on"),
		notes: value("notes"),
	};
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

function renderRow(entry) {
	const { rating_min, rating_max } = state.config;
	const tr = document.createElement("tr");
	const title = cell(tr, "title");
	title.textContent = entry.title;
	const links = catalogLinks(entry);
	if (links) {
		title.appendChild(links);
	}
	cell(tr).textContent = entry.creator;
	cell(tr).textContent = entry.year ?? "";
	const status = document.createElement("select");
	status.name = "status";
	fillStatuses(status, entry.status);
	cell(tr).appendChild(status);
	input(cell(tr), "rating", "number", entry.rating, { min: rating_min, max: rating_max });
	input(cell(tr), "started_on", "date", entry.started_on);
	input(cell(tr), "finished_on", "date", entry.finished_on);
	input(cell(tr), "notes", "text", entry.notes);
	const actions = cell(tr, "actions");
	const save = document.createElement("button");
	save.type = "button";
	save.textContent = "Save";
	save.onclick = async () => {
		showError("");
		try {
			await api(`/api/library/${entry.work_id}`, { method: "PUT", body: entryPayload(tr) });
			await loadEntries();
		} catch (e) {
			showError(e.message);
		}
	};
	const remove = document.createElement("button");
	remove.type = "button";
	remove.className = "danger";
	remove.textContent = "Remove";
	remove.onclick = async () => {
		showError("");
		try {
			await api(`/api/library/${entry.work_id}`, { method: "DELETE" });
			await loadEntries();
		} catch (e) {
			showError(e.message);
		}
	};
	actions.append(save, " ", remove);
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
	markActive();
}

async function loadEntries() {
	state.entries = await api(`/api/library?kind=${encodeURIComponent(state.kind)}`);
	const { plural } = state.config.kinds[state.kind];
	$("rows").replaceChildren(...state.entries.map(renderRow));
	$("entries").hidden = state.entries.length === 0;
	$("empty").hidden = state.entries.length !== 0;
	$("empty").textContent = `No ${plural.toLowerCase()} yet. Add your first one above.`;
}

async function selectKind(kind) {
	state.kind = kind;
	state.view = kind;
	window.location.hash = kind;
	$("library-view").hidden = false;
	$("world-view").hidden = true;
	const { name, plural, creator } = state.config.kinds[kind];
	document.title = `${plural} - My World`;
	$("heading").textContent = `My ${plural}`;
	$("add-summary").textContent = `Add a ${name.toLowerCase()}`;
	$("creator-label").textContent = creator;
	$("creator-column").textContent = creator;
	renderKinds();
	showError("");
	const film = state.config.tmdb && kind === "film";
	$("movie-search").hidden = !film;
	$("movie-ids").hidden = !film;
	if (state.config.tmdb) {
		movieIdsReset();
	}
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
		showError("");
		const body = { kind: state.kind };
		for (const el of form.elements) {
			if (el.name) {
				body[el.name] = el.value;
			}
		}
		try {
			await api("/api/library", { method: "POST", body });
			form.elements.title.value = "";
			form.elements.creator.value = "";
			form.elements.year.value = "";
			form.elements.notes.value = "";
			movieIdsReset();
			$("movie-results").hidden = true;
			$("movie-hint").hidden = true;
			$("movie-query").value = "";
			form.elements.title.focus();
			await loadEntries();
		} catch (e) {
			showError(e.message);
		}
	};

	setupMovieSearch();
	setupWorlds();
	renderKinds();
	const requested = window.location.hash.slice(1);
	const person = requested.match(/^people\/(\d+)$/);
	if (person) {
		await showPerson(Number(person[1]));
	} else if (requested in state.config.kinds) {
		await selectKind(requested);
	} else {
		await selectWorld(requested in WORLDS ? requested : "concerts");
	}
}

// ─── concerts, museums, people ──────────────────────────────────────────────

// view -> [heading, API path]; the rows are the signed-in user's own, read-only
const WORLDS = {
	concerts: ["My Concerts", "/api/concerts"],
	museums: ["My Museums", "/api/museums"],
	people: ["People", "/api/people"],
};

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

// The people who were there, each a link to their row in the People view.
function peopleDetail(list, people) {
	if (people.length === 0) {
		return;
	}
	const li = el("li");
	li.appendChild(el("span", "label", "With"));
	people.forEach((person, index) => {
		if (index > 0) {
			li.append(", ");
		}
		const a = el("a", "person-link", person.name);
		a.href = `/library#people/${person.id}`;
		a.onclick = (event) => {
			event.preventDefault();
			showPerson(person.id).catch((e) => showError(e.message));
		};
		li.appendChild(a);
	});
	list.appendChild(li);
}

function cardShell(item, subtitle) {
	const card = el("article", "world-card");
	if (item.image) {
		const img = el("img", "world-image");
		img.src = item.image;
		img.alt = "";
		img.loading = "lazy";
		card.appendChild(img);
	} else {
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
	return { card, body, list };
}

function concertCard(item) {
	const { body, card, list } = cardShell(item, item.event);
	detail(list, "Date", formatDate(item));
	detail(list, "Where", [item.venue, item.city, item.country].filter(Boolean).join(", "));
	const performers = item.performers.length === 1 && item.performers[0] === item.name ? [] : item.performers;
	detail(list, "Performers", performers);
	detail(list, "Genre", item.genre);
	peopleDetail(list, item.people);
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
	peopleDetail(list, item.people);
	detail(list, "Tickets", item.tickets);
	detail(list, "Review", item.review);
	detail(list, "Remark", item.remark);
	if (item.url) {
		const li = el("li");
		const a = el("a", null, "Website");
		a.href = item.url;
		a.target = "_blank";
		a.rel = "noopener";
		li.appendChild(a);
		list.appendChild(li);
	}
	return card;
}

function outingList(outings) {
	const td = el("td", "outings");
	for (const outing of outings) {
		const date = formatDate(outing);
		td.appendChild(el("div", null, date ? `${outing.name} (${date})` : outing.name));
	}
	return td;
}

function personRow(person) {
	const tr = el("tr");
	tr.id = `person-${person.id}`;
	tr.append(
		el("td", "title", person.name),
		el("td", null, person.company),
		el("td", null, person.description),
		outingList(person.concerts),
		outingList(person.museums),
	);
	return tr;
}

// Everything a search can match on, as one lowercase string.
function haystack(item) {
	const values = [];
	for (const value of Object.values(item)) {
		if (typeof value === "string") {
			values.push(value);
		} else if (Array.isArray(value)) {
			values.push(...value.map((v) => (typeof v === "string" ? v : v.name)));
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
	const people = view === "people";
	$("cards").hidden = people;
	$("people").hidden = !people || shown.length === 0;
	if (people) {
		$("people-rows").replaceChildren(...shown.map(personRow));
		$("cards").replaceChildren();
	} else {
		$("cards").replaceChildren(...shown.map(view === "concerts" ? concertCard : museumCard));
		$("people-rows").replaceChildren();
	}
	if (items.length === 0) {
		$("world-count").textContent = `Nothing here yet: no ${view} have been imported for this account.`;
	} else {
		$("world-count").textContent = shown.length === items.length ? `${items.length} ${view}` : `${shown.length} of ${items.length} ${view}`;
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
	$("heading").textContent = heading;
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

// Open the People view at one person, scrolled to and highlighted.
async function showPerson(id) {
	await selectWorld("people");
	window.location.hash = `people/${id}`;
	const row = $(`person-${id}`);
	if (!row) {
		return;
	}
	for (const old of document.querySelectorAll("#people-rows tr.highlight")) {
		old.classList.remove("highlight");
	}
	row.classList.add("highlight");
	row.scrollIntoView({ block: "center" });
}

function setupWorlds() {
	for (const a of document.querySelectorAll("#worlds a")) {
		a.onclick = (event) => {
			event.preventDefault();
			selectWorld(a.dataset.world).catch((e) => showError(e.message));
		};
	}
	$("world-search").oninput = renderWorld;
}

// ─── entry point ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
	showBuild();
	const page = document.body.dataset.page;
	const run = page === "library" ? libraryPage : indexPage;
	run().catch((e) => showError(e.message));
});
