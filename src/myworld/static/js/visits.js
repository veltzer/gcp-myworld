// The visits of a museum.

import { $ } from "./core.js";
import { removeButton, setPickerValue, syncAlone, toggleAdder } from "./dialog.js";
import { syncDatePicks, where } from "./forms.js";
import { state } from "./library.js";
import { el, formatDate } from "./worlds.js";

// A museum is one row whatever the times it was visited: each visit has its own
// day, rating, review, remark, tickets and company.

// the visits in the dialog, as the server sends them
let editingVisits = [];

// the visit the row is editing (its place in the list), null when the row adds one
let editingVisit = null;

// "4 May 2010, 8/10, with Dana", with what is not known left out or said
export function visitText(visit) {
	const company = visit.alone ? "alone" : visit.people.length ? `with ${visit.people.map((p) => p.name).join(", ")}` : "";
	const rating = visit.rating !== null && visit.rating !== undefined ? `${visit.rating}/${state.config.rating_max}` : "";
	return [formatDate(visit) || "date unknown", rating, company].filter(Boolean).join(", ");
}

// the row's boxes show this visit (a new one: all empty)
function fillVisitRow(visit) {
	const form = $("museum-visit-form");
	$("museum-visit-date").querySelector("input[type=hidden]").value = visit?.date || "";
	syncDatePicks(form);
	$("museum-visit-rating").value = visit?.rating ?? "";
	$("museum-visit-tickets").value = visit?.tickets ?? "";
	setPickerValue(form.querySelector("[data-field=people]"), (visit?.people || []).map((p) => p.id));
	form.elements.alone.checked = Boolean(visit?.alone);
	syncAlone(form);
	$("museum-visit-review").value = visit?.review || "";
	$("museum-visit-remark").value = visit?.remark || "";
	$("museum-visit-add").textContent = visit ? "Update" : "Add";
}

// the row comes in to add a visit (index null) or to edit the one at index; asked again for the same, it goes away
function openVisitRow(index) {
	const row = $("museum-visit-row");
	if (!row.hidden && editingVisit === index) {
		row.hidden = true;
		return;
	}
	editingVisit = index;
	fillVisitRow(index === null ? null : editingVisits[index]);
	toggleAdder(row, true);
}

function renderVisits() {
	const box = $("museum-visits");
	box.replaceChildren();
	if (editingVisits.length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingVisits.forEach((visit, index) => {
		const chip = el("span", "chip", visitText(visit));
		chip.title = visit.review || "";
		const edit = el("button", "modify chip-remove", "\u270e");
		edit.type = "button";
		edit.title = `Edit the visit ${visitText(visit)}`;
		edit.setAttribute("aria-label", edit.title);
		edit.onclick = () => openVisitRow(index);
		chip.appendChild(edit);
		chip.appendChild(removeButton(`Remove the visit ${visitText(visit)}`, () => {
			editingVisits.splice(index, 1);
			editingVisit = null;
			$("museum-visit-row").hidden = true;
			renderVisits();
		}));
		box.appendChild(chip);
	});
	const add = el("button", "modify", "+");
	add.type = "button";
	add.title = "Add a visit";
	add.setAttribute("aria-label", add.title);
	add.onclick = () => openVisitRow(null);
	box.appendChild(add);
}

// what the row says, as a visit
function visitOfRow() {
	const form = $("museum-visit-form");
	const old = editingVisit === null ? null : editingVisits[editingVisit];
	const picker = form.querySelector("[data-field=people]").tomselect;
	const date = $("museum-visit-date").querySelector("input[type=hidden]").value || null;
	const number = (id) => $(id).value === "" ? null : Number($(id).value);
	return {
		id: old?.id,
		date,
		// a date left as it was keeps how precisely it is known (a full time too)
		date_precision: !date ? null : date === old?.date ? old.date_precision : $("museum-visit-date").querySelector(".date-precision").value,
		date_timezone: old?.date_timezone || where(),
		rating: number("museum-visit-rating"),
		tickets: number("museum-visit-tickets"),
		people: picker.getValue().map((id) => ({ id: Number(id), name: picker.options[id].text })),
		alone: form.elements.alone.checked,
		review: $("museum-visit-review").value.trim(),
		remark: $("museum-visit-remark").value.trim(),
	};
}

// what the row says becomes a visit of the list: a new one, or the one it was editing.
// False when a number in it is not one (the browser says so), and nothing changes.
export function addVisit() {
	if (!$("museum-visit-rating").reportValidity() || !$("museum-visit-tickets").reportValidity()) {
		return false;
	}
	const visit = visitOfRow();
	if (editingVisit === null) {
		editingVisits.push(visit);
	} else {
		editingVisits[editingVisit] = visit;
	}
	editingVisit = null;
	$("museum-visit-row").hidden = true;
	renderVisits();
	return true;
}

// a new museum starts with the row in, to say its first visit; one edited with its visits listed
export function prepareVisits(visits, isNew) {
	editingVisits = visits.map((visit) => ({ ...visit }));
	editingVisit = null;
	fillVisitRow(null);
	$("museum-visit-row").hidden = !isNew;
	renderVisits();
}

// the visits to send, with what the row says while it is in (saving does not lose it; a row
// to add one that says nothing adds none); null when a number in the row is not one
export function visitsValues() {
	if (!$("museum-visit-row").hidden) {
		const said = visitOfRow();
		const empty = editingVisit === null && !said.date && said.rating === null && said.tickets === null && !said.people.length && !said.alone && !said.review && !said.remark;
		if (!empty && !addVisit()) {
			return null;
		}
	}
	return editingVisits.map((visit) => ({
		id: visit.id,
		date: visit.date || "",
		date_timezone: visit.date_timezone || "",
		rating: visit.rating ?? "",
		tickets: visit.tickets ?? "",
		people: visit.people.map((p) => p.id),
		alone: visit.alone,
		review: visit.review,
		remark: visit.remark,
	}));
}
