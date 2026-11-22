// The forms of the dialog: what each page's form shows and what it sends.

import { play } from "./board.js";
import { $, api } from "./core.js";
import { PHOTO_MAX_BYTES, adderButton, dialogError, dialogLink, pictureBody, pictures, removeButton, setPickerRows, setPickerValue, syncAlone, worldList } from "./dialog.js";
import { movieIdsReset } from "./films.js";
import { state } from "./library.js";
import { LOCALIZED, addLocalized, addName, editingName, fillLocales, localeName, namesOrStop, pickLocale, prepareLocalized } from "./names.js";
import { addRead, prepareReads } from "./readings.js";
import { refreshWorld } from "./views.js";
import { addVisit, visitsValues } from "./visits.js";
import { WORLDS, el, slug } from "./worlds.js";

// the languages (locale codes) the book in the dialog is owned in
let editingOwned = [];

function renderOwned() {
	const box = $("book-owned");
	box.replaceChildren();
	if (editingOwned.length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingOwned.forEach((code, index) => {
		const chip = el("span", "chip", localeName(code));
		chip.appendChild(removeButton(`No longer owned in ${localeName(code)}`, () => {
			editingOwned.splice(index, 1);
			renderOwned();
		}));
		box.appendChild(chip);
	});
	box.appendChild(adderButton($("book-owned-row"), "Add a language you own it in"));
}

// the language chosen in the row joins the list (once), and the row goes
function addOwned() {
	const code = $("book-owned-locale").value;
	if (code && !editingOwned.includes(code)) {
		editingOwned.push(code);
	}
	$("book-owned-row").hidden = true;
	renderOwned();
}

function prepareOwned(owned) {
	editingOwned = [...owned];
	renderOwned();
}

// the languages to send, with the one chosen in the row while it is in (saving does not lose it)
export function ownedValues() {
	if (!$("book-owned-row").hidden) {
		addOwned();
	}
	return [...editingOwned];
}

// The × of a row that adds something: puts the row away again, nothing added (a
// change of mind). Every such row of every dialog has one, after what it holds.
function setupAdderClose() {
	for (const adder of document.querySelectorAll(".adder")) {
		const close = el("button", "modify adder-close", "\u00d7");
		close.type = "button";
		close.title = "Never mind: put this away, adding nothing";
		close.setAttribute("aria-label", close.title);
		close.onclick = () => {
			adder.hidden = true;
		};
		// a row holds it itself; a block of rows, its last row
		const rows = adder.querySelectorAll(".row");
		(adder.classList.contains("row") || rows.length === 0 ? adder : rows[rows.length - 1]).appendChild(close);
	}
}

// Add, and Enter in the box, add what is typed; Enter never saves the form
export function setupLocalized() {
	fillLocales();
	$("book-read-add").onclick = () => addRead();
	$("book-owned-add").onclick = () => addOwned();
	$("museum-visit-add").onclick = () => addVisit();
	setupAdderClose();
	$("person-name-add").onclick = () => addName();
	// the language of a name being added follows its letters as they are typed
	$("person-name-first").addEventListener("input", () => {
		if (editingName === null) {
			pickLocale($("person-name-locale"), $("person-name-first").value);
		}
	});
	for (const [key, { add, text, locale }] of Object.entries(LOCALIZED)) {
		$(add).onclick = () => addLocalized(key);
		$(text).addEventListener("input", () => pickLocale($(locale), $(text).value));
		$(text).addEventListener("keydown", (event) => {
			if (event.key === "Enter") {
				event.preventDefault();
				addLocalized(key);
			}
		});
	}
}

const editingLinks = { relations: [], organization_links: [] };

function renderLinks(key, boxId, field, rowId) {
	const box = $(boxId);
	box.replaceChildren();
	if (editingLinks[key].length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingLinks[key].forEach((link, index) => {
		// "Friend of" and who, a link to them (a person, or an organization)
		const chip = el("span", "chip");
		const words = el("span");
		words.append(`${link.type} `, dialogLink(field === "person" ? "people" : "organizations", link[field]));
		chip.appendChild(words);
		chip.appendChild(removeButton(`Remove ${link.type} ${link[field].name}`, () => {
			editingLinks[key].splice(index, 1);
			renderLinks(key, boxId, field, rowId);
		}));
		box.appendChild(chip);
	});
	box.appendChild(adderButton($(rowId), field === "person" ? "Add a relation" : "Add an organization"));
}

async function prepareLinks({ key, boxId, rowId, kindId, pickerId, kindsView, rowsView, field, current, exclude = null, label = (row) => row.name }) {
	const [kinds, rows] = await Promise.all([worldList(kindsView), worldList(rowsView)]);
	editingLinks[key] = (current || []).map((link) => ({ ...link }));
	$(kindId).replaceChildren(...kinds.map((k) => {
		const option = document.createElement("option");
		option.value = k.id;
		option.textContent = k.name;
		return option;
	}));
	const offered = rows.filter((row) => row.id !== exclude);
	const select = $(pickerId);
	setPickerRows(select, offered, label);
	const picker = select.tomselect;
	if (kinds.length) {
		picker.enable();
	} else {
		picker.disable();
	}
	picker.off("change");
	picker.on("change", (value) => {
		const row = offered.find((r) => String(r.id) === value);
		const kind = kinds.find((k) => String(k.id) === $(kindId).value);
		if (!row || !kind) {
			return;
		}
		if (!editingLinks[key].some((link) => link.type_id === kind.id && link[field].id === row.id)) {
			editingLinks[key].push({ type_id: kind.id, type: kind.name, [field]: { id: row.id, name: row.name } });
		}
		picker.clear(true);
		$(rowId).hidden = true;
		renderLinks(key, boxId, field, rowId);
	});
	renderLinks(key, boxId, field, rowId);
}

// The person form's two link editors: relations to people (never to oneself) and links to organizations
export async function preparePersonLinks(item) {
	await prepareLinks({
		key: "relations", boxId: "person-relations", rowId: "person-relation-row", kindId: "relation-type", pickerId: "relation-person",
		kindsView: "person-relation-types", rowsView: "people", field: "person", current: item?.relations, exclude: item?.id,
	});
	await prepareLinks({
		key: "organization_links", boxId: "person-organization-links", rowId: "person-organization-row", kindId: "organization-link-type", pickerId: "organization-link-organization",
		kindsView: "person-organization-types", rowsView: "organizations", field: "organization", current: item?.organization_links,
	});
}

// The date pickers of a form, from the date in their hidden field (YYYY,
// YYYY-MM, YYYY-MM-DD or a timestamp): the picker always holds a real day,
// and the precision says how much of it is known.
export function syncDatePicks(form) {
	for (const box of form.querySelectorAll(".date-pick")) {
		const value = box.querySelector("input[type=hidden]").value;
		const [year, month, day] = value.split(/[-T]/);
		box.dataset.original = value;
		box.querySelector(".date-precision").value = !value || day ? "day" : month ? "month" : "year";
		box.querySelector(".date-day").value = value ? `${year}-${month || "01"}-${day || "01"}` : "";
	}
}

// Picking a day, or changing how much of it is known, writes the hidden
// field: only ever a legal date. A date left as it was keeps its time.
export function setupDatePicks() {
	for (const box of document.querySelectorAll(".date-pick")) {
		const hidden = box.querySelector("input[type=hidden]");
		const picker = box.querySelector(".date-day");
		const precision = box.querySelector(".date-precision");
		const update = () => {
			const [year, month] = picker.value.split("-");
			const value = !picker.value ? "" : { year, month: `${year}-${month}`, day: picker.value }[precision.value];
			hidden.value = value && value === box.dataset.original?.slice(0, 10) ? box.dataset.original : value;
		};
		picker.addEventListener("input", update);
		precision.addEventListener("change", update);
	}
}

export function resetForm(form) {
	form.reset();
	for (const select of form.querySelectorAll("[data-chips]")) {
		select.tomselect.clear(true);
	}
	syncAlone(form);
}

// the one picture of a form and its credit, as the country and group forms send them
async function pictureFields(form) {
	return {
		...(await pictureBody(form)),
		image_source: form.elements.image_source.value,
		image_license: form.elements.image_license.value,
		image_author: form.elements.image_author.value,
	};
}

// an image file, stored: the id it is known by
export async function uploadPhoto(file) {
	if (file.size > PHOTO_MAX_BYTES) {
		throw new Error("The photo is larger than 8 MB.");
	}
	const data = new FormData();
	data.append("file", file);
	const response = await fetch("/api/images", { method: "POST", body: data });
	const result = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(result.error || response.statusText);
	}
	return result.id;
}

// the ids picked in the chips box of field ("people", "performers", "organizations")
export function chosen(form, field) {
	return form.querySelector(`[data-field=${field}]`).tomselect.getValue().map(Number);
}

export function where() {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
	} catch (e) {
		return "";
	}
}

// view -> what its form posts
const WORLD_BODIES = {
	"audio-courses": async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			lecturers: chosen(form, "lecturers"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			review: value("review"),
			device_id: value("device_id"),
			listened_at: value("listened_at"),
			started: value("started"),
			ended: state.editing?.ended || "",
			progress: value("progress"),
			great_courses_id: value("great_courses_id"),
			great_courses_slug: value("great_courses_slug"),
			audible_asin: value("audible_asin"),
			link: value("link"),
			...(await pictureBody(form)),
		};
	},
	"audio-books": async (form) => Object.fromEntries(["name", "subtitle", "authors", "series", "series_sequence"].map((name) => [name, form.elements[name].value])),
	"audio-book-versions": async (form) => ({
		...Object.fromEntries(["book_id", "kind", "narrators", "minutes", "parts", "asin", "released", "genres"].map((name) => [name, form.elements[name].value])),
		...(await pictureBody(form)),
	}),
	"audio-books-heard": async (form) => Object.fromEntries(["book_id", "rating", "review"].map((name) => [name, form.elements[name].value])),
	"audio-book-listens": async (form) => {
		const body = Object.fromEntries(["version_id", "percent_heard", "date", "started", "progress", "device_id", "listened_at"].map((name) => [name, form.elements[name].value]));
		return { ...body, finished: form.elements.finished.checked, date_timezone: state.editing?.date_timezone || where() };
	},
	podcasts: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			url: value("url"),
			rss_feed: value("rss_feed"),
			...(await pictureBody(form)),
		};
	},
	"podcast-episodes": async (form) => Object.fromEntries(["podcast_id", "name", "number", "published", "duration", "episode_type", "explicit", "author",
		"description", "enclosure_url", "image_url", "guid"].map((name) => [name, form.elements[name].value])),
	"podcasts-heard": async (form) => Object.fromEntries(["podcast_id", "rating", "review"].map((name) => [name, form.elements[name].value])),
	"episodes-heard": async (form) => {
		const body = Object.fromEntries(["episode_id", "date", "rating", "review", "device_id", "listened_at"].map((name) => [name, form.elements[name].value]));
		return { ...body, date_timezone: state.editing?.date_timezone || where() };
	},
	youtube: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			youtube_id: value("youtube_id"),
			name: value("name"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			rating: value("rating"),
			review: value("review"),
			device_id: value("device_id"),
			watched_at: value("watched_at"),
		};
	},
	chess: async (form) => ({
		// the game's text is what it is added by; one that exists keeps its own
		...(state.editing ? {} : { pgn: form.elements.pgn.value }),
		color: form.elements.color.value,
		remark: form.elements.remark.value,
	}),
	concerts: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			event: value("event"),
			performers: chosen(form, "performers"),
			groups: chosen(form, "groups"),
			genre: value("genre"),
			date: value("date"),
			date_timezone: state.editing?.date_timezone || where(),
			place_id: value("place_id"),
			people: chosen(form, "people"),
			tickets: value("tickets"),
			broadcast: form.elements.broadcast.checked,
			alone: form.elements.alone.checked,
			review: value("review"),
			remark: value("remark"),
			...(await pictureBody(form)),
			image_source: value("image_source"),
			image_license: value("image_license"),
			image_author: value("image_author"),
		};
	},
	museums: async (form) => {
		const value = (name) => form.elements[name].value;
		// every visit of the museum, each with its day, rating, review and company
		const visits = visitsValues();
		if (visits === null) {
			throw new Error("A visit's rating or tickets is not a number: put it right");
		}
		// the museum is a shared place: only which one, and the user's visits to it
		return { place_id: value("place_id"), visits };
	},
	groups: async (form) => ({
		name: form.elements.name.value,
		members: chosen(form, "members"),
		description: form.elements.description.value,
		website: form.elements.website.value,
		...(await pictureFields(form)),
	}),
	cities: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			region: value("region"),
			country_id: value("country_id"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			population: value("population"),
			// all its photos, each with its credit: the first is the one its card shows
			photos: (await pictures(form)).map((photo) => ({
				image_id: photo.id, image_source: photo.image_source || "", image_license: photo.image_license || "", image_author: photo.image_author || "",
			})),
		};
	},
	currencies: async (form) => {
		const value = (name) => form.elements[name].value;
		return { code: value("code"), name: value("name"), symbol: value("symbol"), digits: value("digits") };
	},
	"place-kinds": async (form) => ({ name: form.elements.name.value }),
	"visit-types": async (form) => ({ name: form.elements.name.value }),
	countries: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"), code: value("code"), code3: value("code3"), currency_ids: chosen(form, "currencies"),
			latitude: value("latitude"), longitude: value("longitude"), ...(await pictureFields(form)),
		};
	},
	places: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			city_id: value("city_id"),
			street: value("street"),
			neighbourhood: value("neighbourhood"),
			postcode: value("postcode"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			website: value("website"),
			kinds: chosen(form, "kinds"),
			...(await pictureFields(form)),
		};
	},
	people: async (form) => ({
		// every name in its parts: the English one is the person's own, the others their names in other languages
		...namesOrStop(),
		// all their photos, each with its credit: the first is the default, the one their card shows
		photos: (await pictures(form)).map((photo) => ({
			image_id: photo.id, image_source: photo.image_source || "", image_license: photo.image_license || "", image_author: photo.image_author || "",
		})),
		type_ids: chosen(form, "types"),
		relations: editingLinks.relations.map((r) => ({ type_id: r.type_id, person_id: r.person.id })),
		organization_links: editingLinks.organization_links.map((l) => ({ type_id: l.type_id, organization_id: l.organization.id })),
		description: form.elements.description.value,
	}),
	organizations: async (form) => {
		const value = (name) => form.elements[name].value;
		return {
			name: value("name"),
			type_id: value("type_id"),
			relation_ids: chosen(form, "relations"),
			status: value("status"),
			website: value("website"),
			location: value("location"),
			headquarters_id: value("headquarters_id"),
			city_id: value("city_id"),
			street: value("street"),
			neighbourhood: value("neighbourhood"),
			postcode: value("postcode"),
			latitude: value("latitude"),
			longitude: value("longitude"),
			what_happened: value("what_happened"),
			remark: value("remark"),
			...(await pictureBody(form)),
		};
	},
	"organization-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"person-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
		...(await pictureFields(form)),
	}),
	"relation-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"person-organization-types": async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
	}),
	"person-relation-types": async (form) => ({
		name: form.elements.name.value,
		inverse: form.elements.inverse.value,
		description: form.elements.description.value,
	}),
	devices: async (form) => ({
		name: form.elements.name.value,
		description: form.elements.description.value,
		...(await pictureFields(form)),
	}),
	locales: async (form) => ({
		code: form.elements.code.value,
		name: form.elements.name.value,
		script: form.elements.script.value,
		native: form.elements.native.value,
	}),
};

// The regions there are, offered as the Region box of a city is typed in: one written as another is, is that one.
async function offerRegions() {
	const names = new Set((await api("/api/regions")).map((region) => region.name));
	$("region-names").replaceChildren(...[...names].sort().map((name) => {
		const option = document.createElement("option");
		option.value = name;
		return option;
	}));
}

// What follows a row saved, for the views that have something: a chess game added has
// its moves played here (the server only reads them), which says where its pieces
// ended: the picture of its card. A game whose site said so already has it.
const AFTER_SAVE = {
	chess: async (saved, path) => {
		// (a game with no move has no position to show)
		if (saved.position || !saved.plies) {
			return;
		}
		const game = await api(`${path}/${saved.id}`);
		const { positions } = play(game.moves);
		await api(`${path}/${saved.id}`, { method: "PUT", body: { color: saved.color, remark: saved.remark, final_position: positions[positions.length - 1] } });
	},
};

export function setupWorldForm(view) {
	const path = WORLDS[view][1];
	const form = $(`${slug(view)}-form`);
	if (view === "cities") {
		form.elements.region.addEventListener("focus", () => offerRegions().catch((e) => dialogError(e.message)));
	}
	form.onsubmit = async (event) => {
		event.preventDefault();
		dialogError("");
		const submit = form.querySelector("button[type=submit]");
		submit.disabled = true;
		try {
			const body = await WORLD_BODIES[view](form);
			const saved = state.editing ? await api(`${path}/${state.editing.id}`, { method: "PUT", body }) : await api(path, { method: "POST", body });
			await AFTER_SAVE[view]?.(saved, path);
			$("add-dialog").close();
			await refreshWorld();
		} catch (e) {
			dialogError(e.message);
		} finally {
			submit.disabled = false;
		}
	};
}

export function fillWorldForm(form, item) {
	for (const element of form.elements) {
		if (!element.name || element.type === "file") {
			continue;
		}
		const value = item[element.name];
		if (element.type === "checkbox") {
			element.checked = Boolean(value);
		} else if (Array.isArray(value)) {
			element.value = value.join(", ");
		} else {
			element.value = value ?? "";
		}
	}
	for (const select of form.querySelectorAll("[data-chips]")) {
		setPickerValue(select, item[select.dataset.field].map((row) => row.id));
	}
	if (form.elements.type_id) {
		form.elements.type_id.value = item.type ? item.type.id : "";
	}
}

// The work form: a new entry starts empty (with the film search for films); an
// existing one shows its work.
export async function prepareWorkForm(form, entry) {
	const film = state.config.tmdb && state.kind === "film" && !entry;
	if (state.config.tmdb) {
		movieIdsReset();
	}
	$("movie-search").hidden = !film;
	$("movie-ids").hidden = !film;
	$("movie-results").hidden = true;
	$("movie-hint").hidden = true;
	$("movie-query").value = "";
	const values = entry || { creator: "", year: "", notes: "" };
	for (const name of ["creator", "year", "notes"]) {
		form.elements[name].value = values[name] ?? "";
	}
	// its reads, and every title it has, each in its language; a new book starts with the row to type its title in
	prepareReads(entry?.reads || [], !entry);
	prepareOwned(entry?.owned || []);
	// the language it was first written in; it and the year released are locked like every box (lockFields)
	$("book-original").value = entry?.original_locale || "";
	prepareLocalized("titles", entry ? [{ locale: entry.title_locale, title: entry.main_title }, ...entry.titles] : [], false);
	$("book-title-row").hidden = Boolean(entry);
	// a book's authors are the user's people, any number of them; the picker
	// stays in its place for the other kinds, disabled
	const authors = $("book-authors").tomselect;
	setPickerRows($("book-authors"), await worldList("people"));
	setPickerValue($("book-authors"), (entry?.authors || []).map((a) => a.id));
	if (state.kind === "book") {
		authors.enable();
	} else {
		authors.disable();
	}
}

// The organization dialog's type list: the user's own organization types, and "none".
export async function fillTypes(select, typesView, label = (t) => t.name) {
	const types = await worldList(typesView);
	const none = document.createElement("option");
	none.value = "";
	none.textContent = "(none)";
	select.replaceChildren(none, ...types.map((t) => {
		const option = document.createElement("option");
		option.value = t.id;
		option.textContent = label(t);
		return option;
	}));
}
