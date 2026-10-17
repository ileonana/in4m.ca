const map = L.map("map").setView([44.0, -79.5], 9); // Union <-> Allandale Waterfront corridor

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const markers = new Map(); // tripId -> L.Marker
const stationNames = new Map(); // stop code ("UN") -> name ("Union Station")
const statusEl = document.getElementById("status");

// Feed values end up in popup HTML, so escape them.
function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function stationName(code) {
  return stationNames.get(code) ?? code;
}

// Track and stations from public/line.json (built by scripts/build-line.py).
async function drawLine() {
  try {
    const line = await (await fetch("/line.json")).json();
    L.polyline(line.shape, { color: "#003767", weight: 4, opacity: 0.6 }).addTo(map);
    for (const s of line.stations) {
      stationNames.set(s.code, s.name);
      L.circleMarker([s.lat, s.lon], {
        radius: 5, color: "#003767", weight: 2, fillColor: "#fff", fillOpacity: 1,
      }).addTo(map).bindTooltip(esc(s.name));
    }
  } catch {
    // Map still works without it; popups fall back to stop codes.
  }
}

function trainIcon(bearing) {
  const rotation = typeof bearing === "number" ? bearing : 0;
  return L.divIcon({
    className: "",
    html: `<div class="train-icon" style="transform: rotate(${rotation}deg)">&#10148;</div>`,
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
  const heading = train.finalStop ? ` &rarr; ${esc(stationName(train.finalStop.stopId))}` : "";
  return `
    <div class="popup-eta">
      <strong>${esc(train.label ?? train.tripId)}${heading}</strong>
      ${formatEta(train.nextStop, "Next stop")}
      ${formatEta(train.finalStop, "Terminus")}
    </div>
  `;
}

async function refresh() {
  let data;
  try {
    const res = await fetch("/api/trains");
    data = await res.json();
  } catch (err) {
    statusEl.textContent = "Couldn't reach tracker API";
    return;
  }

  const seen = new Set();
  for (const train of data.trains ?? []) {
    if (train.lat == null || train.lon == null) continue;
    seen.add(train.tripId);

    const latLng = [train.lat, train.lon];
    const icon = trainIcon(train.bearing);
    let marker = markers.get(train.tripId);
    if (marker) {
      marker.setLatLng(latLng);
      marker.setIcon(icon);
      marker.setPopupContent(popupHtml(train));
    } else {
      marker = L.marker(latLng, { icon }).addTo(map).bindPopup(popupHtml(train));
      markers.set(train.tripId, marker);
    }
  }

  // Drop markers for trains no longer in the feed (trip ended, etc.)
  for (const [tripId, marker] of markers) {
    if (!seen.has(tripId)) {
      map.removeLayer(marker);
      markers.delete(tripId);
    }
  }

  const trainCount = seen.size;
  const generated = data.generated ? new Date(data.generated) : null;
  const ageMin = generated ? Math.round((Date.now() - generated.getTime()) / 60000) : null;
  statusEl.textContent = !generated
    ? "No data yet - check back shortly"
    : trainCount === 0
      ? `No Barrie line trains running right now - checked ${ageMin}m ago`
      : `${trainCount} train${trainCount === 1 ? "" : "s"} on the Barrie line - updated ${ageMin}m ago`;
}

// Draw stations first so the first popups already have names.
drawLine().then(refresh);
setInterval(refresh, 30000); // snapshot only changes every 2 min
