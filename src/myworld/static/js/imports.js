// The Imports page: the importers, each with its parameters, Dry run and Run,
// the YouTube connection they read through, and the runs: the ones going
// (each done by a job of its own, in the background) and the last that ended,
// each with its Log (all it said, in a dialog here; #imports/<id> opens it).
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
		renderImporters(importers);
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

// the importers whose details are open: they stay open when the page is drawn again
const opened = new Set();

// The importers in two lists, each a line until it is clicked: the user's own (into their data), then,
// for an admin, the admins' (into the shared data, everyone's, and the tests)
function renderImporters(importers) {
	const groups = [
		["Your importers", "Into your own data: only you see what they bring.", importers.filter((i) => !i.for_admins)],
		["Admin importers", "Seen and run by admins only: into the shared data, everyone's, and the tests.", importers.filter((i) => i.for_admins)],
	];
	const out = [];
	for (const [title, intro, list] of groups) {
		if (!list.length) {
			continue;
		}
		const group = el("section", "importer-group");
		group.append(el("h2", "schema-heading", `${title} (${list.length})`), el("p", "importer-group-intro", intro), ...list.map(importerCard));
		out.push(group);
	}
	$("importers-list").replaceChildren(...out);
}

// One importer: a line with its name and what it adds to; a click opens what it does, a field per
// parameter, and Dry run and Run with the result under them.
function importerCard(importer) {
	const card = el("details", "importer");
	card.open = opened.has(importer.name);
	card.ontoggle = () => (card.open ? opened.add(importer.name) : opened.delete(importer.name));
	const summary = el("summary", "importer-summary");
	summary.appendChild(el("span", "importer-title", importer.title));
	// what it adds to; one into the shared data says so, a test says only admins see it
	const into = [
		importer.dataset_name ? `into ${importer.dataset_name}` : "",
		importer.shared ? "(shared data, everyone's)" : importer.admin_only ? "(only admins see it)" : "",
	].filter(Boolean).join(" ") + (importer.unavailable ? `: ${importer.unavailable}` : "");
	summary.appendChild(el("span", "importer-dataset", into));
	card.appendChild(summary);
	// one with choices to make says how they are picked
	const picking = importer.params.length ? " The choices of your last run are picked to start with." : "";
	card.append(el("p", "checks-intro", `${importer.description}${picking}`));
	const fields = [];
	for (const param of importer.params) {
		const row = el("label", "importer-param");
		row.appendChild(el("span", "importer-param-title", `${param.title}${param.single ? " (one)" : " (as many as you like)"}`));
		const select = document.createElement("select");
		select.multiple = !param.single;
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
		picker.setValue(param.single ? param.chosen.slice(0, 1) : param.chosen, true);
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
		params[param.name] = picker.items.filter(Boolean);
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

// a line of a run's log without the time it was said ("10:04:05 Countries" -> "Countries")
function unstamped(line) {
	return line.replace(/^\d\d:\d\d:\d\d /, "");
}

// What a run did, on one line: its counts (or why it failed, or the last it said); its Log has all of it.
function said(run) {
	const counts = Object.entries(run.counts).map(([what, n]) => `${what}: ${n.toLocaleString()}`).join(", ");
	const last = run.log ? unstamped(run.log.split("\n").at(-1)) : "";
	if (run.status === "done") {
		return `${run.dry_run ? "Nothing kept; it would have: " : ""}${counts || "nothing to do"}`;
	}
	if (run.status === "failed") {
		return last || "Failed";
	}
	return last || (run.status === "queued" ? "Waiting for its job to start" : "Started");
}

const STATUS = { queued: "Queued", running: "Running", done: "Done", failed: "Failed" };

// Clear: deletes the runs that ended, records and logs (the user's own; an admin's, everyone's), asking
// twice in the button itself. What they imported stays, and they still count against the month's runs.
function setupClear(count, everyone) {
	const button = $("import-clear");
	delete button.dataset.armed;
	button.textContent = "Clear";
	button.disabled = count === 0;
	button.title = count === 0
		? "No run that ended is listed"
		: `Delete the runs that ended${everyone ? ", everyone's" : ""}, with their logs. What they imported stays, and they still count against this month's runs`;
	button.onclick = async () => {
		if (!button.dataset.armed) {
			button.dataset.armed = "1";
			button.textContent = everyone ? "Delete everyone's ended runs and logs?" : "Delete your ended runs and logs?";
			return;
		}
		button.disabled = true;
		try {
			await api("/api/import-runs/clear", { method: "POST", body: {} });
			await refreshRuns();
		} catch (e) {
			showError(e.message);
			button.disabled = false;
		}
	};
}

async function clearRun(run, button) {
	if (!button.dataset.armed) {
		button.dataset.armed = "1";
		button.textContent = "Delete?";
		return;
	}
	button.disabled = true;
	await api(`/api/import-runs/${run.id}`, { method: "DELETE" });
	await refreshRuns();
}

// ─── a run's log ─────────────────────────────────────────────────────────────

// the run whose log is open, and the timer that looks at it again while it goes
const shownLog = { id: null, run: null, timer: null };

function logText(run) {
	const facts = [
		`${run.title}: ${run.dry_run ? "dry run" : "run"} ${run.id}, ${STATUS[run.status] || run.status}`,
		`Started ${run.started_at.slice(0, 19).replace("T", " ")} UTC${run.finished_at ? `, ended ${run.finished_at.slice(0, 19).replace("T", " ")} UTC` : ""}`,
		...(run.owner ? [`User ${run.owner.id} (${run.owner.email})`] : []),
		...(Object.keys(run.counts).length ? [Object.entries(run.counts).map(([what, n]) => `${what}: ${n}`).join(", ")] : []),
	];
	return `${facts.join("\n")}\n\n${run.log || "(nothing said yet)"}\n`;
}

function drawLog(run) {
	shownLog.run = run;
	$("run-log-title").textContent = `${run.title}: ${run.dry_run ? "dry run" : "run"} ${run.id}`;
	const ends = run.finished_at ? utc(run.finished_at) : new Date();
	const facts = [
		STATUS[run.status] || run.status,
		`started ${run.started_at.slice(0, 16).replace("T", " ")} UTC`,
		`${run.ended ? "took" : "so far"} ${took(utc(run.started_at), ends)}`,
		...(run.owner ? [`by ${run.owner.email} (user ${run.owner.id})`] : []),
	];
	$("run-log-facts").textContent = facts.join(" · ");
	const pre = $("run-log-text");
	// at the bottom (or not scrolled yet): it follows what is added
	const following = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
	pre.textContent = run.log || (run.status === "queued" ? "Waiting for its job to start…" : "Nothing said yet.");
	if (following) {
		pre.scrollTop = pre.scrollHeight;
	}
}

function scheduleLog() {
	clearTimeout(shownLog.timer);
	shownLog.timer = null;
	if (shownLog.run && !shownLog.run.ended && $("run-log-dialog").open) {
		shownLog.timer = setTimeout(() => refreshLog().catch((e) => showError(e.message)), POLL_MS);
	}
}

async function refreshLog() {
	const id = shownLog.id;
	const run = await api(`/api/import-runs/${id}`);
	if (shownLog.id === id && $("run-log-dialog").open) {
		drawLog(run);
		scheduleLog();
	}
}

// Open a run's log: all it said, each line with its time (UTC), looked at again while it goes;
// its address (#imports/<id>) opens it for whoever may see the run (its user, an admin)
export async function openRunLog(id) {
	shownLog.id = id;
	const run = await api(`/api/import-runs/${id}`);
	const dialog = $("run-log-dialog");
	$("run-log-text").scrollTop = 0;
	drawLog(run);
	navigate(`imports/${id}`);
	if (!dialog.open) {
		dialog.showModal();
	}
	$("run-log-text").scrollTop = $("run-log-text").scrollHeight;
	scheduleLog();
}

// a button that says it did it, for a moment
function flash(button, text) {
	const was = button.dataset.label || button.textContent;
	button.dataset.label = was;
	button.textContent = text;
	setTimeout(() => {
		button.textContent = was;
	}, 1500);
}

async function copyText(button, text) {
	try {
		await navigator.clipboard.writeText(text);
		flash(button, "Copied");
	} catch (e) {
		flash(button, "Could not copy");
	}
}

export function setupRunLog() {
	const dialog = $("run-log-dialog");
	$("run-log-close").onclick = () => dialog.close();
	dialog.onclick = (event) => {
		if (event.target === dialog) {
			dialog.close();
		}
	};
	dialog.onclose = () => {
		clearTimeout(shownLog.timer);
		shownLog.id = null;
		if (state.view === "imports") {
			navigate("imports");
		}
	};
	$("run-log-copy").onclick = () => copyText($("run-log-copy"), logText(shownLog.run));
	$("run-log-link").onclick = () => copyText($("run-log-link"), `${window.location.origin}/library#imports/${shownLog.run.id}`);
	$("run-log-download").onclick = () => {
		const run = shownLog.run;
		const a = el("a");
		a.href = URL.createObjectURL(new Blob([logText(run)], { type: "text/plain" }));
		a.download = `import-${run.importer}-${run.id}.log`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	};
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
		el("td", "", said(run)),
	);
	// all it said, in a dialog of the page: every user's own runs, an admin's everyone's
	const log = el("button", "text", "Log");
	log.type = "button";
	log.title = "All this run said, each line with its time; it follows a run that goes on";
	log.onclick = () => openRunLog(run.id).catch((e) => showError(e.message));
	const logCell = el("td", "nowrap");
	logCell.appendChild(log);
	// one that ended can be deleted, record and log (asking twice); one going has it, disabled
	const clear = el("button", "text danger", "Clear");
	clear.type = "button";
	clear.disabled = !run.ended;
	clear.title = run.ended ? "Delete this run and its log; what it imported stays" : "It can be cleared once it ended";
	clear.onclick = () => clearRun(run, clear).catch((e) => showError(e.message));
	logCell.appendChild(clear);
	cells.push(logCell);
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
	const labels = ["Started (UTC)", ...(everyone ? ["User id", "User"] : []), "Importer", "Kind", "Status", timeLabel, "What it did", ""];
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
	setupClear(ended.length, everyone);
	// a run that ended since the last look, and kept what it did, shows in the sidebar's counts
	if (ended.some((run) => goingIds.has(run.id) && run.status === "done" && !run.dry_run)) {
		loadCounts().catch((e) => showError(e.message));
	}
	goingIds = new Set(running.map((run) => run.id));
	schedulePoll(running.length > 0);
	scheduleTick(running.length > 0);
}
