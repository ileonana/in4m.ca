## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## GO Train Tracker (Cloudflare Worker)

`workers/go-tracker/` is a separate Cloudflare Worker, independent of the Astro site's
GitHub Pages deploy. It serves a live map of GO Transit's Barrie line at `go.in4m.ca`.

- A Cron Trigger (`*/2 * * * *`) fetches Metrolinx's `Gtfs/Feed/VehiclePosition` and
  `Gtfs/Feed/TripUpdates` endpoints (plain JSON, despite the "Gtfs" name -- confirmed by
  inspecting a live response, not protobuf), filters for trips whose `route_id` ends in
  `-BR` (the Barrie line; the prefix before it is a schedule-revision code that changes
  over time, so match the suffix, not the whole string), and writes one JSON snapshot to
  a KV namespace (`TRAIN_STATE`).
- The Worker's `fetch` handler serves that snapshot at `/api/trains` and the static
  Leaflet map page from `public/`. Browser traffic never calls Metrolinx directly --
  only the cron job does, so client load never affects the upstream call volume.
- Cadence is every 2 minutes, not 1, to stay under Workers KV's free-tier 1,000
  writes/day quota. (R2 would remove that constraint but isn't enabled on the Cloudflare
  account yet -- needs a dashboard opt-in plus a payment method on file.)
- Metrolinx's documented limit is 300 calls/second; this pipeline uses 2 calls every 2
  minutes regardless of visitor traffic, nowhere close. The usage guide PDF is
  confidential and gitignored -- never commit it.
- Deploys via `.github/workflows/deploy-go-tracker.yml` on push to
  `workers/go-tracker/**`, using the `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`
  repo secrets. The Metrolinx key is a Worker secret (`GO_API_KEY`, set via
  `wrangler secret put`), not a GitHub secret.
- Local commands (run from `workers/go-tracker/`): `npm run dev`, `npm run deploy`,
  `npm run typecheck`.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
