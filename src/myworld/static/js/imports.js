// The Imports page: the importers, each with its parameters, Dry run and Run,
// the YouTube connection they read through, and the last runs.

import { $, api, showError } from "./core.js";
import { makePicker } from "./dialog.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { loadCounts, renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { el } from "./worlds.js";

export async function selectImports() {
	state.view = "imports";
	navigate("imports");
	document.title = "Imports - My World";
	showSection("imports-view");
	markActive();
	renderKinds();
	showError(takeConnectError());
	$("world-search").value = "";
	await fillTypeFilter("imports");
	updateTools();
	$("world-count").textContent = "";
	const [{ importers, youtube }, runs] = await Promise.all([api("/api/importers"), api("/api/import-runs")]);
	if (state.view === "imports") {
		renderConnection(youtube);
		$("world-count").textContent = `${importers.length} importer${importers.length === 1 ? "" : "s"}`;
		$("importers-list").replaceChildren(...importers.map(importerCard));
		renderRuns(runs);
	}
}

// Connecting YouTube comes back to /library?youtube_error=...#imports when it failed: say it once, and clean the address.
function takeConnectError() {
	const params = new URLSearchParams(window.location.search);
	const error = params.get("youtube_error") || "";
	if (error) {
		window.history.replaceState(window.history.state, "", `/library${window.location.hash}`);
	}
	return error;
}

// The YouTube account the importers read: who it is, and Connect or Disconnect in the same spot.
function renderConnection(youtube) {
	const box = $("youtube-connection");
	const button = el("button", "", youtube.connected ? "Disconnect" : "Connect YouTube");
	button.type = "button";
	let said;
	if (!youtube.configured) {
		said = "YouTube: connecting is not set up on this site.";
		button.disabled = true;
		button.title = "The site has no Google client secret (GOOGLE_CLIENT_SECRET)";
	} else if (youtube.connected) {
		said = `YouTube: connected${youtube.channel ? ` as ${youtube.channel}` : ""}, read only.`;
		button.title = "Forget the connection, and tell Google to revoke it";
		button.onclick = async () => {
			button.disabled = true;
			try {
				await api("/youtube/disconnect", { method: "POST" });
				await selectImports();
			} catch (e) {
				showError(e.message);
				button.disabled = false;
			}
		};
	} else {
		said = "YouTube: not connected. Connecting lets the importers read your playlists, nothing else.";
		button.title = "Go to Google and allow My World to read your YouTube account";
		button.onclick = () => {
			window.location.href = "/youtube/connect";
		};
	}
	box.replaceChildren(el("span", "", said), button);
}

// One importer: what it does, a field per parameter, and Dry run and Run with the result under them.
function importerCard(importer) {
	const card = el("section", "importer");
	const heading = el("h2", "schema-heading", importer.title);
	heading.appendChild(el("span", "importer-dataset", ` into ${importer.dataset_name}`));
	// one with choices to make says how they are picked
	const picking = importer.params.length ? " Pick as many as you like; the ones of your last run are picked to start with." : "";
	card.append(heading, el("p", "checks-intro", `${importer.description}${picking}`));
	const fields = [];
	for (const param of importer.params) {
		const row = el("label", "importer-param");
		row.appendChild(el("span", "importer-param-title", param.title));
		const select = document.createElement("select");
		select.multiple = true;
		select.dataset.placeholder = param.description;
		for (const choice of param.choices) {
			const option = document.createElement("option");
			option.value = choice.value;
			option.textContent = choice.label;
			select.appendChild(option);
		}
		row.appendChild(select);
		card.appendChild(row);
		if (param.error) {
			card.appendChild(el("p", "warning", param.error));
		}
		// a short list (a user's playlists): every choice is offered, not the best few
		const picker = makePicker(select, undefined, null);
		// it starts from what was chosen the last time it was run
		picker.setValue(param.chosen, true);
		if (importer.unavailable || param.error) {
			picker.disable();
		}
		fields.push({ param, picker });
	}
	const result = el("div", "importer-result");
	const buttons = el("p", "importer-buttons");
	const dry = el("button", "", "Dry run");
	dry.type = "button";
	dry.title = "Do it all and roll it back: says what a run would do";
	const run = el("button", "", "Run");
	run.type = "button";
	run.title = "Import: adds only what you do not have";
	const blocked = importer.unavailable || fields.some((f) => f.param.error);
	for (const button of [dry, run]) {
		button.disabled = Boolean(blocked);
		if (importer.unavailable) {
			button.title = importer.unavailable;
		}
		button.onclick = () => runImporter(importer, fields, button === dry, [dry, run], result).catch((e) => showError(e.message));
	}
	buttons.append(dry, run);
	if (importer.unavailable) {
		buttons.appendChild(el("span", "importer-unavailable", importer.unavailable));
	}
	card.append(buttons, result);
	return card;
}

async function runImporter(importer, fields, dryRun, buttons, result) {
	const params = {};
	for (const { param, picker } of fields) {
		params[param.name] = picker.items.slice();
	}
	for (const button of buttons) {
		button.disabled = true;
	}
	result.className = "importer-result";
	result.textContent = dryRun ? "Dry run…" : "Importing…";
	try {
		const done = await api(`/api/importers/${importer.name}/runs`, { method: "POST", body: { params, dry_run: dryRun } });
		result.replaceChildren(...runSummary(done));
		result.classList.add(done.status === "done" ? "pass" : "fail");
		// what was added shows in the sidebar's counts at once (a view fetches its rows again when opened)
		if (done.status === "done" && !dryRun) {
			loadCounts().catch((e) => showError(e.message));
		}
		renderRuns(await api("/api/import-runs"));
	} catch (e) {
		result.classList.add("fail");
		result.textContent = e.message;
	} finally {
		for (const button of buttons) {
			button.disabled = false;
		}
	}
}

// What a run did: its counts on one line (or why it failed), then what it said.
function runSummary(run) {
	const counts = Object.entries(run.counts).map(([what, n]) => `${what}: ${n.toLocaleString()}`).join(", ");
	const head = run.status === "done"
		? `${run.dry_run ? "Dry run, nothing kept. It would have: " : ""}${counts || "nothing to do"}`
		: "Failed, nothing kept";
	const out = [el("p", "importer-counts", head)];
	if (run.log) {
		out.push(el("pre", "importer-log", run.log));
	}
	return out;
}

function renderRuns(runs) {
	$("import-runs-rows").replaceChildren(...runs.map((run) => {
		const tr = el("tr");
		const when = el("td", "nowrap", run.started_at.slice(0, 16).replace("T", " "));
		const counts = Object.entries(run.counts).map(([what, n]) => `${what}: ${n.toLocaleString()}`).join(", ");
		const said = run.status === "done" ? counts || "nothing to do" : run.log.split("\n").at(-1);
		tr.append(when, el("td", "nowrap", run.title), el("td", "", run.dry_run ? "Dry run" : "Run"), el("td", run.status === "done" ? "pass" : "fail", run.status === "done" ? "Done" : "Failed"), el("td", "", said));
		return tr;
	}));
	$("import-runs").hidden = runs.length === 0;
	$("import-runs-none").hidden = runs.length !== 0;
}
