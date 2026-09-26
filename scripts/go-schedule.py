"""Build src/data/go-barrie.json: Barrie line trains between Maple and Union.

Reads the public Metrolinx GO GTFS feed (no API key needed) and writes, for each
service date, the scheduled trains in each direction with their departure from
the origin station and arrival at the destination.

Usage: uv run scripts/go-schedule.py [path/to/GO-GTFS.zip]
"""

import csv
import io
import json
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

GTFS_URL = "https://assets.metrolinx.com/raw/upload/Documents/Metrolinx/Open%20Data/GO-GTFS.zip"
OUT = Path(__file__).resolve().parent.parent / "src" / "data" / "go-barrie.json"
ROUTE = "BR"
MAPLE, UNION = "MP", "UN"


def rows(zf, name):
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def hhmm(t):
    # GTFS times can pass 24:00 for trips after midnight; keep them as-is.
    h, m, _ = t.split(":")
    return f"{int(h):02d}:{m}"


def main():
    if len(sys.argv) > 1:
        zf = zipfile.ZipFile(sys.argv[1])
    else:
        print("Downloading GTFS feed...", file=sys.stderr)
        with urllib.request.urlopen(GTFS_URL) as r:
            zf = zipfile.ZipFile(io.BytesIO(r.read()))

    route_ids = {r["route_id"] for r in rows(zf, "routes.txt") if r["route_short_name"] == ROUTE}
    trips = {
        t["trip_id"]: t
        for t in rows(zf, "trips.txt")
        if t["route_id"] in route_ids
    }

    stops = defaultdict(dict)  # trip_id -> {stop_id: (sequence, arrival, departure)}
    for st in rows(zf, "stop_times.txt"):
        if st["trip_id"] in trips and st["stop_id"] in (MAPLE, UNION):
            stops[st["trip_id"]][st["stop_id"]] = (
                int(st["stop_sequence"]),
                st["arrival_time"],
                st["departure_time"],
            )

    dates_by_service = defaultdict(list)
    for c in rows(zf, "calendar_dates.txt"):
        if c["exception_type"] == "1":
            d = c["date"]
            dates_by_service[c["service_id"]].append(f"{d[:4]}-{d[4:6]}-{d[6:]}")

    days = defaultdict(lambda: {"toUnion": [], "toMaple": []})
    for trip_id, t in trips.items():
        s = stops.get(trip_id, {})
        if MAPLE not in s or UNION not in s:
            continue
        (m_seq, m_arr, m_dep), (u_seq, u_arr, u_dep) = s[MAPLE], s[UNION]
        if m_seq < u_seq:
            direction, dep, arr = "toUnion", hhmm(m_dep), hhmm(u_arr)
        else:
            direction, dep, arr = "toMaple", hhmm(u_dep), hhmm(m_arr)
        train = {"dep": dep, "arr": arr}
        for date in dates_by_service[t["service_id"]]:
            days[date][direction].append(train)

    for day in days.values():
        for trains in day.values():
            trains.sort(key=lambda x: x["dep"])

    feed = next(rows(zf, "feed_info.txt"))
    out = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feedEnd": f"{feed['feed_end_date'][:4]}-{feed['feed_end_date'][4:6]}-{feed['feed_end_date'][6:]}",
        "days": dict(sorted(days.items())),
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"Wrote {OUT} ({len(days)} days)", file=sys.stderr)


if __name__ == "__main__":
    main()
