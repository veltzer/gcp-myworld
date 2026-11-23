/* globals TomSelect */
// The dialog a row is added and edited in: its adders, its pictures and its pickers.

import { $ } from "./core.js";
import { uploadPhoto } from "./forms.js";
import { el, fetchWorld, worldCache } from "./worlds.js";

// One dialog, opened by the + button, showing the form of whatever is on screen.
export const DIALOG_FORMS = ["add-form", "concert-form", "museum-visit-form", "audio-course-form", "audio-book-form", "audio-book-version-form", "audio-book-heard-form", "audio-book-listen-form", "podcast-form", "podcast-episode-form", "podcast-heard-form", "episode-heard-form", "film-form", "film-watch-form", "series-form", "series-watch-form", "youtube-video-form", "chess-game-form", "certification-form", "course-form", "loan-form", "website-form", "trip-form", "lecture-form", "rally-form", "place-form", "place-kind-form", "visit-type-form", "city-form", "country-form", "currency-form", "person-form", "group-form", "organization-form", "organization-tag-form", "profession-form", "relation-type-form", "person-relation-type-form", "person-org-relation-type-form", "device-form", "language-form"];

export const PHOTO_MAX_BYTES = 8 * 1024 * 1024;

export function dialogError(message) {
	const box = $("dialog-error");
	box.textContent = message;
	box.hidden = !message;
}

export async function worldList(view) {
	if (!worldCache[view]) {
		worldCache[view] = await fetchWorld(view);
	}
	return worldCache[view];
}

// A list in a dialog (titles, reads, names, relations, pictures, the chips of a
// picker) shows what there is, each with a − that takes it away, and one + that
// brings in the row to add another with (an "adder", hidden until then). The
// buttons that change things are red, here and everywhere.
export function toggleAdder(row, show = row.hidden) {
	row.hidden = !show;
	if (show) {
		// the box to type in; where a kind is chosen before a pick adds (a relation), the kind
		(row.querySelector("[data-first]") || row.querySelector("input:not([type=hidden])"))?.focus();
	}
}

// the + of a list: brings its adder in, or puts it away again
export function adderButton(row, label) {
	const button = el("button", "modify", "+");
	button.type = "button";
	button.title = label;
	button.setAttribute("aria-label", label);
	button.onclick = () => toggleAdder(row);
	return button;
}

// the − of one thing in a list
export function removeButton(label, onRemove) {
	const button = el("button", "modify chip-remove", "\u2212");
	button.type = "button";
	button.title = label;
	button.setAttribute("aria-label", label);
	button.onclick = onRemove;
	return button;
}

// The pictures of what the dialog edits: {id, image} (and a city photo's
// credit). A box marked data-pictures="many" keeps them all (a book's covers, a
// city's photos), the first being the one its card shows; any other keeps one,
// a new one taking its place. A file chosen is uploaded right away.
let editingPictures = [];

function renderPictures(form) {
	const box = form.querySelector("[data-pictures]");
	if (!box) {
		return;
	}
	const what = box.dataset.what;
	box.replaceChildren();
	if (editingPictures.length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingPictures.forEach((picture, index) => {
		const chip = el("span", "chip picture");
		const img = el("img");
		img.src = picture.image;
		img.alt = `The ${what}`;
		chip.title = [picture.image_author, picture.image_license, picture.image_source].filter(Boolean).join(", ");
		chip.append(img);
		if (box.dataset.pictures === "many") {
			// the first is the default, the one the card shows: the star of another puts it first
			const star = el("button", "modify chip-remove", "\u2605");
			star.type = "button";
			star.disabled = index === 0;
			star.title = index === 0 ? `The default ${what}: the one the card shows` : `Make this the default ${what}: the one the card shows`;
			star.setAttribute("aria-label", star.title);
			star.onclick = () => {
				editingPictures.unshift(...editingPictures.splice(index, 1));
				renderPictures(form);
			};
			chip.append(star);
		}
		chip.append(removeButton(`Remove this ${what}`, () => {
			editingPictures.splice(index, 1);
			renderPictures(form);
		}));
		box.appendChild(chip);
	});
	const one = box.dataset.pictures !== "many" && editingPictures.length > 0;
	box.appendChild(adderButton(form.querySelector("[data-picture-adder]"), one ? `Choose another ${what}, in place of this one` : `Add a ${what}`));
}

export function preparePictures(form, item) {
	const box = form.querySelector("[data-pictures]");
	if (!box) {
		return;
	}
	const all = item?.covers || item?.photos;
	editingPictures = all ? all.map((picture) => ({ ...picture })) : item?.image ? [{ id: Number(item.image.split("/").pop()), image: item.image }] : [];
	form.elements.photo.value = "";
	// a city's credit fields are those of the photo to add, not of one it has
	if (box.dataset.pictures === "many") {
		for (const field of form.querySelectorAll("[data-picture-adder] input:not([type=file])")) {
			field.value = "";
		}
	}
	renderPictures(form);
}

// the file chosen, uploaded and added to the pictures (with the credit typed beside it, where there is one)
async function addPicture(form) {
	const input = form.elements.photo;
	const file = input?.files[0];
	if (!file) {
		return;
	}
	const id = await uploadPhoto(file);
	const adder = form.querySelector("[data-picture-adder]");
	const picture = { id, image: `/api/images/${id}` };
	for (const field of adder.querySelectorAll("input:not([type=file])")) {
		picture[field.name] = field.value.trim();
		field.value = "";
	}
	if (form.querySelector("[data-pictures]").dataset.pictures !== "many") {
		editingPictures = [picture];
	} else if (!editingPictures.some((other) => other.id === id)) {
		editingPictures.push(picture);
	}
	input.value = "";
	adder.hidden = true;
	renderPictures(form);
}

// the pictures to send, with a file still chosen in the adder (saving does not lose it)
export async function pictures(form) {
	await addPicture(form);
	return editingPictures;
}

// the one picture of a form, as its API takes it: a new one, or its removal
export async function pictureBody(form) {
	const [picture] = await pictures(form);
	return { image_id: picture ? picture.id : null, image_remove: !picture };
}

export function setupPictures() {
	for (const adder of document.querySelectorAll("[data-picture-adder]")) {
		const form = adder.closest("form");
		const add = () => addPicture(form).catch((e) => dialogError(e.message));
		const button = adder.querySelector("[data-picture-add]");
		if (button) {
			button.onclick = add;
		} else {
			form.elements.photo.onchange = add;
		}
	}
	// a click on a list is not a click on its +: the label around them would pass it on
	for (const box of document.querySelectorAll(".dialog-form .chips")) {
		box.addEventListener("click", (event) => {
			if (!event.target.closest("button, a")) {
				event.preventDefault();
			}
		});
	}
}

// The grey line under a person in a picker: their types and description,
// since two people may share a name. A person with no name is called by the
// description already, so it is not repeated.
function pickerNote(row) {
	if (!("first_name" in row)) {
		return "";
	}
	const named = row.first_name || row.middle_name || row.surname;
	return [row.is_self && "you", (row.types || []).map((t) => t.name).join("/"), named && row.description?.slice(0, 60)].filter(Boolean).join(" · ");
}

// A person (or any row of a view) named in a dialog is a link to them. It opens
// here, as every link inside the application does (only a link to another site
// opens a tab of its own): the dialog closes, what was typed in it unsaved.
const DIALOG_LINK_TITLE = "Go there: this dialog closes, unsaved";

// a click on such a link: the dialog goes, and the link is followed in this tab
function leaveDialog() {
	$("add-dialog").close();
}

export function dialogLink(view, row) {
	const a = el("a", "person-link", row.name);
	a.dir = "auto";
	a.href = `/library#${view}/${row.id}`;
	a.title = DIALOG_LINK_TITLE;
	a.onclick = leaveDialog;
	return a;
}

// lists this long or shorter open on focus; longer ones only once something is typed
const PICKER_OPEN_ON_FOCUS = 15;

// A picker on a select: only rows that exist can be picked, the best few
// matches of what is typed are offered (a name before a note), and a
// multiple select gives removable chips. shown: how many matches are offered
// at once (null: all, for a short list where every choice should be seen).
export function makePicker(select, onChange, shown = 8) {
	const multiple = select.multiple;
	// a chosen row of a view (a person, a group, a profession) is a link to it, see dialogLink
	const view = select.dataset.chips;
	const item = (data, esc) => view
		? `<div><a class="person-link" href="/library#${esc(view)}/${esc(data.value)}" title="${esc(DIALOG_LINK_TITLE)}">${esc(data.text)}</a></div>`
		: `<div>${esc(data.text)}</div>`;
	const picker = new TomSelect(select, {
		maxItems: multiple ? null : 1,
		placeholder: select.dataset.placeholder,
		maxOptions: shown,
		// the rows are all in memory: filter on every key, so Enter right after typing picks from what was typed
		refreshThrottle: 0,
		create: false,
		hideSelected: true,
		closeAfterSelect: !multiple,
		searchField: [{ field: "text", weight: 2 }, { field: "sub", weight: 0.5 }],
		plugins: multiple ? { remove_button: { label: "\u2212", title: "Remove" } } : ["clear_button"],
		render: {
			option: (data, esc) => `<div class="picker-option"><span>${esc(data.text)}</span>${data.sub ? `<small>${esc(data.sub)}</small>` : ""}</div>`,
			item,
			no_results: (data, esc) => `<div class="no-results">No one matches “${esc(data.input)}”</div>`,
		},
		onChange: () => onChange?.(),
	});
	// a list of chips shows only what is chosen, each with its −; its + (a click anywhere
	// in the box does the same) brings in the box to type another in, which goes again
	// when the picker is left (style.css: the input shows only while it has the focus)
	if (multiple) {
		const add = el("button", "modify picker-add", "+");
		add.type = "button";
		add.title = "Add one: type a name and pick it";
		add.setAttribute("aria-label", add.title);
		add.onclick = () => picker.focus();
		picker.control.appendChild(add);
	}
	// the picker takes a click on a chip for itself (it selects the chip) and cancels it: a click
	// on the chip's link is kept from it, here on the way down, so the link opens
	picker.wrapper.addEventListener("click", (event) => {
		if (event.target.closest("a.person-link")) {
			event.stopPropagation();
			leaveDialog();
		}
	}, true);
	return picker;
}

// What a picker offers: rows of a view, by name (or label), each with its note
export function setPickerRows(select, rows, label = (row) => row.name) {
	const picker = select.tomselect;
	picker.clear(true);
	picker.clearOptions();
	picker.addOptions(rows.map((row) => ({ value: String(row.id), text: label(row), sub: pickerNote(row) })));
	picker.settings.openOnFocus = rows.length <= PICKER_OPEN_ON_FOCUS;
	picker.refreshOptions(false);
}

export function setPickerValue(select, ids) {
	select.tomselect.setValue(ids.map(String), true);
}

// "I went alone" and the With picker exclude each other: with people chosen the
// box is disabled, and with the box ticked the picker is.
export function syncAlone(form) {
	const alone = form?.elements.alone;
	if (!alone) {
		return;
	}
	const picker = form.querySelector("[data-field=people]").tomselect;
	alone.disabled = picker.items.length > 0;
	if (alone.checked) {
		picker.disable();
	} else {
		picker.enable();
	}
}
