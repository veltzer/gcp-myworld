// The readings of a library entry.

import { $ } from "./core.js";
import { removeButton, toggleAdder } from "./dialog.js";
import { state } from "./library.js";
import { localeName } from "./names.js";
import { el } from "./worlds.js";

// Each has its own status, rating, review, the days it was started and finished
// and its language: a book read twice has two, each with what was thought then.

// the readings in the dialog, as the server sends them: {date, locale, status, rating, review, started_on}
let editingReads = [];

// the reading the row is editing (its place in the list), null when the row adds one
let editingRead = null;

// "2006-12-01 in Hebrew, 8/10", with what is not known left out or said; a reading not
// finished says where it is ("Want to")
export function readText(read) {
	const done = !read.status || read.status === "done";
	const when = [read.date || (done ? "date unknown" : ""), read.locale ? `in ${localeName(read.locale)}` : ""].filter(Boolean).join(" ");
	const parts = [when];
	if (!done) {
		parts.push(state.config.statuses[read.status] || read.status);
	}
	if (read.rating !== null && read.rating !== undefined) {
		parts.push(`${read.rating}/${state.config.rating_max}`);
	}
	return parts.filter(Boolean).join(", ");
}

// the row's boxes show this reading (a new one: Done, the rest empty)
function fillReadRow(read) {
	$("book-read-status").value = read?.status || "done";
	$("book-read-rating").value = read?.rating ?? "";
	$("book-read-locale").value = read?.locale || "";
	$("book-read-started").value = read?.started_on || "";
	$("book-read-date").value = read?.date || "";
	$("book-read-review").value = read?.review || "";
	$("book-read-add").textContent = read ? "Update" : "Add";
}

// the row comes in to add a reading (index null) or to edit the one at index; asked again for the same, it goes away
function openReadRow(index) {
	const row = $("book-read-row");
	if (!row.hidden && editingRead === index) {
		row.hidden = true;
		return;
	}
	editingRead = index;
	fillReadRow(index === null ? null : editingReads[index]);
	toggleAdder(row, true);
}

function renderReads() {
	const box = $("book-reads");
	box.replaceChildren();
	if (editingReads.length === 0) {
		box.appendChild(el("span", "empty", "None yet"));
	}
	editingReads.forEach((read, index) => {
		const chip = el("span", "chip", readText(read));
		chip.title = read.review || "";
		const edit = el("button", "modify chip-remove", "\u270e");
		edit.type = "button";
		edit.title = `Edit the reading ${readText(read)}`;
		edit.setAttribute("aria-label", edit.title);
		edit.onclick = () => openReadRow(index);
		chip.appendChild(edit);
		chip.appendChild(removeButton(`Remove the reading ${readText(read)}`, () => {
			editingReads.splice(index, 1);
			editingRead = null;
			$("book-read-row").hidden = true;
			renderReads();
		}));
		box.appendChild(chip);
	});
	const add = el("button", "modify", "+");
	add.type = "button";
	add.title = "Add a reading";
	add.setAttribute("aria-label", add.title);
	add.onclick = () => openReadRow(null);
	box.appendChild(add);
}

// what the row says becomes a reading of the list: a new one, or the one it was editing.
// False when the rating is not one (the browser says so), and nothing changes.
export function addRead() {
	const rating = $("book-read-rating");
	if (!rating.reportValidity()) {
		return false;
	}
	const read = {
		date: $("book-read-date").value || null,
		locale: $("book-read-locale").value,
		status: $("book-read-status").value,
		rating: rating.value === "" ? null : Number(rating.value),
		started_on: $("book-read-started").value || null,
		review: $("book-read-review").value.trim(),
	};
	if (editingRead === null) {
		editingReads.push(read);
	} else {
		editingReads[editingRead] = read;
	}
	editingRead = null;
	$("book-read-row").hidden = true;
	renderReads();
	return true;
}

// a new book starts with the row in, to say its first reading; one edited with its readings listed
export function prepareReads(reads, isNew) {
	editingReads = reads.map((read) => ({ ...read }));
	editingRead = null;
	fillReadRow(null);
	$("book-read-row").hidden = !isNew;
	renderReads();
}

// the readings to send, with what the row says while it is in (saving does not lose it);
// null when the row's rating is not one
export function readsValues() {
	if (!$("book-read-row").hidden && !addRead()) {
		return null;
	}
	return editingReads.map((read) => ({ ...read }));
}
