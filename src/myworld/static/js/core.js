// What every page uses: the API, the error line and the footer.

import { el } from "./worlds.js";

export const $ = (id) => document.getElementById(id);

// The user's theme (Settings): "light" or "dark" on <html>, nothing for "system" (the
// device's); kept in this browser too, so the next page is drawn in it from the start.
export function applyTheme(theme) {
	if (theme === "light" || theme === "dark") {
		document.documentElement.dataset.theme = theme;
	} else {
		delete document.documentElement.dataset.theme;
	}
	try {
		localStorage.setItem("theme", theme || "system");
	} catch {
		// no storage here: the server's choice is applied when each page loads
	}
}

// A view (doc/views.md), opened at /view/<username>/<name>: the page shows it read only, and asks
// the view's own endpoints what it would ask the library's. null on the library page itself.
export const VISIT = (() => {
	const match = window.location.pathname.match(/^\/view\/([^/]+)\/([^/]+)\/?$/);
	return match ? { username: decodeURIComponent(match[1]), name: decodeURIComponent(match[2]), base: `/api/views/${match[1]}/${match[2]}` } : null;
})();

// where an address-bar hash of this page leads: the library's, or the view's
export function pageHref(hash) {
	return `${VISIT ? window.location.pathname : "/library"}#${hash}`;
}

// a library API path as a view's visitor reaches it: the config is the view's, the rest its data
function visited(path, method) {
	if (path === "/api/config") {
		return VISIT.base;
	}
	if (method !== "GET") {
		throw new Error("This is a view: nothing can be changed here");
	}
	return `${VISIT.base}/data/${path.slice("/api/".length)}`;
}

export async function api(path, options = {}) {
	const init = { method: options.method || "GET", headers: {} };
	if (VISIT && path.startsWith("/api/")) {
		path = visited(path, init.method);
	}
	if (options.body !== undefined) {
		init.headers["Content-Type"] = "application/json";
		init.body = JSON.stringify(options.body);
	}
	const response = await fetch(path, init);
	// a 401 from the library API means the session is gone; from a sign-in route it is the answer
	if (response.status === 401 && !path.startsWith("/auth/") && !VISIT) {
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

export function showError(message) {
	const box = $("error");
	box.textContent = message;
	box.hidden = !message;
}

// The footer's provenance, in the spirit of veltzer.github.io: the year and
// the commit come from the deploy stamp, so the same deploy always says the same.
export async function showBuild() {
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
