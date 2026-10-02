# in4m.ca

A personal dashboard, built with [Astro](https://astro.build) and deployed to GitHub Pages at <https://in4m.ca>.

Each tile is a self-contained component in `src/components/` and is laid out as a bento grid in `src/pages/index.astro`.

The `EN | 中` toggle switches between English and Simplified Chinese; the choice is saved in the browser, and a first visit follows the browser's language. Static text is written as `<T zh="…">English</T>` (`src/components/T.astro`); text built by a tile's script comes from that tile's `en`/`zh` strings and is redrawn on change (`src/i18n.ts`). Hacker News and On this day stay in English; Kid events are translated by the pipeline (below).

| Tile | Source |
| :--- | :----- |
| Clock | Toronto / Beijing time, lunar date, Ontario holidays, 黄历 (computed at build time) |
| Weather | [Open-Meteo](https://open-meteo.com), fetched in the browser |
| GO Train | Barrie line, Maple ⇄ Union, from the Metrolinx GTFS feed (`src/data/go-barrie.json`) |
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

## Deploy

`.github/workflows/deploy.yml` builds and publishes to GitHub Pages on every push to `main`, and once a day (05:00 Toronto) so the GO timetable and the almanac window roll forward. Before each build it runs `scripts/go-schedule.py`; if the Metrolinx download fails, the last good timetable is kept and the tile shows a stale warning.

## Scripts

Python helpers live in `scripts/` and are run with [uv](https://docs.astral.sh/uv/) (`uv sync` once, then `uv run scripts/<name>.py`).

- `go-schedule.py` regenerates `src/data/go-barrie.json`. It uses only the standard library and runs in CI.
- `kid-digest.py` builds `src/data/son.enc.json`. It runs daily on a NAS (see `kid-digest.Dockerfile`), never in CI. It reads new mail from two Gmail accounts over IMAP, uses DeepSeek to pick out school and activity emails and extract dated events, translates each upcoming event into English and Simplified Chinese (cached, so only new or changed events are sent), encrypts the upcoming events with AES-GCM (key from PBKDF2), then commits and pushes so the site redeploys. Configuration comes from environment variables; see `kid-digest.env.example`. The ciphertext is public, so the passphrase must be long and random.
- `kid-digest-known-senders.txt` lists sender domains that skip the AI relevance check.
- `list-senders.py` is a one-off helper for building that list.
