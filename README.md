# in4m.ca

A personal dashboard, built with [Astro](https://astro.build) and deployed to GitHub Pages at <https://in4m.ca>, plus a live GO train map at <https://go.in4m.ca> (a separate Cloudflare Worker, below).

Each tile is a self-contained component in `src/components/` and is laid out as a bento grid in `src/pages/index.astro`.

The `EN | 中` toggle switches between English and Simplified Chinese; the choice is saved in the browser, and a first visit follows the browser's language. Static text is written as `<T zh="…">English</T>` (`src/components/T.astro`); text built by a tile's script comes from that tile's `en`/`zh` strings and is redrawn on change (`src/i18n.ts`). Hacker News and On this day stay in English; Kid events are translated by the pipeline (below).

| Tile | Source |
| :--- | :----- |
| Clock | Toronto / Beijing time, lunar date, Ontario holidays, 黄历 (computed at build time) |
| Weather | [Open-Meteo](https://open-meteo.com), fetched in the browser |
| GO Train | Barrie line, Maple ⇄ Union scheduled times from the Metrolinx GTFS feed (`src/data/go-barrie.json`), with a link to the live map |
| Rates | [Bank of Canada Valet](https://www.bankofcanada.ca/valet/), fetched in the browser |
| Hacker News | Firebase API, fetched in the browser |
| On this day | Wikipedia REST feed, fetched in the browser |
| Kid | Encrypted upcoming school/activity events (`src/data/son.enc.json`), decrypted in the browser with a passphrase |

## Commands

| Command           | Action                                       |
| :---------------- | :------------------------------------------- |
| `npm install`     | Install dependencies                         |
| `npm run dev`     | Start the dev server at `localhost:4321`     |
| `npm run build`   | Build the production site to `./dist/`       |
| `npm run preview` | Preview the production build locally         |

The live map has its own commands; see [GO train live map](#go-train-live-map).

## Deploy

`.github/workflows/deploy.yml` builds and publishes to GitHub Pages on every push to `main`, and once a day (05:00 Toronto) so the GO timetable and the almanac window roll forward. Before each build it runs `scripts/go-schedule.py`; if the Metrolinx download fails, the last good timetable (kept in the Actions cache) is used and the tile shows a stale warning.

The live map deploys separately; see below.

## Scripts

Python helpers live in `scripts/` and are run with [uv](https://docs.astral.sh/uv/) (`uv sync` once, then `uv run scripts/<name>.py`).

- `go-schedule.py` regenerates `src/data/go-barrie.json`. It uses only the standard library and runs in CI.
- `kid-digest.py` builds `src/data/son.enc.json`. It runs daily on a NAS (see `kid-digest.Dockerfile`), never in CI. It reads new mail from two Gmail accounts over IMAP, uses DeepSeek to pick out school and activity emails and extract dated events, translates each upcoming event into English and Simplified Chinese (cached, so only new or changed events are sent), encrypts the upcoming events with AES-GCM (key from PBKDF2), then commits and pushes so the site redeploys. Configuration comes from environment variables; see `kid-digest.env.example`. The ciphertext is public, so the passphrase must be long and random.
- `kid-digest-known-senders.txt` lists sender domains that skip the AI relevance check.
- `list-senders.py` is a one-off helper for building that list.
- `_manual_add_jump_events.py` is a one-off NAS helper that added events too old for the pipeline's mail sync.

## GO train live map

`workers/go-tracker/` is a Cloudflare Worker serving a [Leaflet](https://leafletjs.com) map of every GO train on all 7 lines (no buses) at <https://go.in4m.ca>. It is deployed separately from the Pages site.

- Every 2 minutes a Cron Trigger fetches Metrolinx's realtime vehicle positions and trip updates, keeps the GO trains, and saves one snapshot to Workers KV. Visitors only ever read that snapshot (`/api/trains`), so the Metrolinx API key stays on Cloudflare and the API sees 2 calls every 2 minutes, however many people have the map open.
- The map draws each line in its GO colour with its track and stations (`public/line.json`), with toggles to show or hide each line. Each train is an arrow pointing toward its next stop; its popup shows the line, destination, next stop and ETAs, and how late or early it is running.
- `.github/workflows/deploy-go-tracker.yml` deploys it on any push to `main` that touches `workers/go-tracker/`.

| Command (from `workers/go-tracker/`) | Action |
| :----------------------------------- | :----- |
| `npm install`                        | Install dependencies |
| `npm run dev`                        | Run the Worker locally with `wrangler dev` |
| `npm run typecheck`                  | Type-check the Worker |
| `npm run deploy`                     | Deploy by hand (CI normally does this) |
| `uv run scripts/build-line.py`       | Rebuild `public/line.json` from the public GTFS feed (needed only when stations or lines change) |

See `AGENTS.md` for how it works and the realtime feed's quirks.
