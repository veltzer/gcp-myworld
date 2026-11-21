// Read only until its pencil is pressed.

import { prepareBoard, setupBoard } from "./board.js";
import { PICKER_LABELS, showYouTubeFacts } from "./cards.js";
import { $, VISIT, api, showError } from "./core.js";
import { DIALOG_FORMS, dialogError, makePicker, preparePictures, setPickerRows, setPickerValue, syncAlone, worldList } from "./dialog.js";
import { fillTypes, fillWorldForm, preparePersonLinks, prepareWorkForm, resetForm, setupWorldForm, syncDatePicks } from "./forms.js";
import { loadEntries, state } from "./library.js";
import { prepareNames } from "./names.js";
import { refreshWorld } from "./views.js";
import { prepareVisits } from "./visits.js";
import { TYPED, WORLDS, canChange, el, isAdmin, sharedLockedWhy, slug } from "./worlds.js";

// What a dialog shows of something that exists is there to read: every box that
// holds a value is locked, and the red pencil beside it lets it be changed; the
// pencil is then a red × that puts back what was there and locks it again. A
// box with nothing in it yet, and every box of something being added, just
// takes what is typed. Lists of chips are not locked: nothing in them changes
// without their own +, pencil or −.

// Every box of the dialog gets its pencil, once: a text or number box, a
// choice, a picker of one row, a date, a tick box.
export function setupLocks(dialog) {
	for (const label of dialog.querySelectorAll("label")) {
		if (label.closest(".adder, #movie-search, #movie-ids") || label.querySelector(".chips, [data-chips]")) {
			continue;
		}
		// its box is inside it, or (Settings) named by it
		const control = label.htmlFor ? $(label.htmlFor) : label.querySelector(".date-pick") || label.querySelector("input:not([type=hidden]):not([type=file]), select");
		if (!control) {
			continue;
		}
		const what = label.textContent.trim().split("\n")[0].trim();
		const pencil = el("button", "modify lock-edit", "\u270E");
		pencil.type = "button";
		pencil.title = `Edit ${what}`;
		pencil.setAttribute("aria-label", pencil.title);
		let box = control;
		if (label.classList.contains("check")) {
			box = label;
		} else if (!control.matches(".date-pick")) {
			box = el("span", "lockable");
			control.replaceWith(box);
			box.appendChild(control);
		}
		box.classList.add("lock-box");
		box.appendChild(pencil);
		pencil.dataset.edit = pencil.title;
		pencil.dataset.discard = `Put ${what} back as it was`;
		pencil.onclick = () => {
			const controls = lockControls(box);
			if (box.classList.contains("editing")) {
				// the ×: what was there comes back, locked again
				controls.forEach((control, index) => {
					if (control.tomselect) {
						control.tomselect.setValue(box.saved[index], true);
					} else if (control.type === "checkbox") {
						control.checked = box.saved[index];
					} else {
						control.value = box.saved[index];
					}
					// what follows a box (a date's hidden field, I went alone and its picker) follows it back
					control.dispatchEvent(new Event(control.tagName === "SELECT" || control.type === "checkbox" ? "change" : "input", { bubbles: true }));
				});
				setLocked(box, true);
				return;
			}
			// the pencil: the box is freed, and until the form is saved the pencil is a × that regrets it
			box.saved = controls.map((control) => control.tomselect ? [...control.tomselect.items] : control.type === "checkbox" ? control.checked : control.value);
			setLocked(box, false);
			box.classList.add("editing");
			pencil.textContent = "\u00D7";
			pencil.title = pencil.dataset.discard;
			pencil.setAttribute("aria-label", pencil.title);
			pencil.disabled = false;
			(controls[0].tomselect || controls[0]).focus();
		};
	}
}

// the boxes of a lock box that hold its value (not the box a picker types in)
function lockControls(box) {
	return [...box.querySelectorAll("input:not([type=hidden]), select")].filter((control) => !control.closest(".ts-wrapper"));
}

// Locked, a box is not typed into, changed or stopped at by Tab; the text of
// one that holds text can still be selected and copied.
function setLocked(box, locked) {
	box.classList.toggle("locked", locked);
	for (const control of lockControls(box)) {
		if (control.tomselect) {
			control.tomselect.wrapper.toggleAttribute("inert", locked);
		} else if (control.tagName === "INPUT" && control.type !== "checkbox") {
			control.readOnly = locked;
			control.tabIndex = locked ? -1 : 0;
		} else {
			control.toggleAttribute("inert", locked);
		}
	}
	// not being edited (any more): the button is the pencil again
	const pencil = box.querySelector(".lock-edit");
	box.classList.remove("editing");
	pencil.textContent = "\u270E";
	pencil.title = pencil.dataset.edit;
	pencil.setAttribute("aria-label", pencil.title);
	pencil.disabled = !locked;
}

// The boxes of a form as it opens: those of something that exists are locked
// where they hold a value (a tick box always says something). A box marked
// data-fixed is never changed once set (a language's code): no pencil frees it.
export function lockFields(form, existing) {
	for (const box of form.querySelectorAll(".lock-box")) {
		const [control] = lockControls(box);
		const filled = control.type === "checkbox" || (control.tomselect ? control.tomselect.items.length > 0 : control.value !== "");
		setLocked(box, existing && filled);
		// a fixed one (a museum visit's museum) is never changed: its pencil stays, disabled
		box.querySelector(".lock-edit").disabled = "fixed" in control.dataset;
	}
}

// The + button (item null) or a click on an item: the dialog with the form of the view on screen.
export async function openDialog(listed) {
	// a view is read only: no dialog to change anything in
	if (VISIT) {
		return;
	}
	// the view is fixed here: the lists below load before the dialog shows, and another view may be opened meanwhile
	const view = state.view;
	const world = WORLDS[view];
	// the list has no chess game's text or moves: the one opened is fetched with them
	const item = view === "chess" && listed ? { ...listed, ...(await api(`${world[1]}/${listed.id}`)) } : listed;
	const form = world ? $(`${slug(view)}-form`) : $("add-form");
	for (const id of DIALOG_FORMS) {
		$(id).hidden = $(id) !== form;
	}
	const noun = world ? world[2] : state.config.kinds[view].name.toLowerCase();
	$("dialog-title").textContent = item ? `Edit ${noun}` : `Add ${/^[aeiou]/.test(noun) ? "an" : "a"} ${noun}`;
	form.querySelector("button[type=submit]").textContent = item ? "Save" : "Add";
	const remove = form.querySelector("button.delete");
	remove.hidden = !item;
	remove.textContent = "Delete";
	delete remove.dataset.armed;
	dialogError("");
	// every row to add something with is put away: the + of its list brings it in
	for (const adder of form.querySelectorAll(".adder")) {
		adder.hidden = true;
	}
	if (world) {
		for (const select of form.querySelectorAll("[data-chips]")) {
			setPickerRows(select, await worldList(select.dataset.chips));
		}
		if (form.elements.type_id) {
			await fillTypes(form.elements.type_id, TYPED[view]);
		}
		if (form.elements.device_id) {
			await fillTypes(form.elements.device_id, "devices");
		}
		// single pickers over a view (a concert's place, a city, a country): its rows, by the view's label;
		// data-kind keeps the places of one kind (a museum visit's museum: the places of the kind Museum)
		for (const select of form.querySelectorAll("select[data-picker]")) {
			const kind = select.dataset.kind;
			const rows = (await worldList(select.dataset.picker)).filter((row) => !kind || row.kinds?.some((k) => k.name === kind));
			setPickerRows(select, rows, PICKER_LABELS[select.dataset.picker] || ((row) => row.name));
		}
		resetForm(form);
		if (view === "organizations" && !item) {
			// through worldList: a reload of another view may have dropped the cached types meanwhile
			const company = (await worldList("organization-types")).find((t) => t.name === "Company");
			form.elements.type_id.value = company ? company.id : "";
		}
		if (item) {
			fillWorldForm(form, item);
		}
		syncDatePicks(form);
		if (form.elements.device_id) {
			form.elements.device_id.value = item?.device ? item.device.id : "";
		}
		// and the row it has: place_id shows item.place, city_id item.city, ...
		for (const select of form.querySelectorAll("select[data-picker]")) {
			const chosen = item?.[select.name.replace(/_id$/, "")];
			setPickerValue(select, chosen ? [chosen.id] : []);
		}
		if (form.id === "museum-visit-form") {
			prepareVisits(item?.visits || [], !item);
		}
		if (form.id === "chess-game-form") {
			// a game is added by its text; the text of one that exists is only read
			form.elements.pgn.readOnly = Boolean(item);
			form.elements.pgn.required = !item;
			prepareBoard(item);
		}
		if (form.id === "youtube-video-form") {
			showYouTubeFacts(item);
		}
		if (form.id === "person-form") {
			prepareNames(item);
			await preparePersonLinks(item);
		}
		syncAlone(form);
	} else {
		await prepareWorkForm(form, item);
	}
	preparePictures(form, item);
	lockFields(form, Boolean(item));
	// a shared row (a place, a city, ...) is everyone's: one who is no admin reads it and changes nothing,
	// every control in its place, disabled
	const readOnly = Boolean(world) && !canChange(view);
	if (readOnly) {
		for (const pencil of form.querySelectorAll(".lock-edit")) {
			pencil.disabled = true;
		}
		$("dialog-title").textContent = `${noun[0].toUpperCase()}${noun.slice(1)}: ${isAdmin() ? "shared data, locked (Settings: Edit shared data)" : "shared by everyone, only an admin changes it"}`;
	}
	const submit = form.querySelector("button[type=submit]");
	submit.disabled = readOnly;
	submit.title = readOnly ? sharedLockedWhy() : "";
	remove.disabled = readOnly;
	// another view was opened while the lists loaded: its dialog is not this one
	if (state.view !== view) {
		return;
	}
	state.editing = item;
	state.editingView = view;
	$("add-dialog").showModal();
	// the first box to type in, but a picker's: that one comes in with its +
	const first = [...form.querySelectorAll("input")].find((i) => i.offsetParent !== null && !i.readOnly && !i.closest(".ts-wrapper"));
	if (first) {
		first.focus();
	}
}

// Delete asks twice, in the button itself: the first click arms it.
async function deleteEditing(button) {
	if (!button.dataset.armed) {
		button.dataset.armed = "1";
		button.textContent = "Delete for good?";
		return;
	}
	const world = WORLDS[state.editingView];
	if (world) {
		await api(`${world[1]}/${state.editing.id}`, { method: "DELETE" });
		$("add-dialog").close();
		await refreshWorld();
	} else {
		await api(`/api/library-entries/${state.editing.work_id}`, { method: "DELETE" });
		$("add-dialog").close();
		await loadEntries();
	}
}

export function setupAddDialog() {
	const dialog = $("add-dialog");
	for (const button of dialog.querySelectorAll("button.cancel")) {
		button.onclick = () => dialog.close();
	}
	for (const button of dialog.querySelectorAll("button.delete")) {
		button.onclick = () => deleteEditing(button).catch((e) => dialogError(e.message));
	}
	// before the pickers are made: a picker is built beside its select, inside the box that locks it
	setupLocks(dialog);
	for (const select of dialog.querySelectorAll("[data-chips]")) {
		makePicker(select, () => syncAlone(select.closest("form")));
	}
	for (const select of dialog.querySelectorAll("[data-picker], #relation-person, #organization-link-organization")) {
		makePicker(select);
	}
	// In a picker, Escape closes its list and Enter picks the highlighted row;
	// neither ever closes the dialog or saves the form, even when the list has
	// already closed by itself (the edits would be lost, or saved half done)
	dialog.addEventListener("keydown", (event) => {
		if ((event.key === "Escape" || event.key === "Enter") && event.target.closest?.(".ts-wrapper") && !event.target.closest("button")) {
			event.preventDefault();
		}
	}, true);
	$("museum-visit-form").elements.alone.onchange = () => syncAlone($("museum-visit-form"));
	$("concert-form").elements.alone.onchange = () => syncAlone($("concert-form"));
	const { rating_min, rating_max } = state.config;
	$("museum-visit-rating").min = rating_min;
	$("museum-visit-rating").max = rating_max;
	$("audio-course-form").elements.rating.min = rating_min;
	$("audio-course-form").elements.rating.max = rating_max;
	$("audio-book-form").elements.rating.min = rating_min;
	$("audio-book-form").elements.rating.max = rating_max;
	for (const id of ["podcast-heard-form", "episode-heard-form"]) {
		$(id).elements.rating.min = rating_min;
		$(id).elements.rating.max = rating_max;
	}
	$("youtube-video-form").elements.rating.min = rating_min;
	$("youtube-video-form").elements.rating.max = rating_max;
	setupBoard();
	for (const view of Object.keys(WORLDS)) {
		setupWorldForm(view);
	}
	$("fab").onclick = () => {
		openDialog(null).catch((e) => showError(e.message));
	};
}
