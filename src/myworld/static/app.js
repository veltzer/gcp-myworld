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

const state = { config: null, kind: "book", entries: [] };

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

function renderRow(entry) {
	const { rating_min, rating_max } = state.config;
	const tr = document.createElement("tr");
	cell(tr, "title").textContent = entry.title;
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
		if (kind === state.kind) {
			a.className = "active";
		}
		a.onclick = (event) => {
			event.preventDefault();
			selectKind(kind);
		};
		nav.appendChild(a);
	}
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
	window.location.hash = kind;
	const { name, plural, creator } = state.config.kinds[kind];
	document.title = `${plural} - My World`;
	$("heading").textContent = `My ${plural}`;
	$("add-summary").textContent = `Add a ${name.toLowerCase()}`;
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
			form.elements.title.focus();
			await loadEntries();
		} catch (e) {
			showError(e.message);
		}
	};

	const requested = window.location.hash.slice(1);
	await selectKind(requested in state.config.kinds ? requested : "book");
}

// ─── entry point ────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
	showBuild();
	const page = document.body.dataset.page;
	const run = page === "library" ? libraryPage : indexPage;
	run().catch((e) => showError(e.message));
});
