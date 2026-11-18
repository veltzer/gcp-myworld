// Showing a page of the world, and keeping it fresh.

import { runChecks, selectChecks } from "./checks.js";
import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { renderEntries, selectKind, state } from "./library.js";
import { fillLocales } from "./names.js";
import { markActive, paging, renderWorld, showSection } from "./paging.js";
import { selectSchema } from "./schema.js";
import { closeSidebarOnPhone } from "./sidebar.js";
import { rerender, setupSort, updateTools } from "./sorting.js";
import { selectStats } from "./stats.js";
import { isAdmin, selectUsers } from "./users.js";
import { WORLDS, setupLayouts, slug, worldCache } from "./worlds.js";

// hash: where the address bar points, the view itself unless one of its rows is wanted
export async function selectWorld(view, hash = view) {
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
export async function reloadWorld(view) {
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
export async function refreshWorld() {
	for (const key of Object.keys(worldCache)) {
		delete worldCache[key];
	}
	const view = state.view;
	worldCache[view] = await api(WORLDS[view][1]);
	if (view === "locales") {
		// the languages the forms offer are these: a change shows in them at once
		state.config = await api("/api/config");
		fillLocales();
	}
	if (state.view !== view) {
		return;
	}
	await fillTypeFilter(view);
	if (state.view === view) {
		renderWorld();
	}
}

// Open the People or Organizations view at one row or card, scrolled to and highlighted.
// Open one row of a view, or one entry of a library kind (id: its work), marked and scrolled to.
export async function showRow(view, id) {
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

export function setupWorlds() {
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
