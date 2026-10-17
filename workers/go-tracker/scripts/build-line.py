"""Build public/line.json: Barrie line stations and track shape for the live map.

Reads the public Metrolinx GO GTFS feed (no API key needed) and writes each station
the Barrie line serves (code -> name + position) plus the Allandale Waterfront ->
Union track shape. Stations rarely change, so this is a by-hand refresh, not a cron.

Usage (from workers/go-tracker/): uv run scripts/build-line.py [path/to/GO-GTFS.zip]
"""

import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

GTFS_URL = "https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
OUT = Path(__file__).resolve().parent.parent / "public" / "line.json"
ROUTE = "BR"
SHAPE = "ADUN"  # full line, Allandale Waterfront -> Union


def rows(zf, name):
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def main():
    if len(sys.argv) > 1:
        zf = zipfile.ZipFile(sys.argv[1])
    else:
        print("Downloading GTFS feed...", file=sys.stderr)
        with urllib.request.urlopen(GTFS_URL) as r:
            zf = zipfile.ZipFile(io.BytesIO(r.read()))

    route_ids = {r["route_id"] for r in rows(zf, "routes.txt") if r["route_short_name"] == ROUTE}
    trip_ids = {t["trip_id"] for t in rows(zf, "trips.txt") if t["route_id"] in route_ids}
    stop_ids = {st["stop_id"] for st in rows(zf, "stop_times.txt") if st["trip_id"] in trip_ids}

    shape = sorted(
        (int(p["shape_pt_sequence"]), round(float(p["shape_pt_lat"]), 5), round(float(p["shape_pt_lon"]), 5))
        for p in rows(zf, "shapes.txt")
        if p["shape_id"] == SHAPE
    )
    if not stop_ids or not shape:
        raise RuntimeError("feed contained no Barrie line stops or shape")

    # Order stations along the line (north -> south) by latitude.
    stations = sorted(
        (
            {
                "code": s["stop_id"],
                "name": s["stop_name"].removesuffix(" GO"),
                "lat": round(float(s["stop_lat"]), 5),
                "lon": round(float(s["stop_lon"]), 5),
            }
            for s in rows(zf, "stops.txt")
            if s["stop_id"] in stop_ids
        ),
        key=lambda s: -s["lat"],
    )

    OUT.write_text(json.dumps({"stations": stations, "shape": [[lat, lon] for _, lat, lon in shape]}) + "\n")
    print(f"Wrote {len(stations)} stations, {len(shape)} shape points to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
