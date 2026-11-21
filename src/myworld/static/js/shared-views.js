// The Views page (doc/views.md): the user's views, each some of their data shown to anyone,
// read only, at /view/<username>/<name>; made, changed and deleted here.

import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { closeSidebarOnPhone, renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { WORLDS, el } from "./worlds.js";

// what the page last got: the views, the data sets a view can show, and the user's username
let listed = { views: [], datasets: [], username: null };
// the view the dialog changes; null for a new one
let editing = null;

// a data set as the sidebar calls it
function datasetName(key) {
	return state.config.kinds[key]?.plural || WORLDS[key]?.[3] || key;
}

function address(name) {
	return `${window.location.origin}/view/${listed.username || "your-username"}/${name || "name"}`;
}

export async function selectSharedViews() {
	state.view = "shared-views";
	navigate("shared-views");
	document.title = "Views - My World";
	showSection("shared-views-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("shared-views");
	updateTools();
	$("world-count").textContent = "";
	await loadSharedViews();
}

async function loadSharedViews() {
	listed = await api("/api/shared-views");
	if (state.view !== "shared-views") {
		return;
	}
	const { views, username } = listed;
	$("world-count").textContent = `${views.length} view${views.length === 1 ? "" : "s"}`;
	$("shared-views-username").hidden = Boolean(username);
	// a view's address has the username: without one the button stays, disabled
	$("shared-view-new").disabled = !username;
	$("shared-views-none").hidden = views.length > 0;
	$("shared-views").hidden = views.length === 0;
	$("shared-views-rows").replaceChildren(...views.map(viewRow));
}

function viewRow(view) {
	const tr = el("tr");
	const link = el("a", null, `/view/${listed.username}/${view.name}`);
	link.href = view.url;
	link.target = "_blank";
	link.rel = "noopener";
	link.title = "Open the view as anyone sees it, in a new tab";
	const shows = view.datasets.length ? view.datasets.map(datasetName).join(", ") : "Nothing yet";
	const edit = el("button", "text", "Edit");
	edit.type = "button";
	edit.onclick = () => openViewDialog(view);
	const remove = el("button", "text danger", "Delete");
	remove.type = "button";
	remove.title = "Delete the view: its address stops working; your data stays";
	remove.onclick = async () => {
		// asks twice, in the button itself
		if (!remove.dataset.armed) {
			remove.dataset.armed = "1";
			remove.textContent = "Delete for good?";
			return;
		}
		try {
			await api(`/api/shared-views/${view.id}`, { method: "DELETE" });
			await loadSharedViews();
		} catch (e) {
			showError(e.message);
		}
	};
	const actions = el("td", "nowrap");
	actions.append(edit, " ", remove);
	tr.append(el("td", null), el("td", null, view.title), el("td", null, shows), actions);
	tr.firstChild.appendChild(link);
	return tr;
}

function openViewDialog(view) {
	editing = view;
	const form = $("shared-view-form");
	$("shared-view-title").textContent = view ? `View: ${view.name}` : "New view";
	form.elements.name.value = view ? view.name : "";
	form.elements.title.value = view ? view.title : "";
	form.elements.description.value = view ? view.description : "";
	const shown = new Set(view ? view.datasets : []);
	$("shared-view-datasets").replaceChildren(...listed.datasets.map((key) => {
		const line = el("label", "check settings-check");
		const input = document.createElement("input");
		input.type = "checkbox";
		input.value = key;
		input.checked = shown.has(key);
		line.append(input, ` ${datasetName(key)}`);
		return line;
	}));
	$("shared-view-address").textContent = address(form.elements.name.value);
	$("shared-view-error").hidden = true;
	$("shared-view-dialog").showModal();
	form.elements.name.focus();
}

export function setupSharedViews() {
	const form = $("shared-view-form");
	$("shared-view-new").onclick = () => openViewDialog(null);
	$("shared-view-cancel").onclick = () => $("shared-view-dialog").close();
	form.elements.name.oninput = () => {
		$("shared-view-address").textContent = address(form.elements.name.value.toLowerCase());
	};
	form.onsubmit = async (event) => {
		event.preventDefault();
		const body = {
			name: form.elements.name.value,
			title: form.elements.title.value,
			description: form.elements.description.value,
			datasets: [...$("shared-view-datasets").querySelectorAll("input:checked")].map((input) => input.value),
		};
		try {
			if (editing) {
				await api(`/api/shared-views/${editing.id}`, { method: "PUT", body });
			} else {
				await api("/api/shared-views", { method: "POST", body });
			}
			$("shared-view-dialog").close();
			await loadSharedViews();
		} catch (e) {
			$("shared-view-error").textContent = e.message;
			$("shared-view-error").hidden = false;
		}
	};
	$("shared-views-link").onclick = (event) => {
		event.preventDefault();
		closeSidebarOnPhone();
		selectSharedViews().catch((e) => showError(e.message));
	};
}
