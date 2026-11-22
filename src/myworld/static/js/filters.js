// The filters over a list, and what the search box looks in.

import { $ } from "./core.js";
import { worldList } from "./dialog.js";
import { state } from "./library.js";
import { rerender } from "./sorting.js";
import { SIDES, TYPED, el, formatDate } from "./worlds.js";

// The filter next to the search, in groups. On a view whose rows have a
// type (people, organizations) one group picks types; on a library kind
// one picks statuses (Done, Want to, ...) and one whether it has a cover; on
// the views of VALUE_FILTERS each group picks values the rows have (the
// chess games: how they ended, the side played, the site).
// Kept per view as a set of "group:value" ("type:none" for the rows without
// a type), empty for everything. A row matches when, in every group with
// something picked, it has one of the picked values.
const typeFilters = {};

export function pickedTypes(view) {
	if (!typeFilters[view]) {
		typeFilters[view] = new Set();
	}
	return typeFilters[view];
}

// how far a listen (or a book heard) got, in words
const LISTEN_STATUS = { done: "Finished", in_progress: "In progress", "": "Not started" };
const named = (ref) => (ref ? [ref.name] : []);

// The views filtered by values their rows have: what the button says with
// nothing picked, and each group's key, heading and the row's values in it
// (a list: a row may have several, or none); each value is offered with how
// many rows have it, the most first.
const VALUE_FILTERS = {
	chess: {
		all: "All games",
		groups: [
			["outcome", "Result", (g) => [g.outcome]],
			["color", "Played as", (g) => [SIDES[g.color]]],
			["site", "Site", (g) => [g.site]],
		],
	},
	"audio-courses": {
		all: "All courses",
		groups: [
			["status", "Status", (c) => [c.date ? "Finished" : "In progress"]],
			["device", "Device", (c) => named(c.device)],
		],
	},
	"audio-books-heard": {
		all: "All audio books",
		groups: [
			["status", "Status", (b) => [LISTEN_STATUS[b.status]]],
			["kind", "Versions heard", (b) => b.listens.map((l) => l.name)],
		],
	},
	"audio-book-listens": {
		all: "All listens",
		groups: [
			["kind", "Kind", (b) => [b.kind_name]],
			["status", "Status", (b) => [LISTEN_STATUS[b.status]]],
			["device", "Device", (b) => named(b.device)],
		],
	},
	"audio-books": {
		all: "All audio books",
		groups: [["kind", "Versions", (b) => b.versions.map((v) => v.name)]],
	},
	"audio-book-versions": {
		all: "All versions",
		groups: [
			["kind", "Kind", (v) => [v.kind_name]],
			["heard", "You heard it", (v) => [v.listen ? "Heard" : "Not heard"]],
		],
	},
	"podcast-episodes": {
		all: "All episodes",
		groups: [
			["podcast", "Podcast", (e) => named(e.podcast)],
			["heard", "You heard it", (e) => [e.heard ? "Heard" : "Not heard"]],
		],
	},
	"episodes-heard": {
		all: "All episodes",
		groups: [
			["podcast", "Podcast", (e) => named(e.podcast)],
			["device", "Device", (e) => named(e.device)],
		],
	},
	films: {
		all: "All films",
		groups: [
			["genre", "Genre", (f) => f.genres],
			["watched", "You watched it", (f) => [f.watches.length ? "Watched" : "Not watched"]],
		],
	},
	series: {
		all: "All series",
		groups: [
			["genre", "Genre", (f) => f.genres],
			["watched", "You watched it", (f) => [f.watches.length ? "Watched" : "Not watched"]],
		],
	},
	"series-watches": {
		all: "All series watches",
		groups: [
			["status", "Status", (w) => [w.status_name]],
			["seen", "Seen", (w) => [w.seasons_not_seen.length ? "Some seasons" : "Every season known"]],
			["device", "Device", (w) => named(w.device)],
		],
	},
	"film-watches": {
		all: "All film watches",
		groups: [
			["status", "Status", (w) => [w.status_name]],
			["device", "Device", (w) => named(w.device)],
			["where", "Where", (w) => (w.watched_at ? [w.watched_at] : [])],
			["genre", "Genre", (w) => w.genres],
		],
	},
	youtube: {
		all: "All videos",
		groups: [["device", "Device", (v) => named(v.device)]],
	},
};

// The views whose rows also have relations, filtered by them too: what the
// button says with nothing picked, and a row's relations as their cards read
// them. An organization's are to the user (Consulting, Teaching, ...); a
// person's are to other people, from either side ("Mother of" on hers,
// "Child of" on her child's).
const RELATED = {
	organizations: { all: "All organizations", values: (o) => o.relations.map((r) => r.name) },
	people: { all: "All people", values: (p) => [...p.relations, ...p.related].map((r) => r.type) },
};

// What a view is filtered by: what the button says with nothing picked, and
// its groups ({key, heading, options: [{value, name, count}]}). Null: nothing to filter by.
async function filterSpec(view) {
	if (TYPED[view]) {
		const typeRows = await worldList(TYPED[view]);
		const types = [...typeRows.map((t) => ({ value: String(t.id), name: t.name, count: t.count })), { value: "none", name: "No type", count: null }];
		if (!RELATED[view]) {
			return { all: "All types", groups: [{ key: "type", heading: "", options: types }] };
		}
		// the relations the rows have, each with how many rows have it, the most first
		const counts = new Map();
		for (const row of await worldList(view)) {
			for (const value of new Set(RELATED[view].values(row))) {
				counts.set(value, (counts.get(value) || 0) + 1);
			}
		}
		const relations = [...counts].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0])).map(([name, count]) => ({ value: name, name, count }));
		return {
			all: RELATED[view].all,
			groups: [
				{ key: "type", heading: "Type", options: types },
				{ key: "relation", heading: "Relation", options: [...relations, { value: "none", name: "No relation", count: null }] },
			],
		};
	}
	if (VALUE_FILTERS[view]) {
		const rows = await worldList(view);
		const groups = VALUE_FILTERS[view].groups.map(([key, heading, values]) => {
			const counts = new Map();
			for (const row of rows) {
				for (const value of new Set(values(row))) {
					counts.set(value, (counts.get(value) || 0) + 1);
				}
			}
			const options = [...counts].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ value: name, name: name || "(none)", count }));
			return { key, heading, options };
		});
		// a group with one value or none filters nothing: left out; with none left, there is nothing to filter by
		const kept = groups.filter((group) => group.options.length > 1);
		return kept.length ? { all: VALUE_FILTERS[view].all, groups: kept } : null;
	}
	if (state.config.kinds[view]) {
		const count = (test) => state.entries.filter(test).length;
		const statuses = Object.entries(state.config.statuses).map(([value, name]) => ({ value, name, count: count((e) => e.status === value) }));
		const covers = [
			{ value: "yes", name: "With a cover", count: count((e) => e.image) },
			{ value: "no", name: "No cover", count: count((e) => !e.image) },
		];
		return {
			all: `All ${state.config.kinds[view].plural.toLowerCase()}`,
			groups: [{ key: "status", heading: "Status", options: statuses }, { key: "cover", heading: "Cover", options: covers }],
		};
	}
	return null;
}

// a row's values in a filter group
function filterValues(group, item) {
	if (group === "status" && !VALUE_FILTERS[state.view]) {
		return [item.status];
	}
	if (group === "cover") {
		return [item.image ? "yes" : "no"];
	}
	const valued = VALUE_FILTERS[state.view]?.groups.find(([key]) => key === group);
	if (valued) {
		return valued[2](item);
	}
	if (group === "relation") {
		const relations = RELATED[state.view].values(item);
		return relations.length ? relations : ["none"];
	}
	// a person or an organization has a list of types
	const types = item.types || [];
	return types.length ? types.map((t) => String(t.id)) : ["none"];
}

// The button names what is picked: "All types", the names, or how many.
function typeFilterLabel(view, spec) {
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return spec.all;
	}
	const names = spec.groups.flatMap((group) => group.options.filter((o) => picked.has(`${group.key}:${o.value}`)).map((o) => o.name));
	return names.length <= 2 ? names.join(", ") : `${names.length} picked`;
}

export async function fillTypeFilter(view) {
	const button = $("type-filter");
	const menu = $("type-filter-menu");
	const spec = await filterSpec(view);
	// the control is shared by every view: only the one on screen fills it
	if (state.view !== view) {
		return;
	}
	menu.hidden = true;
	button.setAttribute("aria-expanded", "false");
	// a view with nothing to filter by keeps the control, disabled
	button.disabled = !spec;
	if (!spec) {
		button.textContent = "All types";
		menu.replaceChildren();
		return;
	}
	const picked = pickedTypes(view);
	const box = (value, label) => {
		const line = el("label", "type-filter-option");
		const input = document.createElement("input");
		input.type = "checkbox";
		input.value = value;
		input.checked = picked.has(value);
		input.onchange = () => {
			if (input.checked) {
				picked.add(value);
			} else {
				picked.delete(value);
			}
			button.textContent = typeFilterLabel(view, spec);
			rerender();
		};
		line.append(input, ` ${label}`);
		return line;
	};
	const clear = el("button", "text", "Show all");
	clear.type = "button";
	clear.onclick = () => {
		picked.clear();
		for (const input of menu.querySelectorAll("input")) {
			input.checked = false;
		}
		button.textContent = typeFilterLabel(view, spec);
		rerender();
	};
	menu.replaceChildren(
		...spec.groups.flatMap((group) => [
			...(group.heading ? [el("span", "type-filter-heading", group.heading)] : []),
			...group.options.map((o) => box(`${group.key}:${o.value}`, o.count === null ? o.name : `${o.name} (${o.count})`)),
		]),
		clear,
	);
	button.textContent = typeFilterLabel(view, spec);
}

// the filter groups a view has, by key
const FILTER_GROUPS = {
	type: (view) => Boolean(TYPED[view]),
	relation: (view) => Boolean(RELATED[view]),
	status: (view) => view in state.config.kinds,
	cover: (view) => view in state.config.kinds,
};

// a view's groups: those of VALUE_FILTERS, or else those FILTER_GROUPS says it has
function groupsOf(view) {
	if (VALUE_FILTERS[view]) {
		return VALUE_FILTERS[view].groups.map(([key]) => key);
	}
	return Object.entries(FILTER_GROUPS).filter(([, applies]) => applies(view)).map(([key]) => key);
}

export function typeMatches(item) {
	const view = state.view;
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return true;
	}
	// within a group any picked value will do; every group with a pick must match
	return groupsOf(view).every((group) => {
		const wanted = [...picked].filter((value) => value.startsWith(`${group}:`));
		return wanted.length === 0 || filterValues(group, item).some((value) => wanted.includes(`${group}:${value}`));
	});
}

// Everything a search can match on, as one lowercase string.
// what a row is searched by, worked out once per row: there can be 30,000 of them
const haystacks = new WeakMap();

export function haystack(item) {
	if (!haystacks.has(item)) {
		haystacks.set(item, buildHaystack(item));
	}
	return haystacks.get(item);
}

function buildHaystack(item) {
	const values = [];
	for (const value of Object.values(item)) {
		if (typeof value === "string") {
			values.push(value);
		} else if (Array.isArray(value)) {
			values.push(...value.map((v) => (typeof v === "string" ? v : (v.name ?? v.title ?? ""))));
		} else if (value && typeof value === "object" && typeof value.name === "string") {
			values.push(value.name);
		}
	}
	values.push(formatDate(item));
	return values.join(" ").toLowerCase();
}
