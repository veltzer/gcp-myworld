// The search box over a list.

import { $ } from "./core.js";
import { haystack } from "./filters.js";

function searchWords() {
	return $("world-search").value.toLowerCase().split(/\s+/).filter(Boolean);
}

// How well a row matches the search, best first: its name is the search,
// starts with it, has every word at the start of one of its words, has every
// word in it; then every word starts a word somewhere else in the row; then
// only inside other words ("mer" in "America"). Rows of the same rank keep the
// order picked with Sort.
function searchRank(item, words) {
	const name = String(item.name ?? item.title ?? "").toLowerCase();
	const query = words.join(" ");
	if (name === query) {
		return 0;
	}
	if (name.startsWith(query)) {
		return 1;
	}
	const wordStart = (text, word) => new RegExp(`(^|[^\\p{L}\\p{N}])${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "u").test(text);
	if (words.every((word) => wordStart(name, word))) {
		return 2;
	}
	if (words.every((word) => name.includes(word))) {
		return 3;
	}
	const text = haystack(item);
	return words.every((word) => wordStart(text, word)) ? 4 : 5;
}

export function rankBySearch(items) {
	const words = searchWords();
	if (words.length === 0) {
		return items;
	}
	const ranks = new Map(items.map((item) => [item, searchRank(item, words)]));
	// a stable sort: within a rank, the Sort order stays
	return [...items].sort((a, b) => ranks.get(a) - ranks.get(b));
}

export function searchMatches(item) {
	const words = $("world-search").value.toLowerCase().split(/\s+/).filter(Boolean);
	const text = haystack(item);
	return words.every((w) => text.includes(w));
}
