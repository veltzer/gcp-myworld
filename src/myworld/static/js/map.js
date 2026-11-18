// The map layout, and the map of one place.

import { cityName } from "./cards.js";
import { $, showError } from "./core.js";
import { state } from "./library.js";
import { openDialog } from "./locks.js";
import { el, formatDate } from "./worlds.js";

// kind is "photo" or "logo" (a logo is always shown whole, never cropped)

// The views whose items have a latitude and longitude; on the others the Map button is disabled.
export const MAPPED = new Set(["museums", "organizations", "places", "cities", "countries"]);

// Leaflet, from cdnjs, loaded the first time a map is shown
const LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/";

const LEAFLET_JS = ["leaflet.js", "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"];

const LEAFLET_CSS = ["leaflet.css", "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"];

let leafletLoading = null;

let worldMap = null;

let mapMarkers = null;

export function showsMap() {
	return state.layout === "map" && MAPPED.has(state.view);
}

function loadLeaflet() {
	if (!leafletLoading) {
		leafletLoading = new Promise((resolve, reject) => {
			const css = document.createElement("link");
			css.rel = "stylesheet";
			css.href = LEAFLET + LEAFLET_CSS[0];
			css.integrity = LEAFLET_CSS[1];
			css.crossOrigin = "anonymous";
			document.head.appendChild(css);
			const script = document.createElement("script");
			script.src = LEAFLET + LEAFLET_JS[0];
			script.integrity = LEAFLET_JS[1];
			script.crossOrigin = "anonymous";
			script.onload = () => resolve(window.L);
			script.onerror = () => {
				leafletLoading = null;
				reject(new Error("The map library could not be loaded"));
			};
			document.head.appendChild(script);
		});
	}
	return leafletLoading;
}

// One marker per place: two visits of the same museum share a pin, and its popup lists both.
export async function renderMap(items) {
	const L = await loadLeaflet();
	if (!showsMap()) {
		return;
	}
	if (!worldMap) {
		worldMap = L.map("world-map", { worldCopyJump: true });
		L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
			maxZoom: 19,
			attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
		}).addTo(worldMap);
		mapMarkers = L.layerGroup().addTo(worldMap);
	}
	// the box was hidden while the map was made or last drawn: let Leaflet measure it again
	worldMap.invalidateSize();
	mapMarkers.clearLayers();
	const places = new Map();
	for (const item of items) {
		if (item.latitude === null || item.longitude === null) {
			continue;
		}
		const key = `${item.latitude},${item.longitude}`;
		if (!places.has(key)) {
			places.set(key, []);
		}
		places.get(key).push(item);
	}
	const points = [];
	for (const group of places.values()) {
		const point = [group[0].latitude, group[0].longitude];
		points.push(point);
		const marker = L.circleMarker(point, { radius: 8, weight: 2, color: "#1d4ed8", fillColor: "#3b82f6", fillOpacity: 0.85 });
		marker.bindTooltip(group[0].name);
		marker.bindPopup(() => mapPopup(group));
		mapMarkers.addLayer(marker);
	}
	if (points.length > 0) {
		worldMap.fitBounds(points, { padding: [32, 32], maxZoom: 15 });
	} else {
		worldMap.setView([20, 0], 2);
	}
	const unplaced = items.filter((item) => item.latitude === null || item.longitude === null).length;
	if (unplaced > 0) {
		$("world-count").textContent += ` (${unplaced} with no location, not on the map)`;
	}
}

// Material "place"
const PIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>';

// The pin on a museum or organization card: opens a map of that one place.
// Without coordinates it is there, disabled.
export function placeButton(item) {
	const button = el("button", "icon-button place-button");
	button.type = "button";
	button.innerHTML = PIN;
	const placed = item.latitude !== null && item.longitude !== null;
	button.disabled = !placed;
	button.title = placed ? `${item.name} on the map` : "No location: add an address and its latitude and longitude";
	button.setAttribute("aria-label", button.title);
	button.onclick = () => openPlace(item).catch((e) => showError(e.message));
	return button;
}

let placeMap = null;

let placeMarker = null;

async function openPlace(item) {
	const L = await loadLeaflet();
	const point = [item.latitude, item.longitude];
	$("place-title").textContent = item.name;
	$("place-address").textContent = item.address || item.location || (item.city ? cityName(item.city) : "") || item.country?.name || "";
	$("place-osm").href = `https://www.openstreetmap.org/?mlat=${item.latitude}&mlon=${item.longitude}#map=17/${item.latitude}/${item.longitude}`;
	$("place-dialog").showModal();
	if (!placeMap) {
		placeMap = L.map("place-map");
		L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
			maxZoom: 19,
			attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
		}).addTo(placeMap);
		$("place-close").onclick = () => $("place-dialog").close();
	}
	// the box was not laid out until the dialog opened: let Leaflet measure it
	placeMap.invalidateSize();
	placeMap.setView(point, 16);
	if (placeMarker) {
		placeMarker.remove();
	}
	placeMarker = L.circleMarker(point, { radius: 10, weight: 3, color: "#1d4ed8", fillColor: "#3b82f6", fillOpacity: 0.85 }).addTo(placeMap);
	placeMarker.bindTooltip(item.name, { permanent: true, direction: "top", offset: [0, -10] });
}

function mapPopup(group) {
	const box = el("div", "map-popup");
	const first = group[0];
	box.appendChild(el("strong", null, first.name));
	const where = first.address || first.location || (first.city ? cityName(first.city) : "") || first.country?.name;
	if (where) {
		box.appendChild(el("p", null, where));
	}
	for (const item of group) {
		const open = el("button", "text", group.length > 1 ? `Edit: ${formatDate(item) || item.name}` : "Edit");
		open.type = "button";
		open.onclick = () => openDialog(item).catch((e) => showError(e.message));
		box.appendChild(open);
	}
	return box;
}
