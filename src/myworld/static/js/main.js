// The library page as a whole: starting it, and going where the address says.

import { askUsername, setupAccountMenu, setupSettings, showWho } from "./account.js";
import { selectChecks, setupViewChecks } from "./checks.js";
import { $, VISIT, api, applyTheme, showError } from "./core.js";
import { dialogError, pictures, setupPictures } from "./dialog.js";
import { setupMovieSearch } from "./films.js";
import { chosen, ownedValues, setupDatePicks, setupLocalized } from "./forms.js";
import { nav, setupFreshness, startHistory } from "./history.js";
import { fillStatuses, loadEntries, selectKind, state } from "./library.js";
import { setupAddDialog } from "./locks.js";
import { localizedValues } from "./names.js";
import { openRunLog, selectImports, setupRunLog } from "./imports.js";
import { setupPager } from "./paging.js";
import { readsValues } from "./readings.js";
import { selectSchema } from "./schema.js";
import { selectSharedViews, setupSharedViews } from "./shared-views.js";
import { loadCounts, renderKinds, setupSidebar } from "./sidebar.js";
import { selectStats } from "./stats.js";
import { isAdmin, selectUsers } from "./users.js";
import { selectWorld, setupWorlds, showRow } from "./views.js";
import { WORLDS, el } from "./worlds.js";

export async function libraryPage() {
	try {
		state.config = await api("/api/config");
	} catch (e) {
		// a view that is no longer there
		showError(e.message);
		return;
	}
	if (!state.config.user && !VISIT) {
		window.location.href = "/";
		return;
	}
	const { user, rating_min, rating_max } = state.config;
	if (VISIT) {
		setupVisit(state.config.visit);
	} else {
		applyTheme(user.theme);
		showWho(user);
		if (user.picture) {
			$("avatar").src = user.picture;
		}
		// the username first: a new account chooses it before anything else
		await askUsername(user);
		showWho(user);
		setupAccountMenu(user);
		setupSettings(user);
		setupRunLog();
		setupSharedViews();
		$("logout").onclick = async () => {
			await fetch("/auth/logout", { method: "POST" });
			window.location.href = "/";
		};
	}
	setupSidebar();

	const form = $("add-form");
	fillStatuses($("book-read-status"), "done");
	$("book-read-rating").min = rating_min;
	$("book-read-rating").max = rating_max;
	form.onsubmit = async (event) => {
		event.preventDefault();
		dialogError("");
		const body = { kind: state.editingView };
		for (const el of form.elements) {
			if (el.name && el.type !== "file") {
				body[el.name] = el.value;
			}
		}
		if (state.editingView === "book") {
			body.authors = chosen(form, "authors");
			// every title, each in its language; the first is the one the work is known by
			const titles = localizedValues("titles");
			if (titles.length === 0) {
				$("book-title-row").hidden = false;
				dialogError("A book needs a title: type one and press Add");
				return;
			}
			body.title = titles[0].title;
			body.title_locale = titles[0].locale;
			body.titles = titles.slice(1);
			body.original_locale = $("book-original").value;
		}
		// where the user is with it, their rating and review: those of each reading
		body.reads = readsValues();
		if (body.reads === null) {
			return;
		}
		body.owned = ownedValues();
		try {
			// all its covers: the first is the one its card shows
			body.covers = (await pictures(form)).map((cover) => cover.id);
			if (state.editing) {
				await api(`/api/library-entries/${state.editing.work_id}`, { method: "PUT", body });
			} else {
				await api("/api/library-entries", { method: "POST", body });
			}
			$("add-dialog").close();
			await loadEntries();
		} catch (e) {
			dialogError(e.message);
		}
	};

	setupMovieSearch();
	setupLocalized();
	setupPictures();
	setupWorlds();
	setupViewChecks();
	setupDatePicks();
	setupPager();
	setupAddDialog();
	renderKinds();
	if (!VISIT) {
		loadCounts().catch((e) => showError(e.message));
	}
	startHistory();
	setupFreshness();
	await openHash();
}

// Open what the address bar says, without adding a history entry.
export async function openHash() {
	nav.replacing = true;
	try {
		await route(window.location.hash.slice(1));
	} finally {
		nav.replacing = false;
	}
}

// A view's page (doc/views.md): whose view it is and what it is, in place of the account's controls,
// and of the sidebar only the data sets it shows
function setupVisit(visit) {
	document.body.classList.add("visiting");
	for (const id of ["account-box", "settings-button", "logout", "overview-group"]) {
		$(id).hidden = true;
	}
	const banner = $("visit-banner");
	banner.hidden = false;
	banner.replaceChildren(el("span", "visit-title", visit.title), el("span", "visit-owner", ` by ${visit.username}`));
	const home = el("a", "visit-home", "My World");
	home.href = "/";
	home.title = "Make your own: sign in to My World";
	banner.appendChild(home);
	const note = $("visit-note");
	note.hidden = !visit.description;
	note.textContent = visit.description;
}

// Open what an address-bar hash names: a tab, a page, or one row of a view.
async function route(requested) {
	if (VISIT) {
		await visitRoute(requested);
		return;
	}
	const linked = requested.match(/^([a-z-]+)\/(\d+)$/);
	if (linked && (linked[1] in WORLDS || linked[1] in state.config.kinds)) {
		await showRow(linked[1], Number(linked[2]));
	} else if (requested === "stats") {
		await selectStats();
	} else if (requested === "imports") {
		await selectImports();
	} else if (/^imports\/\d+$/.test(requested)) {
		// a run's log, by its address
		await selectImports();
		await openRunLog(Number(requested.split("/")[1]));
	} else if (requested === "users" && isAdmin()) {
		await selectUsers();
	} else if (requested === "checks" && isAdmin()) {
		await selectChecks();
	} else if (requested === "schema" && isAdmin()) {
		await selectSchema();
	} else if (requested === "shared-views") {
		await selectSharedViews();
	} else if (requested in state.config.kinds) {
		await selectKind(requested);
	} else {
		await selectWorld(requested in WORLDS ? requested : "concerts");
	}
}

// In a view, only its data sets open: a hash naming anything else opens the first of them
async function visitRoute(requested) {
	const { datasets } = state.config.visit;
	if (datasets.length === 0) {
		showError("This view shows nothing yet");
		return;
	}
	const linked = requested.match(/^([a-z-]+)\/(\d+)$/);
	if (linked && datasets.includes(linked[1])) {
		await showRow(linked[1], Number(linked[2]));
		return;
	}
	const open = datasets.includes(requested) ? requested : datasets[0];
	if (open in state.config.kinds) {
		await selectKind(open);
	} else {
		await selectWorld(open);
	}
}
