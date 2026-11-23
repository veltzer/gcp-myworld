// What every page uses: the API, the error line and the footer.

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

// The footer's copyright year: this year, as the reader's clock says it. (The build serving is on the
// About page, not on every page: a page the same for every build is one the browser may keep.)
export function showYear() {
	for (const year of document.querySelectorAll(".copyright-year")) {
		year.textContent = String(new Date().getFullYear());
	}
}
