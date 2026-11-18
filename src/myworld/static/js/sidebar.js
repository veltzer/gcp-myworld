// The sidebar: the pages there are, how many rows each has, and folding it away.

import { $, api, showError } from "./core.js";
import { selectKind, state } from "./library.js";
import { markActive } from "./paging.js";
import { selectWorld } from "./views.js";
import { WORLDS, el } from "./worlds.js";

// the sidebar's groups of views (the library's kinds come first, from the config)
// The library kinds (books) come first in Datasets, ahead of these
const NAV_GROUPS = [
	["Datasets", ["concerts", "museums", "audio-courses", "youtube", "places", "cities", "countries"]],
	["People", ["people", "groups", "organizations"]],
	["Types", ["organization-types", "person-types", "relation-types", "person-relation-types", "person-organization-types", "devices", "locales"]],
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
export function renderKinds() {
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
		concerts: "concerts", museums: "museums", "audio-courses": "audio_courses", youtube: "youtube_videos",
		places: "places", cities: "cities", countries: "countries", people: "people", groups: "groups", organizations: "organizations", "organization-types": "organization_types",
		"person-types": "person_types", "relation-types": "relation_types", "person-relation-types": "person_relation_types",
		"person-organization-types": "person_organization_types", devices: "devices", locales: "locales",
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
