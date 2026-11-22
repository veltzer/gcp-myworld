// The Stats page.

import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { selectKind, state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { selectWorld } from "./views.js";
import { WORLDS, el } from "./worlds.js";

export async function selectStats() {
	state.view = "stats";
	navigate("stats");
	document.title = "Stats - My World";
	showSection("stats-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("stats");
	updateTools();
	$("world-count").textContent = "";
	const stats = await api("/api/stats");
	if (state.view === "stats") {
		renderStats(stats);
	}
}

// A number with what it counts, a link to its tab when there is one.
function statTile(label, value, sub, target) {
	const tile = el(target ? "a" : "div", "stat-tile");
	if (target) {
		tile.href = `/library#${target}`;
		tile.onclick = (event) => {
			event.preventDefault();
			(target in WORLDS ? selectWorld(target) : selectKind(target)).catch((e) => showError(e.message));
		};
	}
	tile.append(el("span", "stat-value", value.toLocaleString()), el("span", "stat-label", label));
	if (sub) {
		tile.appendChild(el("span", "stat-sub", sub));
	}
	return tile;
}

// One series of named counts as horizontal bars, the count written beside each.
function barChart(title, rows) {
	const card = el("section", "chart-card");
	card.appendChild(el("h2", null, title));
	const max = Math.max(1, ...rows.map((r) => r.count));
	const list = el("div", "bar-list");
	for (const row of rows) {
		const line = el("div", "bar-row");
		line.title = `${row.name}: ${row.count}`;
		const track = el("span", "bar-track");
		const fill = el("span", "bar-fill");
		fill.style.width = `${(100 * row.count) / max}%`;
		track.appendChild(fill);
		line.append(el("span", "bar-name", row.name), track, el("span", "bar-value", row.count));
		list.appendChild(line);
	}
	card.appendChild(list);
	return card;
}

// Counts per year as columns, every year in the range shown (empty ones too).
function yearChart(title, rows, noun) {
	const card = el("section", "chart-card");
	card.appendChild(el("h2", null, title));
	if (rows.length === 0) {
		card.appendChild(el("p", "empty", "Nothing dated yet."));
		return card;
	}
	const counts = new Map(rows.map((r) => [r.year, r.count]));
	const first = rows[0].year;
	const last = rows[rows.length - 1].year;
	const max = Math.max(...rows.map((r) => r.count));
	const plot = el("div", "columns");
	const axis = el("div", "column-years");
	const step = Math.max(1, Math.ceil((last - first + 1) / 8));
	for (let year = first; year <= last; year++) {
		const n = counts.get(year) || 0;
		const column = el("span", "column");
		column.title = `${year}: ${n} ${noun}`;
		const fill = el("span", "column-fill");
		fill.style.height = `${(100 * n) / max}%`;
		column.appendChild(fill);
		plot.appendChild(column);
		axis.appendChild(el("span", null, (year - first) % step === 0 ? String(year) : ""));
	}
	card.append(plot, axis, el("p", "chart-note", `Most: ${max} ${noun} in a year. Hover a column for its year.`));
	return card;
}

function renderStats(stats) {
	const tiles = el("div", "stat-tiles");
	for (const kind of stats.library) {
		const sub = Object.entries(kind.by_status).map(([status, n]) => `${n} ${status.toLowerCase()}`).join(" · ");
		tiles.appendChild(statTile(kind.label, kind.total, sub, kind.kind));
	}
	tiles.append(
		statTile("Concerts", stats.concerts, `${stats.performers} performers`, "concerts"),
		statTile("Museum visits", stats.museum_visits, `${stats.museums} museums`, "museums"),
		statTile("Audio courses", stats.audio_courses, "", "audio-courses"),
		statTile("Audio books heard", stats.audio_books_heard, `${stats.audio_book_listens} versions heard`, "audio-books-heard"),
		statTile("Podcasts heard", stats.podcasts_heard, `${stats.episodes_heard} episodes heard`, "podcasts-heard"),
		statTile("Films watched", stats.films_watched, `${stats.film_watches} film watches`, "film-watches"),
		statTile("Series watched", stats.series_watched, `${stats.series_watches} series watches`, "series-watches"),
		statTile("YouTube videos", stats.youtube_videos, "", "youtube"),
		statTile("Chess games", stats.chess_games, stats.chess_by_outcome.map((o) => `${o.count.toLocaleString()} ${o.name.toLowerCase()}`).join(" · "), "chess"),
		statTile("Places", stats.places, "", "places"),
		statTile("Podcasts", stats.podcasts, `${stats.podcast_episodes.toLocaleString()} episodes`, "podcasts"),
		statTile("Audio books", stats.audio_books, `${stats.audio_book_versions.toLocaleString()} versions`, "audio-books"),
		statTile("Films", stats.films, "", "films"),
		statTile("Series", stats.series, "", "series"),
		statTile("Cities", stats.cities, "", "cities"),
		statTile("Countries", stats.countries, "", "countries"),
		statTile("People", stats.people, "", "people"),
		statTile("Groups", stats.groups, "", "groups"),
		statTile("Organizations", stats.organizations, "", "organizations"),
		statTile("Organization tags", stats.organization_types, "", "organization-types"),
		statTile("Professions", stats.person_types, "", "person-types"),
		statTile("Org relation types", stats.relation_types, "", "relation-types"),
		statTile("Person relation types", stats.person_relation_types, "", "person-relation-types"),
		statTile("Person-org relation types", stats.person_organization_types, "", "person-organization-types"),
		statTile("Devices", stats.devices, "", "devices"),
		statTile("Photos and logos", stats.images, "", null),
	);
	const charts = el("div", "stat-charts");
	charts.append(
		barChart("People by profession (one with several counts in each)", stats.people_by_type),
		barChart("Organizations by type", stats.organizations_by_type),
		barChart("Organizations by relation (one with several relations counts in each)", stats.organizations_by_relation),
		yearChart("Concerts per year", stats.concerts_by_year, "concerts"),
		yearChart("Museum visits per year", stats.museums_by_year, "visits"),
		barChart("YouTube videos by channel (the most watched)", stats.youtube_by_channel),
		barChart("YouTube videos by category", stats.youtube_by_category),
		yearChart("Chess games per year", stats.chess_by_year, "games"),
	);
	$("stats-view").replaceChildren(tiles, charts);
}
