// Back and Forward inside the page.

import { $, showError } from "./core.js";
import { state } from "./library.js";
import { openHash } from "./main.js";
import { reloadWorld } from "./views.js";
import { WORLDS } from "./worlds.js";

// The app is one page: each view, and each row a link opened, is a history
// entry with its own #hash, so the browser's Back and Forward and the two
// arrows in the toolbar walk through them. The entries are numbered (in
// history.state) to know when there is nothing further back or forward.
const NAV_TOP_KEY = "myworld.nav-top";

// replacing: while the page opens what the address bar already says (at start,
// on Back or Forward), a view that fills in its own hash ("" -> "#concerts")
// corrects the entry it is on rather than adding one
export const nav = { index: 0, top: 0, replacing: false };

export function navigate(hash) {
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
	} catch {
		// blocked storage: after a reload Forward may stay disabled; Back still works
	}
}

// Back to this tab after a while: the data may have changed meanwhile.
export function setupFreshness() {
	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState === "visible" && state.view in WORLDS) {
			reloadWorld(state.view).catch((e) => showError(e.message));
		}
	});
}

export function startHistory() {
	const known = window.history.state && Number.isInteger(window.history.state.nav);
	nav.index = known ? window.history.state.nav : 0;
	let top = 0;
	try {
		top = Number(window.sessionStorage.getItem(NAV_TOP_KEY)) || 0;
	} catch {
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
