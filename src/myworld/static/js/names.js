// Names and titles in languages, and the names of a person.

import { $ } from "./core.js";
import { adderButton, dialogError, removeButton, toggleAdder } from "./dialog.js";
import { state } from "./library.js";
import { el } from "./worlds.js";

// A list of links of the person being edited, each a kind and a row of a view
// ("Mother of" Dana, "Worked at" Schema), shown as removable chips; a row
// picked in the picker is added with the kind chosen beside it.
// field names the row in each link ("person", "organization").

// The dialogs' lists of what is said in several languages, one per language: a
// person's names in other languages than English, and a book's titles.
export const LOCALIZED = {
	// a book has one title per language
	titles: { box: "book-titles", row: "book-title-row", locale: "book-title-locale", text: "book-title-text", add: "book-title-add", field: "title" },
};

export const editingLocalized = { titles: [] };

export function localeName(code) {
	return state.config.locales[code] || code;
}

function optionOf(value, text) {
	const option = document.createElement("option");
	option.value = value;
	option.textContent = text;
	return option;
}

// every select marked data-locales: the languages, but data-skip's, after data-blank's empty choice
export function fillLocales() {
	for (const select of document.querySelectorAll("select[data-locales]")) {
		const options = Object.entries(state.config.locales).filter(([code]) => code !== select.dataset.skip).map(([code, name]) => optionOf(code, name));
		if (select.dataset.blank) {
			options.unshift(optionOf("", select.dataset.blank));
		}
		select.replaceChildren(...options);
	}
}

// the script most of the letters of text are in ("Hebrew"), of those the languages are written in; "" with no such letters
function scriptOf(text) {
	let best = "";
	let most = 0;
	for (const script of new Set(Object.values(state.config.locale_scripts))) {
		const count = (text.match(new RegExp(`\\p{Script=${script}}`, "gu")) || []).length;
		if (count > most) {
			best = script;
			most = count;
		}
	}
	return best;
}

// what is typed is in the language it says: when its letters are not that language's
// (a Hebrew title, "English" chosen), choose the first language of its letters the select offers
export function pickLocale(select, text) {
	const scripts = state.config.locale_scripts;
	const script = scriptOf(text);
	if (select.disabled || !script || scripts[select.value] === script) {
		return;
	}
	const fitting = Array.from(select.options).find((option) => scripts[option.value] === script);
	if (fitting) {
		select.value = fitting.value;
	}
}

// the boxes of the row a name is typed in, by the part each holds
const NAME_BOXES = { honorific: "person-name-honorific", first_name: "person-name-first", middle_name: "person-name-middle", surname: "person-name-surname" };

// the names in the dialog: {locale, honorific, first_name, middle_name, surname}; the
// English one is the person's own name parts, the others their names in other languages
let editingNames = [];

// the name the row is editing (its place in the list), null when the row adds one
export let editingName = null;

function wholeName(name) {
	return Object.keys(NAME_BOXES).map((part) => name[part]).filter(Boolean).join(" ");
}

// the row's boxes show this name; a new one is in the first language the person has no name in
function fillNameRow(name) {
	const taken = new Set(editingNames.map((other) => other.locale));
	$("person-name-locale").value = name ? name.locale : Object.keys(state.config.locales).find((code) => !taken.has(code)) || "en";
	for (const [part, box] of Object.entries(NAME_BOXES)) {
		$(box).value = name?.[part] || "";
	}
	$("person-name-add").textContent = name ? "Update" : "Add";
}

// the row comes in to add a name (index null) or to edit the one at index; asked again for the same, it goes away
function openNameRow(index) {
	const row = $("person-name-row");
	if (!row.hidden && editingName === index) {
		row.hidden = true;
		return;
	}
	editingName = index;
	fillNameRow(index === null ? null : editingNames[index]);
	toggleAdder(row, true);
}

function renderNames() {
	const box = $("person-names");
	box.replaceChildren();
	if (editingNames.length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingNames.forEach((name, index) => {
		const chip = el("span", "chip");
		const words = el("span", null, wholeName(name));
		words.dir = "auto";
		chip.append(`${localeName(name.locale)}: `, words);
		const edit = el("button", "modify chip-remove", "\u270e");
		edit.type = "button";
		edit.title = `Edit the name ${wholeName(name)}`;
		edit.setAttribute("aria-label", edit.title);
		edit.onclick = () => openNameRow(index);
		chip.appendChild(edit);
		chip.appendChild(removeButton(`Remove the name ${wholeName(name)}`, () => {
			editingNames.splice(index, 1);
			editingName = null;
			$("person-name-row").hidden = true;
			renderNames();
		}));
		box.appendChild(chip);
	});
	const add = el("button", "modify", "+");
	add.type = "button";
	add.title = "Add a name in another language";
	add.setAttribute("aria-label", add.title);
	add.onclick = () => openNameRow(null);
	box.appendChild(add);
}

// what the row says becomes a name of the list: a new one, or the one it was editing. A row
// left empty adds nothing. False when it cannot be (a part of two words, a second name in a
// language), and the dialog says why.
export function addName() {
	const name = { locale: $("person-name-locale").value };
	for (const [part, box] of Object.entries(NAME_BOXES)) {
		name[part] = $(box).value.trim().split(/\s+/).join(" ");
	}
	if (wholeName(name)) {
		for (const part of ["honorific", "first_name", "surname"]) {
			if (/\s/.test(name[part])) {
				dialogError("The honorific, the first name and the surname are one word each: more names go in the middle name");
				return false;
			}
		}
		if (editingNames.some((other, index) => other.locale === name.locale && index !== editingName)) {
			dialogError(`There is already a name in ${localeName(name.locale)}: one per language (its pencil edits it)`);
			return false;
		}
		if (editingName === null) {
			editingNames.push(name);
		} else {
			editingNames[editingName] = name;
		}
	}
	editingName = null;
	$("person-name-row").hidden = true;
	renderNames();
	return true;
}

// someone new starts with the row in, to say their English name; someone edited with their names listed
export function prepareNames(person) {
	const english = { locale: "en", honorific: person?.honorific || "", first_name: person?.first_name || "", middle_name: person?.middle_name || "", surname: person?.surname || "" };
	editingNames = [...(wholeName(english) ? [english] : []), ...(person?.names || []).map((name) => ({
		locale: name.locale, honorific: name.honorific || "", first_name: name.first_name || "", middle_name: name.middle_name || "", surname: name.surname || "",
	}))];
	editingName = null;
	fillNameRow(null);
	$("person-name-row").hidden = Boolean(person);
	renderNames();
}

// what to send of the names, with what the row says while it is in (saving does not lose
// it): the English one as the person's name parts, the others as their names. Null when
// the row's name cannot be.
function namesValues() {
	if (!$("person-name-row").hidden && !addName()) {
		return null;
	}
	const english = editingNames.find((name) => name.locale === "en");
	const parts = Object.fromEntries(Object.keys(NAME_BOXES).map((part) => [part, english?.[part] || ""]));
	return { ...parts, names: editingNames.filter((name) => name.locale !== "en").map((name) => ({ ...name })) };
}

export function renderLocalized(key) {
	const { box: boxId, row, field, first } = LOCALIZED[key];
	const box = $(boxId);
	box.replaceChildren();
	// the name that is not of this list (a person's English one), shown with the others, none set apart
	const fixed = first?.();
	if (fixed) {
		const chip = el("span", "chip kept");
		const words = el("span", null, fixed);
		words.dir = "auto";
		chip.append(`${localeName("en")}: `, words);
		box.appendChild(chip);
	}
	if (editingLocalized[key].length === 0 && !fixed) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingLocalized[key].forEach((item, index) => {
		const chip = el("span", item.kept ? "chip kept" : "chip");
		const words = el("span", null, item.text);
		words.dir = "auto";
		chip.append(`${localeName(item.locale)}: `, words);
		if (!item.kept) {
			chip.appendChild(removeButton(`Remove ${item.text}`, () => {
				editingLocalized[key].splice(index, 1);
				renderLocalized(key);
			}));
		}
		box.appendChild(chip);
	});
	box.appendChild(adderButton($(row), `Add a ${field} in another language`));
}

// the names to send, or the save stops: the dialog already says what is wrong with the row's name
export function namesOrStop() {
	const names = namesValues();
	if (names === null) {
		throw new Error($("dialog-error").textContent || "The name cannot be added as it is");
	}
	return names;
}

// what is typed in the editor's box, added to its list (a person's name in a language replacing the one they had in it)
export function addLocalized(key) {
	const { locale: localeId, text: textId, field } = LOCALIZED[key];
	const text = $(textId).value.trim().split(/\s+/).join(" ");
	pickLocale($(localeId), text);
	const locale = $(localeId).value;
	if (!locale || !text) {
		return;
	}
	const list = editingLocalized[key];
	// one per language: what is kept (a work's title) is not replaced
	if (list.some((item) => item.kept && item.locale === locale)) {
		dialogError(`There is already a ${field} in ${localeName(locale)}: one per language`);
		return;
	}
	// what was typed for this language before is replaced
	editingLocalized[key] = list.filter((item) => item.locale !== locale);
	editingLocalized[key].push({ locale, text, kept: false });
	$(textId).value = "";
	$(LOCALIZED[key].row).hidden = true;
	renderLocalized(key);
}

export function prepareLocalized(key, items, kept) {
	const { field, text } = LOCALIZED[key];
	editingLocalized[key] = items.map((item) => ({ locale: item.locale, text: item[field], kept }));
	$(text).value = "";
	renderLocalized(key);
}

// the list to send, with anything still typed in the box (saving does not lose it)
export function localizedValues(key) {
	addLocalized(key);
	const { field } = LOCALIZED[key];
	return editingLocalized[key].map((item) => ({ locale: item.locale, [field]: item.text }));
}
