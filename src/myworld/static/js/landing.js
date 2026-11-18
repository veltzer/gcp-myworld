/* globals google */
// The landing page (signing in and up) and the page a mailed link leads to.

import { $, api, showError } from "./core.js";

function loadGoogleSignIn(clientId) {
	const script = document.createElement("script");
	script.src = "https://accounts.google.com/gsi/client";
	script.async = true;
	script.onload = () => {
		google.accounts.id.initialize({
			client_id: clientId,
			ux_mode: "redirect",
			login_uri: `${window.location.origin}/auth/login`,
		});
		// Google's own button, unseen over the Google tile: a click on the tile is a click on it
		google.accounts.id.renderButton($("signin-button"), {
			type: "standard",
			size: "large",
			width: 200,
		});
	};
	script.onerror = () => {
		googleOff("Could not load Google sign-in: check your connection and reload");
		showError("Could not load Google sign-in. Check your connection and reload.");
	};
	document.head.appendChild(script);
}

// the Google tile, greyed out, when it cannot be used
function googleOff(why) {
	$("signin").classList.add("off");
	$("signin").title = why;
}

// the email tile opens the email form under the tiles, and closes it again
function setupEmailMethod() {
	const button = $("email-method");
	button.onclick = () => {
		const open = $("email-form").hidden;
		$("email-form").hidden = !open;
		button.setAttribute("aria-expanded", String(open));
		if (open) {
			$("email-form").elements.email.focus();
		}
	};
}

function setupProviders(configured) {
	for (const link of document.querySelectorAll(".method[data-provider]")) {
		if (configured[link.dataset.provider]) {
			continue;
		}
		link.classList.add("off");
		link.setAttribute("aria-disabled", "true");
		link.title = "Not configured on this server";
		link.onclick = (event) => event.preventDefault();
	}
}

// Signing in takes the email and the password; "Get a link by mail" takes
// only the email, and the server mails it a link to choose the password with
function setupEmailForm() {
	const form = $("email-form");
	const password = form.elements.password;
	const submit = $("email-submit");
	let mode = "login";

	const applyMode = () => {
		const link = mode === "link";
		submit.textContent = link ? "Mail me a link" : "Sign in";
		$("password-row").hidden = link;
		$("email-hint").hidden = !link;
		$("email-switch-text").textContent = link ? "Already chose a password?" : "New here, or forgot your password?";
		$("email-mode").textContent = link ? "Sign in" : "Get a link by mail";
		showError("");
	};
	$("email-mode").onclick = () => {
		mode = mode === "login" ? "link" : "login";
		applyMode();
	};
	$("toggle-password").onclick = () => {
		const hidden = password.type === "password";
		password.type = hidden ? "text" : "password";
		$("toggle-password").textContent = hidden ? "Hide" : "Show";
	};
	form.onsubmit = async (event) => {
		event.preventDefault();
		showError("");
		$("email-sent").hidden = true;
		const email = form.elements.email.value.trim();
		if (!email || !email.includes("@")) {
			showError("Enter your email address.");
			form.elements.email.focus();
			return;
		}
		submit.disabled = true;
		try {
			if (mode === "link") {
				const result = await api("/auth/email/register", { method: "POST", body: { email } });
				$("email-sent").textContent = result.message;
				$("email-sent").hidden = false;
			} else {
				const result = await api("/auth/email/login", { method: "POST", body: { email, password: password.value } });
				window.location.href = result.next;
				return;
			}
		} catch (e) {
			showError(e.message);
		}
		submit.disabled = false;
	};
	applyMode();
}

export async function indexPage() {
	const config = await api("/api/config");
	if (config.user) {
		window.location.href = "/library";
		return;
	}
	const error = new URLSearchParams(window.location.search).get("error");
	if (error) {
		showError(error);
		window.history.replaceState(null, "", "/");
	}
	if (config.google_client_id) {
		loadGoogleSignIn(config.google_client_id);
	} else {
		googleOff("Google sign-in is not configured on this server (GOOGLE_CLIENT_ID is not set)");
	}
	setupProviders(config.providers);
	setupEmailMethod();
	setupEmailForm();
	$("dev-login").hidden = !config.dev_login;
}

// The link carries a token that proves its reader has the mailbox: they choose the password here
export async function verifyPage() {
	const config = await api("/api/config");
	const token = new URLSearchParams(window.location.search).get("token") || "";
	// the token is not to stay in the address bar, the history or a bookmark
	window.history.replaceState(null, "", "/verify");
	const form = $("password-form");
	const password = form.elements.password;
	password.minLength = config.password_min_length;
	try {
		const pending = await api("/auth/email/verify", { method: "POST", body: { token } });
		$("verify-email").textContent = pending.email;
		form.elements.email.value = pending.email;
		form.hidden = false;
		password.focus();
	} catch (e) {
		showError(e.message);
		$("verify-again").hidden = false;
		return;
	}
	$("toggle-password").onclick = () => {
		const hidden = password.type === "password";
		password.type = hidden ? "text" : "password";
		$("toggle-password").textContent = hidden ? "Hide" : "Show";
	};
	form.onsubmit = async (event) => {
		event.preventDefault();
		showError("");
		if (password.value.length < config.password_min_length) {
			showError(`Use at least ${config.password_min_length} characters for the password.`);
			password.focus();
			return;
		}
		$("password-submit").disabled = true;
		try {
			const result = await api("/auth/email/password", { method: "POST", body: { token, password: password.value } });
			window.location.href = result.next;
		} catch (e) {
			showError(e.message);
			$("password-submit").disabled = false;
		}
	};
}
