// What a row looks like as a card, for every page.

import { boardImage } from "./board.js";
import { $, api, pageHref, showError } from "./core.js";
import { worldList } from "./dialog.js";
import { editable, state } from "./library.js";
import { placeButton } from "./map.js";
import { localeName } from "./names.js";
import { showRow } from "./views.js";
import { visitText } from "./visits.js";
import { SIDES, cornerOf, detail, el, formatDate, inView, linksDetail, slug, websiteButton } from "./worlds.js";

// what the picture of the rows of the view shown is called ("photo", "logo", "flag": its dialog's
// picture box says), "" for rows that never have one
function pictureName() {
	return document.getElementById(`${slug(state.view)}-form`)?.querySelector("[data-pictures]")?.dataset.what || "";
}

const NO_COVER_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 4h5v8l-2.5-1.5L6 12V4z"/></svg>';

// a camera, struck through
const NO_PHOTO_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3 7.2 5H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2h-3.2L15 3H9zm3 15c-2.8 0-5-2.2-5-5s2.2-5 5-5 5 2.2 5 5-2.2 5-5 5z"/><path d="M3 2 22 21" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';

export function cardShell(item, subtitle, kind = "photo") {
	const card = el("article", "world-card");
	card.id = `${slug(state.view)}-${item.id}`;
	card.title = item.name;
	if (item.image) {
		card.classList.add("has-image", `is-${kind}`);
		const img = el("img", "world-image");
		img.src = item.image;
		img.alt = "";
		img.loading = "lazy";
		card.appendChild(img);
	} else if (kind === "cover" || pictureName()) {
		// something that could have a picture and has none gets a blank one that says so plainly
		// ("No cover", "No photo", "No logo", "No flag"), laid out in every layout like a real one
		const what = kind === "cover" ? "cover" : pictureName();
		card.classList.add("has-image", `is-${kind}`, "no-picture");
		const slot = el("div", "world-image cover-slot");
		const blank = el("div", kind === "cover" ? "cover-blank" : "cover-blank picture-blank");
		blank.innerHTML = kind === "cover" ? NO_COVER_ICON : NO_PHOTO_ICON;
		blank.appendChild(el("span", null, `No ${what}`));
		slot.appendChild(blank);
		card.appendChild(slot);
	} else {
		// what never has a picture: an empty slot, so the list layout keeps every row the same shape
		card.appendChild(el("div", "world-image no-image"));
	}
	const body = el("div", "world-body");
	// a Hebrew title or name reads right to left, inside a page that reads left to right
	const heading = el("h2", "world-title", item.name);
	heading.dir = "auto";
	body.appendChild(heading);
	// the subtitle is text, or nodes of its own (a book's authors, as links)
	if (subtitle) {
		const line = el("p", "world-subtitle");
		line.append(subtitle);
		line.dir = "auto";
		body.appendChild(line);
	}
	const list = el("ul", "world-details");
	body.appendChild(list);
	card.appendChild(body);
	editable(card, item);
	return { card, body, list };
}

function concertCard(item) {
	const { body, card, list } = cardShell(item, item.event);
	detail(list, "Date", formatDate(item));
	// where it was: a link to the place on the Places page
	linksDetail(list, "Where", "places", item.place ? [{ id: item.place.id, name: placeName(item.place) }] : []);
	// a show named after its one performer does not repeat the name
	const performers = item.performers.length === 1 && item.performers[0].name === item.name ? [] : item.performers;
	linksDetail(list, "Groups", "groups", item.groups);
	linksDetail(list, "Performers", "people", performers);
	detail(list, "Genre", item.genre);
	if (item.alone) {
		detail(list, "With", "alone");
	}
	linksDetail(list, "With", "people", item.people);
	detail(list, "Tickets", item.tickets);
	if (item.broadcast) {
		detail(list, "Seen", "on TV");
	}
	detail(list, "Review", item.review);
	detail(list, "Remark", item.remark);
	photoCredit(body, item);
	return card;
}

// The credit a photo's license asks for, under the card: "Photo: author, license", linked to where it comes from
function photoCredit(body, item, what = "Photo") {
	if (!item.image || !item.image_source) {
		return;
	}
	const credit = el("p", "credit");
	const a = el("a", null, what);
	a.href = item.image_source;
	a.target = "_blank";
	a.rel = "noopener";
	const who = [item.image_author, item.image_license].filter(Boolean).join(", ");
	credit.append(a, who ? `: ${who}` : "");
	body.appendChild(credit);
}

// "Tmuna Theater, Tel Aviv": a place's name with its city, when it has one
function placeName(place) {
	return [place.name, place.city?.name].filter(Boolean).join(", ");
}

// "Santa Clara, California, United States of America": a city with its region and country
export function cityName(city) {
	return [city.name, city.region, city.country?.name].filter(Boolean).join(", ");
}

// how a single picker names the rows of a view
export const PICKER_LABELS = { places: placeName, cities: cityName, "podcast-episodes": (row) => `${row.podcast?.name}: ${row.name}` };

function placeCard(item) {
	const { card, list } = cardShell(item, [item.city?.name, item.city?.country?.name].filter(Boolean).join(", "));
	cornerOf(card).appendChild(placeButton(item));
	linksDetail(list, "City", "cities", item.city ? [item.city] : []);
	detail(list, "Address", item.address);
	// how many concerts were there, always shown (0 too), then which
	// what it is (museum, concert venue, ...), each a link to its row of Place kinds
	linksDetail(list, "Kinds", "place-kinds", item.kinds);
	detail(list, "Concerts", String(item.concerts.length));
	linksDetail(list, "Seen there", "concerts", item.concerts);
	// the user's own visits there (museum visits, ...), always counted
	detail(list, "Your visits", String(item.visits));
	websiteButton(card, item.website);
	return card;
}

function groupCard(item) {
	const { card, body, list } = cardShell(item, item.description);
	// how many people are in it, always shown (0 too), then who they are
	detail(list, "Members", String(item.members.length));
	linksDetail(list, "Who", "people", item.members);
	linksDetail(list, "Performed at", "concerts", item.concerts);
	websiteButton(card, item.website);
	photoCredit(body, item);
	return card;
}

function cityCard(item) {
	const { card, body, list } = cardShell(item, [item.region, item.country?.name].filter(Boolean).join(", "));
	cornerOf(card).appendChild(placeButton(item));
	linksDetail(list, "Country", "countries", item.country ? [item.country] : []);
	detail(list, "Population", item.population === null || item.population === undefined ? "" : item.population.toLocaleString());
	// what is in it, each always counted (0 too), then which
	detail(list, "Places", String(item.places.length));
	linksDetail(list, "Which places", "places", item.places);
	linksDetail(list, "Museums", "places", item.museums);
	linksDetail(list, "Organizations", "organizations", item.organizations);
	linksDetail(list, "Headquarters of", "organizations", item.headquarters_of);
	photoCredit(body, item);
	return card;
}

// a country's picture is its flag, shown whole as a logo is
function countryCard(item) {
	const { card, body, list } = cardShell(item, `${item.cities.length.toLocaleString()} ${item.cities.length === 1 ? "city" : "cities"}`, "logo");
	cornerOf(card).appendChild(placeButton(item));
	detail(list, "Code", [item.code, item.code3].filter(Boolean).join(", "));
	linksDetail(list, "Currencies", "currencies", item.currencies);
	linksDetail(list, "Languages", "locales", item.languages);
	linksDetail(list, "Cities", "cities", item.cities);
	photoCredit(body, item, "Flag");
	return card;
}

function currencyCard(item) {
	const { card, list } = cardShell(item, [item.code, item.symbol].filter(Boolean).join(" "));
	detail(list, "Code", item.code);
	detail(list, "Symbol", item.symbol);
	detail(list, "Digits", item.digits === null ? "" : String(item.digits));
	detail(list, "Countries", String(item.countries.length));
	linksDetail(list, "Which countries", "countries", item.countries);
	return card;
}

function museumCard(item) {
	const { card, list } = cardShell(item, item.city?.name);
	cornerOf(card).appendChild(placeButton(item));
	linksDetail(list, "City", "cities", item.city ? [item.city] : []);
	detail(list, "Address", item.address);
	// every time it was visited, the latest first: the day, the rating and the company of each
	detail(list, item.visits.length === 1 ? "Visit" : "Visits", item.visits.length ? item.visits.map(visitText).join("; ") : "none yet");
	linksDetail(list, "With", "people", item.people);
	detail(list, "Review", item.visits.map((visit) => visit.review).filter(Boolean).join("; "));
	detail(list, "Remark", item.visits.map((visit) => visit.remark).filter(Boolean).join("; "));
	websiteButton(card, item.url);
	return card;
}

function organizationCard(item) {
	const { card, list } = cardShell(item, item.location, "logo");
	cornerOf(card).appendChild(placeButton(item));
	linksDetail(list, "Type", "organization-types", item.type ? [item.type] : []);
	// the office's city, and where its headquarters are when elsewhere
	linksDetail(list, "City", "cities", item.city ? [item.city] : []);
	linksDetail(list, "Headquarters", "cities", item.headquarters && item.headquarters.id !== item.city?.id ? [item.headquarters] : []);
	// how it is related to me: links to the Relation types page
	linksDetail(list, "Relation", "relation-types", item.relations);
	detail(list, "Status", item.status);
	detail(list, "What happened", item.what_happened);
	detail(list, "Address", item.address);
	// how many people are at it, always shown (0 too), then who they are
	detail(list, "People", String(item.people.length));
	// each with how they are linked: "Dana Cohen (Worked at)"
	linksDetail(list, "Who", "people", item.person_links.map((link) => ({ id: link.person.id, name: link.name })));
	detail(list, "Remark", item.remark);
	websiteButton(card, item.website);
	return card;
}

function audioCourseCard(item) {
	const { card, list } = cardShell(item, item.lecturers.map((p) => p.name).join(", "));
	linksDetail(list, "Lecturer", "people", item.lecturers);
	if (item.status === "in_progress") {
		detail(list, "Status", ["In progress", item.progress].filter(Boolean).join(", "));
		detail(list, "Started", item.started.slice(0, 10));
	} else {
		detail(list, "Finished", formatDate(item));
	}
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
	detail(list, "Where", item.listened_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	websiteButton(card, item.url);
	return card;
}

// 1346 -> "22h 26m", 45 -> "45m"
function formatMinutes(minutes) {
	if (minutes === null) {
		return "";
	}
	const h = Math.floor(minutes / 60);
	return h ? `${h}h ${minutes % 60}m` : `${minutes}m`;
}

function audioBookCard(item) {
	const { card, list } = cardShell(item, item.authors);
	detail(list, "Subtitle", item.subtitle);
	detail(list, "Narrators", item.narrators);
	detail(list, "Series", [item.series, item.series_sequence && `#${item.series_sequence}`].filter(Boolean).join(" "));
	if (item.status === "done") {
		detail(list, "Finished", item.date ? formatDate(item) : "Yes");
	} else {
		detail(list, "Status", item.status === "in_progress" ? ["In progress", item.percent_heard ? `${Math.round(item.percent_heard)}% heard` : item.progress].filter(Boolean).join(", ") : "Not started");
		detail(list, "Started", item.started.slice(0, 10));
	}
	detail(list, "Length", formatMinutes(item.minutes));
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
	// each once: the list repeats a top genre for each path under it
	detail(list, "Genres", [...new Set(item.genres)].join(", "));
	detail(list, "Where", item.listened_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	detail(list, "Released", item.released);
	detail(list, "Added", item.added.slice(0, 10));
	if (item.source_rating !== null) {
		detail(list, `On ${item.source_name || "its source"}`, `${item.source_rating}/5${item.source_ratings ? ` (${item.source_ratings.toLocaleString()} ratings)` : ""}`);
	} else {
		detail(list, "From", item.source_name);
	}
	websiteButton(card, item.url, item.source_name ? `${item.source_name} page` : "Page");
	return card;
}

// a podcast, shared: its episodes as its feed has them, and how many of them the user heard
function podcastCard(item) {
	const { card, list } = cardShell(item, "", "cover");
	// always said, 0 too
	detail(list, "Episodes", String(item.episodes));
	detail(list, "Latest episode", item.published.slice(0, 10));
	detail(list, "Episodes you heard", String(item.heard));
	websiteButton(card, item.url);
	return card;
}

// an episode, shared, as its feed says it; when the user heard it, a link to their hearing of it
function podcastEpisodeCard(item) {
	const { card, list } = cardShell(item, item.podcast?.name || "", "cover");
	linksDetail(list, "Podcast", "podcasts", item.podcast ? [item.podcast] : []);
	linksDetail(list, "You heard it", "episodes-heard", item.heard ? [{ id: item.heard.id, name: formatDate(item.heard) || "Yes" }] : []);
	feedDetails(list, item);
	websiteButton(card, item.url, "Listen");
	return card;
}

function feedDetails(list, item) {
	detail(list, "Number", item.number === null ? "" : String(item.number));
	detail(list, "Published", item.published.slice(0, 10));
	detail(list, "Length", formatDuration(item.duration));
	detail(list, "About", item.description);
}

function rated(list, item) {
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
}

// a podcast the user listens to: what they think of it, and the episodes of it they heard, each a link to its hearing
function podcastHeardCard(item) {
	const { card, list } = cardShell(item, "", "cover");
	linksDetail(list, "Podcast", "podcasts", item.podcast ? [item.podcast] : []);
	rated(list, item);
	// always said, 0 too
	detail(list, "Episodes heard", String(item.episodes.length));
	detail(list, "Time heard", item.duration ? formatDuration(item.duration) : "");
	detail(list, "Last heard", item.date_sort);
	linksDetail(list, "Episodes", "episodes-heard", item.episodes);
	websiteButton(card, item.url);
	return card;
}

function episodeHeardCard(item) {
	const { card, list } = cardShell(item, item.podcast?.name || "", "cover");
	linksDetail(list, "Podcast", "podcasts", item.podcast ? [item.podcast] : []);
	linksDetail(list, "Episode", "podcast-episodes", item.episode ? [item.episode] : []);
	detail(list, "Heard", formatDate(item));
	rated(list, item);
	detail(list, "Where", item.listened_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	feedDetails(list, item);
	websiteButton(card, item.url, "Listen");
	return card;
}

// 3725 -> "1:02:05", 391 -> "6:31"
function formatDuration(seconds) {
	if (seconds === null) {
		return "";
	}
	const [h, m, s] = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
	const two = (n) => String(n).padStart(2, "0");
	return h ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

// What YouTube says of a video, in its dialog: only read, never typed (the
// YouTube importers refresh it). A new video, or one YouTube says nothing of,
// shows each with a dash, so the dialog is the same shape every time.
export function showYouTubeFacts(item) {
	const dash = (value) => (value === null || value === undefined || value === "" ? "\u2014" : String(value));
	const facts = [
		["Channel", item?.channel],
		["Category", item?.category],
		["Length", item?.duration == null ? null : formatDuration(item.duration)],
		["Uploaded", item?.uploaded],
		["Views", item?.views == null ? null : item.views.toLocaleString()],
		["On YouTube", item ? (item.unavailable ? "No longer" : "Yes") : null],
	];
	showFacts("youtube-facts", facts.map(([label, value]) => [label, dash(value)]));
}

// A podcast's episodes, in its dialog: how many its feed has, how many of
// them the user heard (0 too), the newest's date; a new podcast has none yet.
export function showPodcastFacts(item) {
	showFacts("podcast-facts", [
		["Episodes", String(item?.episodes ?? 0)],
		["Episodes you heard", String(item?.heard ?? 0)],
		["Latest episode", item?.published ? item.published.slice(0, 10) : "\u2014"],
	]);
}

function showFacts(id, facts) {
	$(id).replaceChildren(...facts.map(([label, value]) => {
		const fact = el("span", "fact");
		fact.append(el("span", "label", label), el("span", "value", value));
		return fact;
	}));
}

function youtubeCard(item) {
	// YouTube's own thumbnail (a grey one when the video is gone); one YouTube
	// no longer has may have no name: it goes by its id
	const shown = {
		...item,
		name: item.name || `Unavailable video ${item.youtube_id}`,
		image: `https://i.ytimg.com/vi/${item.youtube_id}/hqdefault.jpg`,
	};
	const { card, list } = cardShell(shown, item.channel);
	// the dialog edits the row as it is, with no name made up for it
	editable(card, item);
	if (item.unavailable) {
		detail(list, "Status", "No longer on YouTube");
	}
	detail(list, "Watched", formatDate(item));
	detail(list, "Category", item.category);
	detail(list, "Length", formatDuration(item.duration));
	detail(list, "Uploaded", item.uploaded);
	if (item.views !== null) {
		detail(list, "Views", item.views.toLocaleString());
	}
	if (item.rating !== null) {
		detail(list, "Rating", `${item.rating}/${state.config.rating_max}`);
	}
	detail(list, "Review", item.review);
	detail(list, "Where", item.watched_at);
	linksDetail(list, "Device", "devices", item.device ? [item.device] : []);
	websiteButton(card, `https://www.youtube.com/watch?v=${item.youtube_id}`, "On YouTube");
	return card;
}

function chessCard(item) {
	// its picture is where the pieces ended, seen from the side the user played; one with no move has none
	const shown = { ...item, image: item.plies && item.position ? boardImage(item.position, item.color === "black") : null };
	const side = item.color ? ` as ${SIDES[item.color]}` : "";
	const { card, list } = cardShell(shown, `${item.outcome}${side} against ${item.opponent}`, "logo");
	card.classList.add("is-board");
	editable(card, item);
	detail(list, "Played", formatDate(item));
	detail(list, "Result", item.result === "*" ? "No result" : item.result);
	detail(list, "Ended", item.termination);
	const rated = (elo) => (elo === null ? "unrated" : String(elo));
	if (item.rating !== null || item.opponent_rating !== null) {
		detail(list, "Ratings", `${rated(item.rating)} (me), ${rated(item.opponent_rating)} (${item.opponent})`);
	}
	detail(list, "Moves", item.plies ? String(Math.ceil(item.plies / 2)) : "Not recorded");
	detail(list, "Time control", item.time_control);
	detail(list, "Opening", [item.eco, item.opening].filter(Boolean).join(" "));
	detail(list, "Event", item.event);
	detail(list, "Site", item.site);
	detail(list, "Remark", item.remark);
	websiteButton(card, item.link, "The game online");
	return card;
}

// every view's card maker: each view has the List, Cards, Tiles and Gallery layouts
export const CARDS = {
	concerts: concertCard,
	museums: museumCard,
	"audio-courses": audioCourseCard,
	"audio-books": audioBookCard,
	podcasts: podcastCard,
	"podcast-episodes": podcastEpisodeCard,
	"podcasts-heard": podcastHeardCard,
	"episodes-heard": episodeHeardCard,
	youtube: youtubeCard,
	chess: chessCard,
	places: placeCard,
	cities: cityCard,
	countries: countryCard,
	currencies: currencyCard,
	"place-kinds": sharedNameCard,
	"visit-types": sharedNameCard,
	groups: groupCard,
	organizations: organizationCard,
	people: personCard,
	"organization-types": typeCard,
	"person-types": typeCard,
	"relation-types": typeCard,
	"person-relation-types": typeCard,
	"person-organization-types": typeCard,
	devices: typeCard,
	locales: localeCard,
};

// Material "link"
const LINK_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z"/></svg>';

// Everything that ties a person to the user, grouped, each entry a link to its card.
async function showConnections(person) {
	const [concerts, museums, courses, books, bands] = await Promise.all([
		// in a view, only what it shows
		...["concerts", "museums", "audio-courses"].map((view) => (inView(view) ? worldList(view) : [])),
		inView("book") ? api("/api/library-entries?kind=book") : [], inView("groups") ? worldList("groups") : [],
	]);
	const has = (list) => list.some((p) => p.id === person.id);
	// a book is known by its work: #book/<work id>
	const wrote = books.filter((b) => has(b.authors)).map((b) => ({ id: b.work_id, name: b.title }));
	const groups = [
		["Concerts you went to together", "concerts", concerts.filter((c) => has(c.people))],
		["Concerts they performed at", "concerts", concerts.filter((c) => has(c.performers))],
		["Museums you visited together", "museums", museums.filter((m) => has(m.people))],
		["Audio courses they taught", "audio-courses", courses.filter((c) => has(c.lecturers))],
		["Books they wrote", "book", wrote],
		["Groups they are in", "groups", bands.filter((g) => has(g.members))],
		// how they are related to other people, both ways; each links to the other person
		["Related people", "people", [...person.relations, ...person.related].map((r) => ({ id: r.person.id, name: r.name }))],
		["Organizations", "organizations", person.organization_links.map((link) => ({ id: link.organization.id, name: link.name }))],
	].filter(([, view, items]) => items.length > 0 && inView(view));
	$("connections-title").textContent = person.name;
	const body = $("connections-body");
	body.replaceChildren();
	if (groups.length === 0) {
		body.appendChild(el("p", "empty", "No concerts, museums, courses, books, groups or organizations link you yet."));
	}
	for (const [label, view, items] of groups) {
		body.appendChild(el("h3", null, `${label} (${items.length})`));
		const ul = el("ul");
		for (const item of items) {
			const li = el("li");
			const when = formatDate(item);
			if (when) {
				li.appendChild(el("span", "when", when));
			}
			const a = el("a", "person-link", item.name);
			a.href = pageHref(`${view}/${item.id}`);
			a.onclick = (event) => {
				event.preventDefault();
				$("connections-dialog").close();
				showRow(view, item.id).catch((e) => showError(e.message));
			};
			li.appendChild(a);
			ul.appendChild(li);
		}
		body.appendChild(ul);
	}
	$("connections-dialog").showModal();
}

// the pin's corner on a person's card: how they are connected to the user
function connectionsButton(person) {
	const button = el("button", "icon-button place-button");
	button.type = "button";
	button.title = `How you are connected to ${person.name}`;
	button.setAttribute("aria-label", button.title);
	button.innerHTML = LINK_ICON;
	button.onclick = () => showConnections(person).catch((e) => showError(e.message));
	return button;
}

function personCard(item) {
	const { card, list } = cardShell(item, item.description);
	cornerOf(card).appendChild(connectionsButton(item));
	// their names but the one shown (the one in the preferred language), each with its language
	const others = [{ locale: "en", name: item.english_name }, ...item.names].filter((n) => n.name && n.name !== item.name);
	detail(list, "Other names", others.map((n) => `${n.name} (${localeName(n.locale)})`).join("; "));
	linksDetail(list, "Profession", "person-types", item.types);
	// each with how they are linked: "Worked at Schema", "Mother of Dana"
	linksDetail(list, "Organizations", "organizations", item.organization_links.map((link) => ({ id: link.organization.id, name: link.name })));
	linksDetail(list, "Relations", "people", [...item.relations, ...item.related].map((r) => ({ id: r.person.id, name: r.name })));
	return card;
}

// what the rows of each enumeration view are counted in
const TYPE_COUNTS = {
	"organization-types": "Organizations",
	"person-types": "People",
	"relation-types": "Organizations",
	"person-relation-types": "Relations",
	"person-organization-types": "Links",
	devices: "Recordings",
};

// A language of the locales table: its code, the script it is written in, and how much is said in it
function localeCard(item) {
	// its picture is its own name in its own script
	const { card, list } = cardShell(item, item.native);
	detail(list, "Code", item.code);
	detail(list, "Script", item.script);
	// always shown, 0 too
	detail(list, "Used by", String(item.count));
	return card;
}

// A row of a shared list of names (place kinds, visit types): how many places are of it, or how many of
// the user's visits
function sharedNameCard(item) {
	const { card, list } = cardShell(item, "");
	detail(list, state.view === "place-kinds" ? "Places" : "Your visits", String(item.count));
	return card;
}

// A row of an enumeration (types, relation types, devices), with how many rows are of it;
// a person relation type also with how it reads the other way ("Mother of" / "Child of")
function typeCard(item) {
	const { card, body, list } = cardShell(item, item.description);
	if ("inverse" in item) {
		detail(list, "Other way", item.inverse || item.name);
	}
	// always shown, 0 too
	detail(list, TYPE_COUNTS[state.view], String(item.count));
	// a device has a photo of itself, a profession one of someone at that work
	photoCredit(body, item);
	return card;
}
