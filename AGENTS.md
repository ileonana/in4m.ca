## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## This repo is public

The GitHub repo is public, and so is everything in its history. Never commit secrets
(API keys, app passwords, the kid-digest passphrase, `.env` / `.dev.vars` files) or
plaintext personal data -- in particular, kid events are published only as ciphertext
(`src/data/son.enc.json`). Keep NAS hostnames, IPs and paths out of committed files.

## Kid digest (runs on a NAS, not CI)

`scripts/kid-digest.py` runs daily on the owner's NAS in Docker
(`scripts/kid-digest.Dockerfile`) and commits only the encrypted
`src/data/son.enc.json`, which triggers a normal Pages deploy. Code changes reach the NAS
only when the owner pulls there by hand. The NAS host has no `git` installed, so any pull
goes through a Docker `alpine/git` container -- never suggest a plain `git pull` on it.

## GO Train Tracker (Cloudflare Worker)

`workers/go-tracker/` is a separate Cloudflare Worker, independent of the Astro site's
GitHub Pages deploy. It serves a live map of all 7 GO train lines (no buses) at
`go.in4m.ca`. The site's GO tile (`src/components/GoTrain.astro`) links to it.

### Pipeline

- A Cron Trigger (`*/2 * * * *`) fetches Metrolinx's `Gtfs/Feed/VehiclePosition` and
  `Gtfs/Feed/TripUpdates` endpoints (plain JSON, despite the "Gtfs" name -- confirmed by
  inspecting a live response, not protobuf), keeps GO trains, and writes one JSON
  snapshot to a KV namespace (`TRAIN_STATE`, key `snapshot`, 10-minute TTL so stale data
  clears itself if the cron stops). The `scheduled` handler awaits the refresh, so a
  failed Metrolinx call shows as an errored run in the Cloudflare dashboard's cron events.
- The Worker's `fetch` handler serves that snapshot at `/api/trains` and the static
  Leaflet map page from `public/`. Browser traffic never calls Metrolinx directly --
  only the cron job does, so client load never affects the upstream call volume. The map
  polls `/api/trains` every 30 s.
- Cadence is every 2 minutes, not 1, to stay under Workers KV's free-tier 1,000
  writes/day quota. (R2 would remove that constraint but isn't enabled on the Cloudflare
  account yet -- needs a dashboard opt-in plus a payment method on file.)
- Metrolinx's documented limit is 300 calls/second; this pipeline uses 2 calls every 2
  minutes regardless of visitor traffic, nowhere close. The key "may get disabled if
  extensive API calls are detected", so never add per-visitor or retry-loop calls. The
  usage guide PDF is confidential and gitignored -- never commit it.
- Each snapshot lands about 56 s after its cron minute (time spent waiting on Metrolinx or
  the cron start), and the snapshot's `generated` time is stamped after the response. ETAs
  are absolute times, so the browser's "X min" countdown is unaffected; train positions
  can be up to ~3.5 min old. The owner is fine with this.

### Realtime feed quirks (seen in live data, 2026-10-17)

- **Line codes:** the line is the code after the last `-` of `route_id` (e.g.
  `09261126-BR`; the prefix is a schedule-revision code that changes, so never match the
  whole string). Trains: `BR`, `GT`, `LE`, `LW`, `MI`, `RH`, `ST`. Kitchener is `GT` (its
  old Georgetown code), not `KI`. Buses have numeric codes and are dropped. `route_id` is
  optional in GTFS-realtime, so the Worker falls back to the trip_id's middle segment
  (`20261017-GT-3959`).
- **No heading:** `bearing` and `speed` are 0 for every train. The map points each arrow
  from the train toward its next stop (toward the terminus when within 400 m of the next
  stop; a dot when at the terminus too). It uses the feed's bearing automatically if
  Metrolinx ever sends a real one.
- **`direction_id` is unreliable:** in the static schedule 1 means "to Union" on every
  line, but the live feed has it the other way round on Lakeshore West and Kitchener. If
  inbound/outbound is ever needed, use "final stop is `UN`" instead. Every scheduled GO
  train trip starts or ends at Union, except Lakeshore West's Aldershot <-> Niagara Falls
  trains.
- **Passed stops:** `stop_time_update` may still list stops already passed, so "next
  stop" is the first one whose time hasn't gone by (30 s slack).
- Train `label`s look like `GT - Stratford GO` (line code + headsign).

### Map data

- Line names/colours, simplified track shapes, and station names/positions/lines come
  from `public/line.json`, built from the public static GTFS zip (no API key) by
  `uv run scripts/build-line.py` (run from `workers/go-tracker/`). Re-run it by hand if
  Metrolinx adds or renames a station or line, and keep `TRAIN_LINES` in `src/index.ts`
  in sync with its line codes.
- Which lines a viewer has toggled off is remembered per browser in `localStorage`.

### Deploy and local work

- Deploys via `.github/workflows/deploy-go-tracker.yml` on push to `main` touching
  `workers/go-tracker/**` (runs `npm ci` and the typecheck first), using the
  `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` repo secrets. The Metrolinx key is a
  Worker secret (`GO_API_KEY`, set via `wrangler secret put`), not a GitHub secret.
- Local commands (run from `workers/go-tracker/`): `npm run dev`, `npm run deploy`,
  `npm run typecheck`. The key isn't available locally, so test with a fake snapshot
  (`npx wrangler kv key put --binding TRAIN_STATE --local snapshot '<json>'`) or by
  calling the bundled `scheduled()` with mocked feeds -- don't point the real API at a
  dummy key. If you do put a real key in `.dev.vars` for local testing, it is gitignored;
  keep it that way.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
