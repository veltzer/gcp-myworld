// The Imports page: the importers, each with its parameters, Dry run and Run,
// the YouTube connection they read through, and the runs: the ones going
// (each done by a job of its own, in the background) and the last that ended.
// The page looks again every few seconds while any is going.

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

// how often the page looks again while a run is going
const POLL_MS = 3000;
let pollTimer = null;
// the runs that were going the last time it looked: one that ended since may have added rows
let goingIds = new Set();

async function refreshRuns() {
	const runs = await api("/api/import-runs");
	if (state.view === "imports") {
		renderRuns(runs);
	}
}

function schedulePoll(going) {
	clearTimeout(pollTimer);
	pollTimer = null;
	if (going && state.view === "imports") {
		pollTimer = setTimeout(() => refreshRuns().catch((e) => showError(e.message)), POLL_MS);
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
	// what it adds to; a test adds to nothing, and says only admins see it
	const into = [importer.dataset_name ? `into ${importer.dataset_name}` : "", importer.admin_only ? "(only admins see it)" : ""].filter(Boolean).join(" ");
	heading.appendChild(el("span", "importer-dataset", ` ${into}`));
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
	result.textContent = "Starting…";
	try {
		const run = await api(`/api/importers/${importer.name}/runs`, { method: "POST", body: { params, dry_run: dryRun } });
		if (run.status === "failed") {
			result.classList.add("fail");
			result.textContent = run.log;
		} else {
			result.textContent = `${dryRun ? "Dry run" : "Run"} started: it goes on in the background, under Running below.`;
		}
		await refreshRuns();
	} catch (e) {
		result.classList.add("fail");
		result.textContent = e.message;
	} finally {
		for (const button of buttons) {
			button.disabled = false;
		}
	}
}

// "2026-11-21T10:00:00" is UTC, said or not
function utc(iso) {
	return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

// "4:05", "1:02:03": how long from one time to another
function took(from, to) {
	const seconds = Math.max(0, Math.round((to - from) / 1000));
	const two = (n) => String(n).padStart(2, "0");
	const [h, m, sec] = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
	return h ? `${h}:${two(m)}:${two(sec)}` : `${m}:${two(sec)}`;
}

// What a run did: its counts on one line (or why it failed), and all it said under it, opened with a click.
function said(run) {
	const counts = Object.entries(run.counts).map(([what, n]) => `${what}: ${n.toLocaleString()}`).join(", ");
	const lines = run.log ? run.log.split("\n") : [];
	let head;
	if (run.status === "done") {
		head = `${run.dry_run ? "Nothing kept; it would have: " : ""}${counts || "nothing to do"}`;
	} else if (run.status === "failed") {
		head = lines.at(-1) || "Failed";
	} else {
		head = lines.at(-1) || (run.status === "queued" ? "Waiting for its job to start" : "Started");
	}
	const cell = el("td");
	if (lines.length === 0) {
		cell.textContent = head;
		return cell;
	}
	const details = el("details");
	details.append(el("summary", "", head), el("pre", "importer-log", run.log));
	cell.appendChild(details);
	return cell;
}

const STATUS = { queued: "Queued", running: "Running", done: "Done", failed: "Failed" };

// the logs of a run's Cloud Run Jobs execution, in the console (an admin's)
function executionLink(run) {
	const parts = run.execution.match(/^projects\/([^/]+)\/locations\/([^/]+)\/jobs\/[^/]+\/executions\/([^/]+)$/);
	if (!parts) {
		return document.createTextNode("");
	}
	const a = el("a", "", "Logs");
	a.href = `https://console.cloud.google.com/run/jobs/executions/details/${parts[2]}/${parts[3]}/logs?project=${parts[1]}`;
	a.target = "_blank";
	a.rel = "noopener";
	return a;
}

function runRow(run, everyone, now) {
	const tr = el("tr");
	const started = utc(run.started_at);
	const cells = [el("td", "nowrap", run.started_at.slice(0, 16).replace("T", " "))];
	if (everyone) {
		const who = el("td", "nowrap", run.owner.email);
		who.title = `User ${run.owner.id}`;
		cells.push(el("td", "nowrap", String(run.owner.id)), who);
	}
	const statusClass = run.ended ? (run.status === "done" ? "pass" : "fail") : "going";
	cells.push(
		el("td", "nowrap", run.title),
		el("td", "nowrap", run.dry_run ? "Dry run" : "Run"),
		el("td", `nowrap ${statusClass}`, STATUS[run.status] || run.status),
		timeCell(run, started, now),
		said(run),
	);
	if (everyone) {
		const logs = el("td", "nowrap");
		logs.appendChild(executionLink(run));
		cells.push(logs);
	}
	tr.append(...cells);
	return tr;
}

// how long it took, or, for one going, how long so far: that one ticks every second (tick)
function timeCell(run, started, now) {
	const cell = el("td", "nowrap", took(started, run.finished_at ? utc(run.finished_at) : now));
	if (!run.ended) {
		cell.classList.add("ticking");
		cell.dataset.started = String(started.getTime());
	}
	return cell;
}

let tickTimer = null;

function tick() {
	// another page was opened: the clock stops (the Imports page starts it again)
	if (state.view !== "imports") {
		scheduleTick(false);
		return;
	}
	const now = new Date();
	for (const cell of document.querySelectorAll("#import-running-rows .ticking")) {
		cell.textContent = took(new Date(Number(cell.dataset.started)), now);
	}
}

function scheduleTick(going) {
	clearInterval(tickTimer);
	tickTimer = going ? setInterval(tick, 1000) : null;
}

function runsHead(everyone, timeLabel) {
	const tr = el("tr");
	const labels = ["Started (UTC)", ...(everyone ? ["User id", "User"] : []), "Importer", "Kind", "Status", timeLabel, "What it did", ...(everyone ? ["Job"] : [])];
	tr.append(...labels.map((label) => el("th", "", label)));
	return tr;
}

function renderLimit(limit, everyone) {
	const { used, allowed } = limit;
	const runs = (n) => `${n.toLocaleString()} run${n === 1 ? "" : "s"}`;
	const mine = allowed === null
		? `You started ${runs(used)} this month; as an admin you have no limit.`
		: `You started ${runs(used)} of your ${allowed.toLocaleString()} this month (dry runs count too).`;
	$("import-limit").textContent = everyone ? `${mine} The runs below are everyone's.` : mine;
}

function renderRuns({ running, ended, everyone, limit }) {
	const now = new Date();
	renderLimit(limit, everyone);
	$("import-running-title").textContent = everyone ? "Running (everyone's)" : "Running";
	$("import-ended-title").textContent = everyone ? "Ended (everyone's)" : "Ended";
	$("import-running-head").replaceChildren(runsHead(everyone, "Time so far"));
	$("import-ended-head").replaceChildren(runsHead(everyone, "Took"));
	$("import-running-rows").replaceChildren(...running.map((run) => runRow(run, everyone, now)));
	$("import-ended-rows").replaceChildren(...ended.map((run) => runRow(run, everyone, now)));
	$("import-running").hidden = running.length === 0;
	$("import-running-none").hidden = running.length !== 0;
	$("import-ended").hidden = ended.length === 0;
	$("import-ended-none").hidden = ended.length !== 0;
	// a run that ended since the last look, and kept what it did, shows in the sidebar's counts
	if (ended.some((run) => goingIds.has(run.id) && run.status === "done" && !run.dry_run)) {
		loadCounts().catch((e) => showError(e.message));
	}
	goingIds = new Set(running.map((run) => run.id));
	schedulePoll(running.length > 0);
	scheduleTick(running.length > 0);
}
