// GO Transit live train tracker (all 7 GO train lines, no buses).
//
// A Cron Trigger polls Metrolinx's GTFS-realtime feeds (JSON, despite the
// "Gtfs" name -- confirmed by hand, see AGENTS.md) every 2
// minutes, keeps only GO trains, and writes one small snapshot to
// KV. The public /api/trains route only ever reads that snapshot, so
// browser traffic never touches Metrolinx's API directly or affects its
// call volume.
//
// Real-time route_id values look like "09261126-BR" -- a schedule-revision
// prefix plus a line code -- so we read the code after the last "-" rather
// than matching whole strings, in case the prefix changes when Metrolinx
// publishes a new schedule. Train lines have letter codes (Kitchener is "GT",
// its old Georgetown code); buses have numbers ("09261126-41") and are
// skipped. route_id is optional in GTFS-realtime, so we fall back to trip_ids
// shaped like "20261127-BR-6606" (the format the static feed uses).

export interface Env {
  TRAIN_STATE: KVNamespace;
  ASSETS: Fetcher;
  GO_API_KEY: string;
}

// Must match the line codes in public/line.json (scripts/build-line.py).
const TRAIN_LINES = new Set(["BR", "GT", "LE", "LW", "MI", "RH", "ST"]);
const FEED_BASE = "https://api.openmetrolinx.com/OpenDataAPI/api/V1/Gtfs/Feed";
const SNAPSHOT_KEY = "snapshot";

interface StopTimeEvent {
  time?: number | null;
  delay?: number | null;
}

interface StopTimeUpdate {
  stop_id: string;
  arrival: StopTimeEvent | null;
  departure: StopTimeEvent | null;
}

interface TripUpdateEntity {
  trip_update?: {
    trip: { trip_id: string; route_id?: string; direction_id: number };
    stop_time_update: StopTimeUpdate[];
  } | null;
}

interface VehicleEntity {
  vehicle?: {
    trip: { trip_id: string; route_id?: string; direction_id: number; start_time: string };
    vehicle?: { id: string; label: string };
    position?: { latitude: number; longitude: number; bearing: number; speed: number };
    stop_id?: string;
    current_status?: string;
    timestamp?: number;
  } | null;
}

interface StopEta {
  stopId: string;
  eta: string | null;
  delaySeconds: number;
}

interface TrainSnapshot {
  tripId: string;
  line: string;
  vehicleId: string | null;
  label: string | null;
  directionId: number;
  lat: number | null;
  lon: number | null;
  bearing: number | null;
  speed: number | null;
  currentStopId: string | null;
  currentStatus: string | null;
  updatedAt: string | null;
  nextStop: StopEta | null;
  finalStop: StopEta | null;
}

// The GO train line code for a trip, or null for buses / anything unrecognised.
function trainLine(trip: { route_id?: string; trip_id?: string }): string | null {
  const fromRoute = trip.route_id?.split("-").pop();
  if (fromRoute && TRAIN_LINES.has(fromRoute)) return fromRoute;
  const fromTrip = trip.trip_id?.split("-")[1];
  return fromTrip && TRAIN_LINES.has(fromTrip) ? fromTrip : null;
}

async function fetchFeed(name: string, apiKey: string): Promise<any> {
  const res = await fetch(`${FEED_BASE}/${name}?key=${apiKey}`);
  if (!res.ok) {
    throw new Error(`${name} feed returned HTTP ${res.status}`);
  }
  return res.json();
}

function eventOf(update: StopTimeUpdate): StopTimeEvent | null {
  return update.departure ?? update.arrival;
}

// The feed may still list stops the train has already passed, so "next" is the
// first one whose time hasn't gone by yet (with a little slack for dwell time).
function nextUpdate(updates: StopTimeUpdate[], nowSec: number): StopTimeUpdate | undefined {
  return updates.find((u) => (eventOf(u)?.time ?? Infinity) >= nowSec - 30) ?? updates[updates.length - 1];
}

function toEta(update: StopTimeUpdate | undefined): StopEta | null {
  if (!update) return null;
  const event = eventOf(update);
  const time = event?.time;
  return {
    stopId: update.stop_id,
    eta: time ? new Date(time * 1000).toISOString() : null,
    delaySeconds: event?.delay ?? 0,
  };
}

async function refreshSnapshot(env: Env): Promise<void> {
  const [vehiclePositions, tripUpdates] = await Promise.all([
    fetchFeed("VehiclePosition", env.GO_API_KEY),
    fetchFeed("TripUpdates", env.GO_API_KEY),
  ]);

  const stopUpdatesByTrip = new Map<string, StopTimeUpdate[]>();
  for (const entity of (tripUpdates.entity ?? []) as TripUpdateEntity[]) {
    const tu = entity.trip_update;
    if (tu && trainLine(tu.trip)) {
      stopUpdatesByTrip.set(tu.trip.trip_id, tu.stop_time_update ?? []);
    }
  }

  const nowSec = Date.now() / 1000;
  const trains: TrainSnapshot[] = [];
  for (const entity of (vehiclePositions.entity ?? []) as VehicleEntity[]) {
    const v = entity.vehicle;
    const line = v && trainLine(v.trip);
    if (!v || !line) continue;

    const stopUpdates = stopUpdatesByTrip.get(v.trip.trip_id) ?? [];
    trains.push({
      tripId: v.trip.trip_id,
      line,
      vehicleId: v.vehicle?.id ?? null,
      label: v.vehicle?.label ?? null,
      directionId: v.trip.direction_id,
      lat: v.position?.latitude ?? null,
      lon: v.position?.longitude ?? null,
      bearing: v.position?.bearing ?? null,
      speed: v.position?.speed ?? null,
      currentStopId: v.stop_id ?? null,
      currentStatus: v.current_status ?? null,
      updatedAt: v.timestamp ? new Date(v.timestamp * 1000).toISOString() : null,
      nextStop: toEta(nextUpdate(stopUpdates, nowSec)),
      finalStop: toEta(stopUpdates[stopUpdates.length - 1]),
    });
  }

  await env.TRAIN_STATE.put(
    SNAPSHOT_KEY,
    JSON.stringify({ generated: new Date().toISOString(), trains }),
    { expirationTtl: 600 } // stale data self-clears if the cron ever stops firing
  );
}

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
};

export default {
  // Awaited (not waitUntil) so a failed Metrolinx call marks the cron run as
  // errored in the dashboard instead of disappearing.
  async scheduled(_controller: ScheduledController, env: Env) {
    await refreshSnapshot(env);
  },

  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/trains") {
      const snapshot = await env.TRAIN_STATE.get(SNAPSHOT_KEY);
      return new Response(snapshot ?? JSON.stringify({ generated: null, trains: [] }), {
        headers: {
          "content-type": "application/json",
          "cache-control": "public, max-age=20",
          ...CORS_HEADERS,
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
