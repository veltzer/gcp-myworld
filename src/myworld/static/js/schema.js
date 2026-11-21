// The structure of the database, drawn.

import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { el } from "./worlds.js";

// Mermaid draws the diagram; loaded the first time the page is opened, like Leaflet
const MERMAID = ["https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js", "sha512-6a80OTZVmEJhqYJUmYd5z8yHUCDlYnj6q9XwB/gKOEyNQV/Q8u+XeSG59a2ZKFEHGTYzgfOQKYEBtrZV7vBr+Q=="];

let mermaidLoading = null;

function loadMermaid() {
	if (!mermaidLoading) {
		mermaidLoading = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			[script.src, script.integrity] = MERMAID;
			script.crossOrigin = "anonymous";
			script.onload = () => {
				const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
				// full size, scrolling in its box: shrunk to the page's width the names cannot be read
				window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral", er: { useMaxWidth: false } });
				resolve(window.mermaid);
			};
			script.onerror = () => {
				mermaidLoading = null;
				reject(new Error("The diagram library could not be loaded"));
			};
			document.head.appendChild(script);
		});
	}
	return mermaidLoading;
}

// The tables and how they point at each other, as a Mermaid ER diagram: each
// table with its keys only (the cards below have every column)
function schemaDiagram(tables) {
	const word = (text) => text.replace(/[^A-Za-z0-9_]/g, "_");
	const lines = ["erDiagram"];
	for (const table of tables) {
		const fks = new Set(table.foreign_keys.flatMap((fk) => fk.columns));
		const keys = table.columns.filter((c) => c.primary_key || fks.has(c.name));
		lines.push(`  ${word(table.name)} {`);
		for (const column of keys) {
			const marks = [column.primary_key ? "PK" : "", fks.has(column.name) ? "FK" : ""].filter(Boolean).join(", ");
			lines.push(`    ${word(column.type.split("(")[0])} ${word(column.name)} ${marks}`);
		}
		lines.push("  }");
	}
	for (const table of tables) {
		for (const fk of table.foreign_keys) {
			// many of this table to one of that; "zero or one" when the key may be empty
			const optional = fk.columns.some((name) => table.columns.find((c) => c.name === name)?.nullable);
			lines.push(`  ${word(table.name)} }o--${optional ? "o|" : "||"} ${word(fk.table)} : "${word(fk.columns.join(", "))}"`);
		}
	}
	return lines.join("\n");
}

function schemaCard(table) {
	const card = el("article", "schema-table");
	card.id = `schema-${table.name}`;
	const head = el("h3", "schema-name", table.name);
	head.appendChild(el("span", "schema-rows", ` ${table.rows.toLocaleString()} row${table.rows === 1 ? "" : "s"}`));
	card.appendChild(head);
	const columns = el("table", "entries schema-columns");
	const header = el("tr");
	for (const name of ["Column", "Type", "Empty", "Default", "Key"]) {
		header.appendChild(el("th", "", name));
	}
	columns.appendChild(el("thead")).appendChild(header);
	const body = columns.appendChild(el("tbody"));
	const fkOf = new Map(table.foreign_keys.flatMap((fk) => fk.columns.map((c, i) => [c, `${fk.table}.${fk.referred[i]}`])));
	for (const column of table.columns) {
		const row = el("tr");
		const key = [column.primary_key ? "primary" : "", fkOf.has(column.name) ? `\u2192 ${fkOf.get(column.name)}` : ""].filter(Boolean).join(", ");
		for (const value of [column.name, column.type, column.nullable ? "yes" : "no", column.default, key]) {
			row.appendChild(el("td", "", value));
		}
		if (table.only_in_database.includes(column.name)) {
			row.classList.add("drift");
			row.title = "In the database but not in the code's model";
		}
		body.appendChild(row);
	}
	card.appendChild(columns);
	const facts = el("ul", "schema-facts");
	for (const fk of table.foreign_keys) {
		facts.appendChild(el("li", "", `Foreign key ${fk.columns.join(", ")} \u2192 ${fk.table} (${fk.referred.join(", ")})${fk.on_delete ? `, on delete ${fk.on_delete.toLowerCase()}` : ""}`));
	}
	for (const unique of table.unique) {
		facts.appendChild(el("li", "", `Unique ${unique.columns.join(", ")}${unique.name ? ` (${unique.name})` : ""}`));
	}
	for (const index of table.indexes) {
		facts.appendChild(el("li", "", `${index.unique ? "Unique index" : "Index"} ${index.name} on ${index.columns.join(", ")}`));
	}
	for (const check of table.checks) {
		facts.appendChild(el("li", "", `Check ${check.name}: ${check.sql}`));
	}
	if (facts.children.length) {
		card.appendChild(facts);
	}
	return card;
}

export async function selectSchema() {
	state.view = "schema";
	navigate("schema");
	document.title = "Schema - My World";
	showSection("schema-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("schema");
	updateTools();
	$("world-count").textContent = "";
	// the browser saves it: the answer says it is a file (Content-Disposition), so the page stays
	$("schema-dump").onclick = () => {
		window.location.href = "/api/admin/dump";
	};
	const schema = await api("/api/schema");
	if (state.view !== "schema") {
		return;
	}
	const rows = schema.tables.reduce((sum, t) => sum + t.rows, 0);
	$("world-count").textContent = `${schema.tables.length} tables`;
	$("schema-summary").textContent = `Read from the database itself (${schema.dialect} ${schema.server_version}): ${schema.tables.length} tables, ${rows.toLocaleString()} rows in all.`;
	// where the database and the code's models differ: a migration still to run, or one that left something behind
	const drift = [
		...schema.missing.map((name) => `Table ${name} is in the code but not in the database (the app makes it when it starts)`),
		...schema.tables.filter((t) => !t.in_model).map((t) => `Table ${t.name} is in the database but not in the code`),
		...schema.tables.flatMap((t) => t.only_in_model.map((c) => `Column ${t.name}.${c} is in the code but not in the database: run scripts/migrate.sh`)),
		...schema.tables.flatMap((t) => t.only_in_database.map((c) => `Column ${t.name}.${c} is in the database but not in the code`)),
	];
	$("schema-drift").replaceChildren(...drift.map((text) => el("li", "", text)));
	$("schema-drift").hidden = drift.length === 0;
	$("schema-tables").replaceChildren(...schema.tables.map(schemaCard));
	const diagram = $("schema-diagram");
	diagram.textContent = "Drawing\u2026";
	try {
		const mermaid = await loadMermaid();
		const { svg } = await mermaid.render("schema-diagram-svg", schemaDiagram(schema.tables));
		diagram.innerHTML = svg;
	} catch (e) {
		diagram.textContent = e.message;
	}
}
