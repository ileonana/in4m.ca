const map = L.map("map").setView([44.0, -79.5], 9); // Union <-> Allandale Waterfront corridor

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 18,
}).addTo(map);

const markers = new Map(); // tripId -> L.Marker
const statusEl = document.getElementById("status");

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

function formatEta(stop, label) {
  if (!stop) return "";
  const mins = minutesUntil(stop.eta);
  const delay = stop.delaySeconds ? ` (+${Math.round(stop.delaySeconds / 60)}m delay)` : "";
  const when = mins === null ? "unknown" : mins <= 0 ? "arriving" : `${mins} min`;
  return `<b>${label}: ${stop.stopId}</b>${when}${delay}`;
}

function popupHtml(train) {
  return `
    <div class="popup-eta">
      <strong>${train.label ?? train.tripId}</strong>
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

  const trainCount = data.trains?.length ?? 0;
  const generated = data.generated ? new Date(data.generated) : null;
  const ageMin = generated ? Math.round((Date.now() - generated.getTime()) / 60000) : null;
  statusEl.textContent = generated
    ? `${trainCount} train${trainCount === 1 ? "" : "s"} on the Barrie line - updated ${ageMin}m ago`
    : "No data yet - check back shortly";
}

refresh();
setInterval(refresh, 20000);
