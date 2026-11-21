// Every list a page at a time.

import { CARDS } from "./cards.js";
import { $, showError } from "./core.js";
import { typeMatches } from "./filters.js";
import { listKey, showCount, state } from "./library.js";
import { renderMap, showsMap } from "./map.js";
import { rankBySearch, searchMatches } from "./search.js";
import { setCount } from "./sidebar.js";
import { rerender, sortItems } from "./sorting.js";
import { COUNTS, WORLDS, worldCache } from "./worlds.js";

const PAGE_SIZES = [25, 50, 100, 200];

const PAGE_SIZE_KEY = "myworld.page-size";

// key: what the list on screen is (view, search, sort, filter, layout): a new one starts at the first page
export const paging = { key: "", page: 0, size: savedPageSize(), shown: [] };

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
export function pageOf(shown, key, paged = true) {
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
export function pagerOff() {
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

export function setupPager() {
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

export function renderWorld() {
	const view = state.view;
	const items = worldCache[view] || [];
	const shown = rankBySearch(sortItems(items.filter((item) => typeMatches(item) && searchMatches(item))));
	const map = showsMap();
	// a page at a time, but the map shows every place
	const page = pageOf(shown, listKey(view), !map);
	$("cards").hidden = map;
	$("cards").replaceChildren(...(map ? [] : page.map(CARDS[view])));
	$("world-map").hidden = !map;
	// "Audio courses" -> "audio courses"; a name with capitals inside ("YouTube videos") stays
	const title = WORLDS[view][0].replace(/^My /, "");
	const what = /^.+[A-Z]/.test(title) ? title : title.toLowerCase();
	const counted = COUNTS[view];
	setCount(view, counted ? counted(items)[0] : items.length);
	if (items.length === 0) {
		$("world-count").textContent = `Nothing here yet: no ${what} for this account.`;
	} else if (counted) {
		// the visits, of the museums shown and of them all
		const [total, said] = counted(items);
		const [inView, saidShown] = counted(shown);
		$("world-count").textContent = inView === total && shown.length === items.length ? `${total.toLocaleString()} ${said}` : `${inView.toLocaleString()} ${saidShown} (of ${total.toLocaleString()})`;
	} else {
		showCount(shown.length, items.length, what);
	}
	if (map) {
		renderMap(shown).catch((e) => showError(e.message));
	}
}

export function markActive() {
	for (const a of document.querySelectorAll("#kinds a")) {
		const active = a.dataset.world ? a.dataset.world === state.view : a.dataset.kind === state.view;
		a.classList.toggle("active", active);
	}
	$("stats-link").classList.toggle("active", state.view === "stats");
	$("imports-link").classList.toggle("active", state.view === "imports");
	$("users-link").classList.toggle("active", state.view === "users");
	$("checks-link").classList.toggle("active", state.view === "checks");
	$("schema-link").classList.toggle("active", state.view === "schema");
}

// One of the page bodies: the library table, the cards and tables, the stats, the imports, the users, the checks.
export function showSection(id) {
	for (const section of ["library-view", "world-view", "stats-view", "imports-view", "users-view", "checks-view", "schema-view"]) {
		$(section).hidden = section !== id;
	}
}
