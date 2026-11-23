// The About page: the build serving (/app/version): the commit it was built from, when it was
// deployed and built, when this server started, and the Cloud Run revision. Every time is said
// in UTC and in the reader's own time zone, as their browser knows it.

import { $, api } from "./core.js";
import { el } from "./worlds.js";

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

// "2026-11-23 10:04:05 UTC", and "23 November 2026, 12:04:05 (Asia/Jerusalem)" in the reader's zone
function bothZones(iso) {
	const when = new Date(iso);
	const utc = el("time", null, `${when.toISOString().slice(0, 19).replace("T", " ")} UTC`);
	utc.dateTime = when.toISOString();
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	const local = new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "medium" }).format(when);
	const box = el("span");
	box.append(utc, el("br"), el("span", "muted", `${local} (${zone || "your time zone"})`));
	return box;
}

// one line of the list: what it is, and its value (a text or an element)
function fact(list, label, value) {
	const dd = el("dd");
	dd.append(value);
	list.append(el("dt", null, label), dd);
}

function time(iso) {
	return ISO.test(iso || "") ? bothZones(iso) : "not known (a build run locally)";
}

export async function aboutPage() {
	const info = await api("/app/version");
	const list = $("about-facts");
	list.replaceChildren();
	// "v1.2-3-gabc1234-dirty": the commit is its last part
	const commit = (info.git_describe || "").match(/(?:-g)?([0-9a-f]{7,40})(?:-dirty)?$/);
	if (commit) {
		const link = el("a");
		link.href = `https://github.com/veltzer/gcp-myworld/commit/${commit[1]}`;
		link.appendChild(el("code", null, commit[1]));
		const source = el("span");
		const repo = el("a", null, "veltzer/gcp-myworld");
		repo.href = "https://github.com/veltzer/gcp-myworld";
		source.append(repo, " at ", link);
		fact(list, "Source", source);
	} else {
		fact(list, "Source", info.git_describe || "not known");
	}
	fact(list, "Deployed", time(info.deploy_date));
	fact(list, "Built", time(info.built_at));
	fact(list, "This server started", time(info.started_at));
	fact(list, "Serving as", info.revision && info.revision !== "local" ? info.revision : "a local server");
}
