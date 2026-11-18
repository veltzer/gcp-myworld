// The Users page (admins only).

import { methodOf } from "./account.js";
import { $, api, showError } from "./core.js";
import { fillTypeFilter } from "./filters.js";
import { navigate } from "./history.js";
import { state } from "./library.js";
import { markActive, showSection } from "./paging.js";
import { renderKinds } from "./sidebar.js";
import { updateTools } from "./sorting.js";
import { el } from "./worlds.js";

export function isAdmin() {
	return state.config.user.role === "admin";
}

export async function selectUsers() {
	state.view = "users";
	navigate("users");
	document.title = "Users - My World";
	showSection("users-view");
	markActive();
	renderKinds();
	showError("");
	$("world-search").value = "";
	await fillTypeFilter("users");
	updateTools();
	const users = await api("/api/users");
	if (state.view === "users") {
		renderUsers(users);
	}
}

// Every account; an admin gives or takes the admin role with the select, and
// the server refuses to demote the last admin.
function renderUsers(users) {
	const admins = users.filter((u) => u.role === "admin").length;
	$("world-count").textContent = `${users.length} account${users.length === 1 ? "" : "s"}, ${admins} admin${admins === 1 ? "" : "s"}`;
	$("users-rows").replaceChildren(...users.map((user) => {
		const tr = el("tr");
		const role = el("select");
		role.setAttribute("aria-label", `Role of ${user.email}`);
		for (const value of ["user", "admin"]) {
			const option = el("option", null, value === "admin" ? "Admin" : "User");
			option.value = value;
			role.appendChild(option);
		}
		role.value = user.role;
		role.onchange = async () => {
			showError("");
			try {
				await api(`/api/users/${user.id}`, { method: "PUT", body: { role: role.value } });
			} catch (e) {
				role.value = user.role;
				showError(e.message);
				return;
			}
			// an admin who made themselves a user can no longer see this page
			state.config = await api("/api/config");
			if (!isAdmin()) {
				window.location.href = "/library";
				return;
			}
			await selectUsers();
		};
		tr.append(
			el("td", "title", user.name),
			el("td", null, user.email),
			el("td", null, user.methods.map((method) => methodOf(method).name).join(", ")),
			el("td", null, user.created_at.slice(0, 10)),
			el("td", null),
		);
		tr.lastChild.appendChild(role);
		return tr;
	}));
}
