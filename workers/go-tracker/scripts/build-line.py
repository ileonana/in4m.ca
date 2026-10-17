"""Build public/line.json: GO train lines, track shapes and stations for the live map.

Reads the public Metrolinx GO GTFS feed (no API key needed) and writes, for every
GO train line, its name, colour and track shapes, plus each station (code -> name,
position, lines served). Stations rarely change, so this is a by-hand refresh, not
a cron.

Lines are keyed by the code at the end of their route_id ("09261126-GT" -> "GT"),
which is also what the realtime feed uses -- note Kitchener is "GT" (its old
Georgetown code), not "KI".

Usage (from workers/go-tracker/): uv run scripts/build-line.py [path/to/GO-GTFS.zip]
"""

import csv
import io
import json
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

GTFS_URL = "https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
OUT = Path(__file__).resolve().parent.parent / "public" / "line.json"
RAIL = "2"  # GTFS route_type for rail
TOLERANCE = 0.0001  # degrees (~10 m) when simplifying track shapes


def rows(zf, name):
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def simplify(points, tol):
    """Ramer-Douglas-Peucker: drop points that lie within `tol` of the line between neighbours."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (y1, x1), (y2, x2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, idx = 0.0, None
        for i in range(a + 1, b):
            y, x = points[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def main():
    if len(sys.argv) > 1:
        zf = zipfile.ZipFile(sys.argv[1])
    else:
        print("Downloading GTFS feed...", file=sys.stderr)
        with urllib.request.urlopen(GTFS_URL) as r:
            zf = zipfile.ZipFile(io.BytesIO(r.read()))

    lines = {}  # route_id -> line dict
    for r in rows(zf, "routes.txt"):
        if r["route_type"] == RAIL:
            lines[r["route_id"]] = {
                "code": r["route_id"].rsplit("-", 1)[-1],
                "name": r["route_long_name"],
                "color": "#" + r["route_color"].lower(),
                "shapes": [],
            }

    trip_line = {}  # trip_id -> route_id
    shape_ids = defaultdict(set)  # route_id -> shape_ids
    for t in rows(zf, "trips.txt"):
        if t["route_id"] in lines:
            trip_line[t["trip_id"]] = t["route_id"]
            if t["shape_id"]:
                shape_ids[t["route_id"]].add(t["shape_id"])

    station_lines = defaultdict(set)  # stop_id -> line codes
    for st in rows(zf, "stop_times.txt"):
        route_id = trip_line.get(st["trip_id"])
        if route_id:
            station_lines[st["stop_id"]].add(lines[route_id]["code"])

    wanted = set().union(*shape_ids.values())
    raw = defaultdict(list)
    for p in rows(zf, "shapes.txt"):
        if p["shape_id"] in wanted:
            raw[p["shape_id"]].append((int(p["shape_pt_sequence"]), float(p["shape_pt_lat"]), float(p["shape_pt_lon"])))

    for route_id, line in lines.items():
        # Shapes come in pairs named by endpoints ("ADUN" / "UNAD"); one direction is enough.
        seen = set()
        for shape_id in sorted(shape_ids[route_id]):
            pair = frozenset((shape_id[:2], shape_id[2:]))
            if pair in seen or shape_id not in raw:
                continue
            seen.add(pair)
            points = [(lat, lon) for _, lat, lon in sorted(raw[shape_id])]
            line["shapes"].append([[round(lat, 5), round(lon, 5)] for lat, lon in simplify(points, TOLERANCE)])

    stations = [
        {
            "code": s["stop_id"],
            "name": s["stop_name"].removesuffix(" GO"),
            "lat": round(float(s["stop_lat"]), 5),
            "lon": round(float(s["stop_lon"]), 5),
            "lines": sorted(station_lines[s["stop_id"]]),
        }
        for s in rows(zf, "stops.txt")
        if s["stop_id"] in station_lines
    ]
    if not lines or not stations or not all(l["shapes"] for l in lines.values()):
        raise RuntimeError("feed is missing GO train lines, shapes or stations")

    out = {"lines": sorted(lines.values(), key=lambda l: l["name"]), "stations": sorted(stations, key=lambda s: s["name"])}
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    points = sum(len(s) for l in lines.values() for s in l["shapes"])
    print(f"Wrote {len(lines)} lines, {len(stations)} stations, {points} shape points to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
