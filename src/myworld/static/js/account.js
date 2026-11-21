// The account menu and the settings.

import { $, api, applyTheme } from "./core.js";
import { state } from "./library.js";
import { lockFields, setupLocks } from "./locks.js";
import { el } from "./worlds.js";

// how each sign-in method is named, what its own id for the person is called, and its icon (static/<icon>.svg)
const PROVIDERS = {
	google: ["Google", "Google ID", "google"],
	github: ["GitHub", "GitHub user ID", "github"],
	email: ["Email and password", "Email", "email"],
	dev: ["Development login", "Email", "email"],
};

export function methodOf(key) {
	const [name, idLabel, icon] = PROVIDERS[key] || [key, "ID", "email"];
	return { name, idLabel, icon };
}

function methodIcon(key) {
	const img = el("img", "login-icon");
	img.src = `/static/${methodOf(key).icon}.svg`;
	img.alt = "";
	return img;
}

// The panel under the avatar and name: who is signed in, how, and every way they sign in.
export function setupAccountMenu(user) {
	const rows = [
		["Email", user.email],
		["Signed in with", methodOf(user.method).name],
		["Role", user.role === "admin" ? "Admin" : "User"],
		["Account", `#${user.id}`],
		["Since", user.since],
	];
	$("account-details").replaceChildren(...rows.flatMap(([label, value]) => [el("dt", null, label), el("dd", null, value)]));
	const count = user.logins.length;
	$("account-logins-heading").textContent = count === 1 ? "Your way to sign in" : `Your ${count} ways to sign in`;
	$("account-logins").replaceChildren(...user.logins.map((login) => {
		const method = methodOf(login.method);
		const li = el("li", "account-login");
		const text = el("div");
		const name = el("div", "account-login-name", method.name);
		if (login.current) {
			name.appendChild(el("span", "badge", "this session"));
		}
		text.append(name, el("div", "account-login-meta", `${method.idLabel} ${login.provider_id}`));
		if (login.email) {
			text.appendChild(el("div", "account-login-meta", `reports ${login.email}`));
		}
		if (login.last) {
			text.appendChild(el("div", "account-login-meta", `last used ${login.last}`));
		}
		li.append(methodIcon(login.method), text);
		return li;
	}));
	$("account-note").textContent = "Signing in with Google, GitHub or a password under this same verified email always reaches this same account.";
	const button = $("account-button");
	const menu = $("account-menu");
	const show = (open) => {
		menu.hidden = !open;
		button.setAttribute("aria-expanded", String(open));
	};
	button.onclick = () => show(menu.hidden);
	document.addEventListener("click", (event) => {
		if (!menu.hidden && !event.target.closest(".account")) {
			show(false);
		}
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape" && !menu.hidden) {
			show(false);
			button.focus();
		}
	});
}

// The top bar's name, and the icon of how this session signed in beside it
export function showWho(user) {
	$("who").textContent = user.name || user.email;
	const method = methodOf(user.method);
	const icon = $("who-method");
	icon.src = `/static/${method.icon}.svg`;
	icon.alt = method.name;
	icon.title = `Signed in with ${method.name}`;
	// an admin is told so, in the top bar
	$("who-role").hidden = user.role !== "admin";
}

// The Settings button opens the settings dialog with the name ready to edit;
// Cancel, Escape and the backdrop close it unsaved, Save sends the name, the preferred language and the theme
export function setupSettings(user) {
	const dialog = $("settings-dialog");
	const name = $("settings-name");
	const error = $("settings-error");
	name.maxLength = state.config.name_max_length;
	const locale = $("settings-locale");
	const theme = $("settings-theme");
	// an admin's lock on the shared data; one who is no admin sees it, disabled
	const editShared = $("settings-edit-shared");
	editShared.disabled = user.role !== "admin";
	editShared.title = user.role === "admin" ? "" : "Only an admin may change the shared data";
	let savedEditShared = user.edit_shared === true;
	let saved = user.name;
	let savedLocale = user.locale;
	let savedTheme = user.theme;
	setupLocks(dialog);
	$("settings-button").onclick = () => {
		name.value = saved;
		locale.value = savedLocale;
		theme.value = savedTheme;
		editShared.checked = savedEditShared;
		error.hidden = true;
		// both are there to read; the pencil of each lets it be changed
		lockFields($("settings-form"), true);
		// one who is no admin cannot unlock it either
		editShared.closest(".lock-box").querySelector(".lock-edit").disabled = user.role !== "admin";
		dialog.showModal();
	};
	$("settings-cancel").onclick = () => dialog.close();
	dialog.onclick = (event) => {
		if (event.target === dialog) {
			dialog.close();
		}
	};
	$("settings-form").onsubmit = async (event) => {
		event.preventDefault();
		try {
			const account = await api("/api/account/name", { method: "PUT", body: { name: name.value } });
			saved = account.name;
			showWho(account);
			if (theme.value !== savedTheme) {
				savedTheme = (await api("/api/account/theme", { method: "PUT", body: { theme: theme.value } })).theme;
				applyTheme(savedTheme);
			}
			const reload = locale.value !== savedLocale || editShared.checked !== savedEditShared;
			if (editShared.checked !== savedEditShared) {
				savedEditShared = (await api("/api/account/edit-shared", { method: "PUT", body: { edit_shared: editShared.checked } })).edit_shared;
			}
			if (locale.value !== savedLocale) {
				savedLocale = (await api("/api/account/locale", { method: "PUT", body: { locale: locale.value } })).locale;
			}
			if (reload) {
				// every book may be shown by another title, every shared page be changed or not: load the page again
				window.location.reload();
				return;
			}
			dialog.close();
		} catch (e) {
			error.textContent = e.message;
			error.hidden = false;
		}
	};
}
