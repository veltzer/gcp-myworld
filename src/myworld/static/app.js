// Browser side of My World: talks to the JSON API in src/myworld/. This is where a page starts;
// what it is made of is in js/, a module for each part.

import { showBuild, showError } from "./js/core.js";
import { indexPage, verifyPage } from "./js/landing.js";
import { libraryPage } from "./js/main.js";

document.addEventListener("DOMContentLoaded", () => {
	showBuild();
	const page = document.body.dataset.page;
	const run = { index: indexPage, verify: verifyPage, library: libraryPage }[page];
	// a page with nothing to run (the privacy page) only has its footer filled
	if (run) {
		run().catch((e) => showError(e.message));
	}
});
