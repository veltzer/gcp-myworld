// The sidebar: the pages there are, how many rows each has, and folding it away.

import { $, VISIT, api, pageHref, showError } from "./core.js";
import { selectKind, state } from "./library.js";
import { markActive } from "./paging.js";
import { selectWorld } from "./views.js";
import { SHARED_VIEWS, WORLDS, el } from "./worlds.js";

// the sidebar's groups of views: first what is the user's own (the library's kinds, from the config, ahead
// of the rest), then what everyone shares (SHARED_VIEWS), apart, under a heading of its own
const NAV_GROUPS = [
	["Yours", ["concerts", "museums", "audio-courses", "audio-books", "podcasts", "podcast-episodes", "youtube", "chess"]],
	["Your people", ["people", "groups", "organizations"]],
	["Your types", ["organization-types", "person-types", "relation-types", "person-relation-types", "person-organization-types", "devices"]],
	["Shared by everyone", ["places", "cities", "countries", "currencies", "place-kinds", "visit-types", "locales"]],
];

function sideLink(label, key, open) {
	const a = el("a", "side-link");
	a.href = pageHref(key);
	a.append(el("span", "side-label", label), el("span", "side-count"));
	a.onclick = (event) => {
		event.preventDefault();
		closeSidebarOnPhone();
		open();
	};
	return a;
}

// a globe (Material "public"): what everyone shares
const SHARED_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>';

function sideGroup(heading, links, shared = false) {
	const group = el("div", shared ? "side-group shared" : "side-group");
	const title = el("h2", "side-heading", heading);
	if (shared) {
		title.insertAdjacentHTML("afterbegin", SHARED_ICON);
		title.title = "The same rows for every account, with nothing personal on them; only an admin changes them";
	}
	group.append(title, ...links);
	return group;
}

// The sidebar, made once; after that only which page is active changes
export function renderKinds() {
	const nav = $("kinds");
	if (!nav.children.length && VISIT) {
		nav.append(visitGroup());
	} else if (!nav.children.length) {
		const library = Object.entries(state.config.kinds).map(([kind, { plural }]) => {
			const a = sideLink(plural, kind, () => selectKind(kind));
			a.dataset.kind = kind;
			return a;
		});
		const groups = NAV_GROUPS.map(([heading, views], i) => sideGroup(heading, [...(i === 0 ? library : []), ...views.map((view) => {
			const a = sideLink(WORLDS[view][3], view, () => selectWorld(view).catch((e) => showError(e.message)));
			a.dataset.world = view;
			return a;
		})], views.every((view) => SHARED_VIEWS.has(view))));
		nav.append(...groups);
	}
	markActive();
}

// A view's sidebar: the data sets it shows, in the library's order, under its title
function visitGroup() {
	const { datasets, title } = state.config.visit;
	const library = Object.entries(state.config.kinds).filter(([kind]) => datasets.includes(kind)).map(([kind, { plural }]) => {
		const a = sideLink(plural, kind, () => selectKind(kind));
		a.dataset.kind = kind;
		return a;
	});
	const worlds = NAV_GROUPS.flatMap(([, views]) => views).filter((view) => datasets.includes(view)).map((view) => {
		const a = sideLink(WORLDS[view][3], view, () => selectWorld(view).catch((e) => showError(e.message)));
		a.dataset.world = view;
		return a;
	});
	return sideGroup(title, [...library, ...worlds]);
}

// How many rows a view or library kind has, next to its name in the sidebar
export function setCount(key, count) {
	const span = document.querySelector(`#kinds a[data-world="${key}"] .side-count, #kinds a[data-kind="${key}"] .side-count`);
	if (span) {
		span.textContent = count.toLocaleString();
	}
}

// The counts when the page opens, from the stats; each list keeps its own fresh as it is loaded
export async function loadCounts() {
	const stats = await api("/api/stats");
	for (const kind of stats.library) {
		setCount(kind.kind, kind.total);
	}
	const keys = {
		concerts: "concerts", museums: "museum_visits", "audio-courses": "audio_courses", "audio-books": "audio_books", podcasts: "podcasts", "podcast-episodes": "podcast_episodes", youtube: "youtube_videos", chess: "chess_games",
		places: "places", cities: "cities", countries: "countries", currencies: "currencies", people: "people", groups: "groups", organizations: "organizations", "organization-types": "organization_types",
		"person-types": "person_types", "relation-types": "relation_types", "person-relation-types": "person_relation_types",
		"person-organization-types": "person_organization_types", devices: "devices", locales: "locales",
		"place-kinds": "place_kinds", "visit-types": "visit_types",
	};
	for (const [view, key] of Object.entries(keys)) {
		setCount(view, stats[key]);
	}
}

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

export function closeSidebarOnPhone() {
	if (phone.matches) {
		document.body.classList.remove("sidebar-open");
		syncSidebar();
	}
}

export function setupSidebar() {
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
