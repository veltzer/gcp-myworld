// The account menu and the settings.

import { $, api } from "./core.js";
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
}

// The Settings button opens the settings dialog with the name ready to edit;
// Cancel, Escape and the backdrop close it unsaved, Save sends the name and the preferred language
export function setupSettings(user) {
	const dialog = $("settings-dialog");
	const name = $("settings-name");
	const error = $("settings-error");
	name.maxLength = state.config.name_max_length;
	const locale = $("settings-locale");
	let saved = user.name;
	let savedLocale = user.locale;
	setupLocks(dialog);
	$("settings-button").onclick = () => {
		name.value = saved;
		locale.value = savedLocale;
		error.hidden = true;
		// both are there to read; the pencil of each lets it be changed
		lockFields($("settings-form"), true);
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
			if (locale.value !== savedLocale) {
				savedLocale = (await api("/api/account/locale", { method: "PUT", body: { locale: locale.value } })).locale;
				// every book may be shown by another title now: load the page again
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
