// The filters over a list, and what the search box looks in.

import { $ } from "./core.js";
import { worldList } from "./dialog.js";
import { state } from "./library.js";
import { rerender } from "./sorting.js";
import { TYPED, el, formatDate } from "./worlds.js";

// The filter next to the search, in groups. On a view whose rows have a
// type (people, organizations) one group picks types; on a library kind
// one picks statuses (Done, Want to, ...) and one whether it has a cover; on
// the chess games one picks how they ended, one the side played, one the site.
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

// What a view is filtered by: what the button says with nothing picked, and
// its groups ({key, heading, options: [{value, name, count}]}). Null: nothing to filter by.
async function filterSpec(view) {
	if (TYPED[view]) {
		const types = await worldList(TYPED[view]);
		const options = types.map((t) => ({ value: String(t.id), name: t.name, count: t.count }));
		return { all: "All types", groups: [{ key: "type", heading: "", options: [...options, { value: "none", name: "No type", count: null }] }] };
	}
	if (view === "chess") {
		// how it ended, the side played and where it was played, each value with how many games have it
		const games = await worldList(view);
		const group = (key, heading, value) => {
			const counts = new Map();
			for (const game of games) {
				counts.set(value(game), (counts.get(value(game)) || 0) + 1);
			}
			const options = [...counts].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ value: name, name: name || "(none)", count }));
			return { key, heading, options };
		};
		return {
			all: "All games",
			groups: [group("outcome", "Result", (g) => g.outcome), group("color", "Played as", (g) => (g.color === "white" ? "White" : "Black")), group("site", "Site", (g) => g.site)],
		};
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
	if (group === "status") {
		return [item.status];
	}
	if (group === "cover") {
		return [item.image ? "yes" : "no"];
	}
	if (group === "outcome") {
		return [item.outcome];
	}
	if (group === "color") {
		return [item.color === "white" ? "White" : "Black"];
	}
	if (group === "site") {
		return [item.site];
	}
	// a person has a list of types, an organization one
	const types = item.types || (item.type ? [item.type] : []);
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
	status: (view) => view in state.config.kinds,
	cover: (view) => view in state.config.kinds,
	outcome: (view) => view === "chess",
	color: (view) => view === "chess",
	site: (view) => view === "chess",
};

export function typeMatches(item) {
	const view = state.view;
	const picked = pickedTypes(view);
	if (picked.size === 0) {
		return true;
	}
	// within a group any picked value will do; every group with a pick must match
	return Object.entries(FILTER_GROUPS).every(([group, applies]) => {
		if (!applies(view)) {
			return true;
		}
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
