// The checks: the Checks page (admins only) and the checks of the page on screen.

import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { isAdmin } from "./users.js";
import { showRow } from "./views.js";
import { WORLDS, el } from "./worlds.js";

export async function selectChecks() {
	state.view = "checks";
	navigate("checks");
	document.title = "Checks - My World";
	showSection("checks-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("checks");
	updateTools();
	const checks = await loadChecks();
	if (state.view === "checks") {
		$("world-count").textContent = `${checks.length} check${checks.length === 1 ? "" : "s"}`;
		$("checks-list").replaceChildren(...checkGroups(checks));
	}
}

// The checks there are (admins only), fetched once: the Checks page and each page's own checks use them.
let checksLoading = null;

function loadChecks() {
	if (!checksLoading) {
		checksLoading = api("/api/checks").catch((e) => {
			checksLoading = null;
			throw e;
		});
	}
	return checksLoading;
}

// The Checks page, a group per dataset (Books, Museums, ...): a heading with its own Run all, then its checks.
function checkGroups(checks) {
	const groups = [];
	for (const check of checks) {
		let group = groups.at(-1);
		if (!group || group.dataset.dataset !== check.dataset) {
			group = el("section", "check-group");
			group.dataset.dataset = check.dataset;
			const heading = el("h2", "schema-heading", check.dataset_name);
			const run = el("button", "text", "Run all");
			run.type = "button";
			const list = el("div", "checks");
			run.onclick = () => runChecks(list, run).catch((e) => showError(e.message));
			heading.appendChild(run);
			group.append(heading, list);
			groups.push(group);
		}
		group.querySelector(".checks").appendChild(checkCard(check));
	}
	return groups;
}

// The views that have checks, once an admin's checks are loaded: the toolbar button is enabled on those.
let checkedViews = new Set();

export function updateViewChecks() {
	const button = $("view-checks-button");
	const has = isAdmin() && checkedViews.has(state.view);
	button.disabled = !has;
	button.title = !isAdmin() ? "Only an admin can run the checks" : has ? "Run the checks of this page" : "This page has no checks";
	// the panel belongs to the page it was opened on
	const panel = $("view-checks");
	if (panel.dataset.view !== state.view) {
		panel.hidden = true;
		button.setAttribute("aria-expanded", "false");
	}
}

async function openViewChecks() {
	const view = state.view;
	const checks = (await loadChecks()).filter((check) => check.dataset === view);
	if (state.view !== view || checks.length === 0) {
		return;
	}
	const panel = $("view-checks");
	panel.dataset.view = view;
	$("view-checks-title").textContent = `Checks of ${checks[0].dataset_name}`;
	$("view-checks-list").replaceChildren(...checks.map(checkCard));
	panel.hidden = false;
	$("view-checks-button").setAttribute("aria-expanded", "true");
	await runChecks($("view-checks-list"), $("view-checks-run"));
}

export function setupViewChecks() {
	$("view-checks-button").onclick = () => {
		if ($("view-checks").hidden) {
			openViewChecks().catch((e) => showError(e.message));
		} else {
			$("view-checks").hidden = true;
			$("view-checks-button").setAttribute("aria-expanded", "false");
		}
	};
	$("view-checks-run").onclick = () => runChecks($("view-checks-list"), $("view-checks-run")).catch((e) => showError(e.message));
	$("view-checks-close").onclick = () => {
		$("view-checks").hidden = true;
		$("view-checks-button").setAttribute("aria-expanded", "false");
	};
	if (isAdmin()) {
		loadChecks().then((checks) => {
			checkedViews = new Set(checks.map((check) => check.dataset));
			updateViewChecks();
		}).catch((e) => showError(e.message));
	}
	updateViewChecks();
}

// One check: what it looks at, a button to run it, and the last result under it.
// One row per check, all the same height: the name (what it checks in full
// is its tooltip), the result once run, and Run. A failing check's problems
// are under a closed disclosure, so a long list does not push the rest away.
function checkCard(check) {
	const card = el("div", "check");
	card.dataset.check = check.name;
	// on or off for this admin, saved in the database: Run all skips one that is off
	const enabled = document.createElement("input");
	enabled.type = "checkbox";
	enabled.className = "check-enabled";
	enabled.setAttribute("aria-label", `Run ${check.title} with Run all`);
	const title = el("span", "check-title", check.title);
	title.title = check.description;
	const run = el("button", "text check-run", "Run");
	run.type = "button";
	run.onclick = () => runCheck(card).catch((e) => showError(e.message));
	const show = () => {
		enabled.checked = check.enabled;
		enabled.title = check.enabled ? "On: Run all runs it. Untick to turn it off" : "Off: Run all skips it. Tick to turn it on";
		card.classList.toggle("check-off", !check.enabled);
		run.disabled = !check.enabled;
		card.dataset.enabled = String(check.enabled);
	};
	enabled.onchange = async () => {
		const on = enabled.checked;
		enabled.disabled = true;
		try {
			await api(`/api/disabled-checks/${check.name}`, { method: on ? "DELETE" : "PUT" });
			check.enabled = on;
			// the same check may be on the Checks page and in a page's own checks
			for (const other of document.querySelectorAll(`.check[data-check="${check.name}"]`)) {
				other.dispatchEvent(new Event("check-toggled"));
			}
		} catch (e) {
			showError(e.message);
		} finally {
			enabled.disabled = false;
			show();
		}
	};
	card.addEventListener("check-toggled", show);
	card.append(enabled, title, el("span", "check-result"), run);
	show();
	if (!check.enabled) {
		card.querySelector(".check-result").textContent = "Off";
	}
	return card;
}

// What a problem is about: a link to the row when it has a place in the app
// and is the viewer's own or shared (owner null: the app opens those), plain text otherwise.
function problemSubject(problem) {
	const match = problem.link.match(/^([a-z-]+)\/(\d+)$/);
	const theirs = problem.owner === null || problem.owner === state.config.user.id;
	if (!match || !theirs || !(match[1] in WORLDS || match[1] in state.config.kinds)) {
		return el("span", "check-subject", problem.subject);
	}
	const a = el("a", "check-subject", problem.subject);
	a.href = `/library#${problem.link}`;
	a.onclick = (event) => {
		event.preventDefault();
		showRow(match[1], Number(match[2])).catch((e) => showError(e.message));
	};
	return a;
}

async function runCheck(card) {
	const button = card.querySelector(".check-run");
	const out = card.querySelector(".check-result");
	button.disabled = true;
	card.querySelector(".check-details")?.remove();
	out.className = "check-result";
	out.textContent = "Running\u2026";
	try {
		const result = await api(`/api/checks/${card.dataset.check}`);
		out.classList.add(result.ok ? "pass" : "fail");
		if (result.ok) {
			out.textContent = `All ${result.checked} ${result.noun} pass`;
		} else {
			// the count is the toggle of the list, which opens under the whole row
			const list = el("ul", "check-problems check-details");
			list.hidden = true;
			for (const problem of result.problems) {
				const item = el("li");
				item.append(problemSubject(problem), document.createTextNode(`: ${problem.message}`));
				list.appendChild(item);
			}
			// the server sends the first few hundred of a long list
			const count = result.problem_count;
			if (count > result.problems.length) {
				list.appendChild(el("li", "check-more", `and ${(count - result.problems.length).toLocaleString()} more`));
			}
			const toggle = el("button", "text check-toggle", `${count.toLocaleString()} problem${count === 1 ? "" : "s"} in ${result.checked.toLocaleString()} ${result.noun}`);
			toggle.type = "button";
			toggle.setAttribute("aria-expanded", "false");
			toggle.onclick = () => {
				list.hidden = !list.hidden;
				toggle.setAttribute("aria-expanded", String(!list.hidden));
			};
			out.replaceChildren(toggle);
			card.appendChild(list);
		}
	} catch (e) {
		out.classList.add("fail");
		out.textContent = e.message;
	} finally {
		button.disabled = false;
	}
}

// Run every check under box in turn, its Run all button disabled meanwhile.
export async function runChecks(box, button) {
	button.disabled = true;
	try {
		for (const card of box.querySelectorAll(".check")) {
			// one turned off is skipped, and says so
			if (card.dataset.enabled === "false") {
				card.querySelector(".check-details")?.remove();
				const out = card.querySelector(".check-result");
				out.className = "check-result";
				out.textContent = "Off";
				continue;
			}
			await runCheck(card);
		}
	} finally {
		button.disabled = false;
	}
}
