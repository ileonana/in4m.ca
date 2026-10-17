const map = L.map("map").setView([43.7, -79.6], 9); // refit to the network once line.json loads

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const markers = new Map(); // tripId -> { marker, line }
const stationNames = new Map(); // stop code ("UN") -> name ("Union Station")
const lines = new Map(); // line code ("BR") -> { name, color, group: L.LayerGroup }
const statusEl = document.getElementById("status");
const HIDDEN_KEY = "hiddenLines";

// Feed values end up in popup HTML, so escape them.
function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function stationName(code) {
  return stationNames.get(code) ?? code;
}

// Which lines the viewer switched off last time (per browser, best effort).
function loadHidden() {
  try {
    return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY)) ?? []);
  } catch {
    return new Set();
  }
}

function saveHidden() {
  const hidden = [...lines].filter(([, l]) => !map.hasLayer(l.group)).map(([code]) => code);
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(hidden));
  } catch {}
}

// Track, stations and per-line toggles from public/line.json (built by scripts/build-line.py).
async function drawLines() {
  let data;
  try {
    data = await (await fetch("/line.json")).json();
  } catch {
    return; // map still works without it; trains just aren't grouped or named
  }

  const hidden = loadHidden();
  const overlays = {};
  for (const l of data.lines) {
    const group = L.layerGroup();
    for (const shape of l.shapes) {
      L.polyline(shape, { color: l.color, weight: 4, opacity: 0.6 }).addTo(group);
    }
    lines.set(l.code, { name: l.name, color: l.color, group });
    overlays[`<span class="swatch" style="background:${l.color}"></span>${esc(l.name)}`] = group;
    if (!hidden.has(l.code)) group.addTo(map);
  }

  // A station shared by several lines (e.g. Union) gets a dot in each line's
  // group, so it stays visible as long as any of its lines is shown.
  for (const s of data.stations) {
    stationNames.set(s.code, s.name);
    for (const code of s.lines) {
      const line = lines.get(code);
      if (!line) continue;
      L.circleMarker([s.lat, s.lon], {
        radius: 4, color: "#333", weight: 1.5, fillColor: "#fff", fillOpacity: 1,
      }).bindTooltip(esc(s.name)).addTo(line.group);
    }
  }

  L.control.layers(null, overlays, { collapsed: window.innerWidth < 700 }).addTo(map);
  map.on("overlayadd overlayremove", () => {
    saveHidden();
    updateStatus();
  });
  map.fitBounds(data.stations.map((s) => [s.lat, s.lon]), { padding: [20, 20] });
}

function trainIcon(train) {
  const color = lines.get(train.line)?.color ?? "#333";
  // Metrolinx currently sends bearing 0 / speed 0 for every train, i.e. no real
  // heading, so only draw a direction arrow when the feed actually has one.
  if (!train.bearing && !train.speed) {
    return L.divIcon({
      className: "",
      html: `<div class="train-dot" style="background:${color}"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
  }
  // The arrow glyph points east; GTFS bearing is degrees clockwise from north.
  return L.divIcon({
    className: "",
    html: `<div class="train-icon" style="color:${color};transform: rotate(${train.bearing - 90}deg)">&#10148;</div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

function minutesUntil(iso) {
  if (!iso) return null;
  const diffMs = new Date(iso).getTime() - Date.now();
  return Math.round(diffMs / 60000);
}

function formatDelay(seconds) {
  const mins = Math.round(seconds / 60);
  if (mins > 0) return ` (${mins} min late)`;
  if (mins < 0) return ` (${-mins} min early)`;
  return "";
}

function formatEta(stop, label) {
  if (!stop) return "";
  const mins = minutesUntil(stop.eta);
  const when = mins === null ? "unknown" : mins <= 0 ? "arriving" : `${mins} min`;
  return `<b>${label}: ${esc(stationName(stop.stopId))}</b>${when}${formatDelay(stop.delaySeconds)}`;
}

function popupHtml(train) {
  const line = lines.get(train.line);
  const lineName = line ? `<span class="line" style="color:${line.color}">${esc(line.name)}</span>` : "";
  // Labels look like "GT - Stratford GO" (line code + headsign); the destination says it better.
  const heading = train.finalStop
    ? `&rarr; ${esc(stationName(train.finalStop.stopId))}`
    : esc((train.label ?? train.tripId).replace(/^[A-Z]{2} - /, ""));
  return `
    <div class="popup-eta">
      ${lineName}
      <strong>${heading}</strong>
      ${formatEta(train.nextStop, "Next stop")}
      ${formatEta(train.finalStop, "Terminus")}
    </div>
  `;
}

// The layer a train's marker lives in: its line's group, so toggling a line hides its trains too.
function layerFor(line) {
  return lines.get(line)?.group ?? map;
}

let lastData = null;

function updateStatus() {
  if (!lastData) return;
  const total = markers.size;
  const shown = [...markers.values()].filter(({ line }) => {
    const l = lines.get(line);
    return !l || map.hasLayer(l.group);
  }).length;
  const generated = lastData.generated ? new Date(lastData.generated) : null;
  const ageMin = generated ? Math.round((Date.now() - generated.getTime()) / 60000) : null;
  const filtered = shown < total ? ` (${shown} shown)` : "";
  statusEl.textContent = !generated
    ? "No data yet - check back shortly"
    : total === 0
      ? `No GO trains running right now - checked ${ageMin}m ago`
      : `${total} GO train${total === 1 ? "" : "s"} running${filtered} - updated ${ageMin}m ago`;
}

async function refresh() {
  try {
    const res = await fetch("/api/trains");
    lastData = await res.json();
  } catch (err) {
    statusEl.textContent = "Couldn't reach tracker API";
    return;
  }

  const seen = new Set();
  for (const train of lastData.trains ?? []) {
    if (train.lat == null || train.lon == null) continue;
    seen.add(train.tripId);

    const latLng = [train.lat, train.lon];
    const icon = trainIcon(train);
    const entry = markers.get(train.tripId);
    if (entry && entry.line === train.line) {
      entry.marker.setLatLng(latLng);
      entry.marker.setIcon(icon);
      entry.marker.setPopupContent(popupHtml(train));
    } else {
      entry?.marker.remove();
      const marker = L.marker(latLng, { icon }).bindPopup(popupHtml(train)).addTo(layerFor(train.line));
      markers.set(train.tripId, { marker, line: train.line });
    }
  }

  // Drop markers for trains no longer in the feed (trip ended, etc.)
  for (const [tripId, { marker }] of markers) {
    if (!seen.has(tripId)) {
      marker.remove();
      markers.delete(tripId);
    }
  }

  updateStatus();
}

// Draw lines first so the first trains already have colours, groups and station names.
drawLines().then(refresh);
setInterval(refresh, 30000); // snapshot only changes every 2 min
