"""One-off: add the 9 weekly JUMP Basketball sessions from the forwarded order
confirmation (Order #162792, too old for the pipeline's incremental IMAP sync)
to state.json. Only touches state.json -- the next normal kid-digest.py run
(Task Scheduler, in Docker) will pick these up and encrypt+publish them as
usual, since it always regenerates son.enc.json from the full state on every
run, not just from newly-extracted events.

Run directly on the NAS host, no git/Docker needed for this step:

    python3 _manual_add_jump_events.py

Then delete this file. To publish immediately instead of waiting for the
next scheduled run, trigger the kid-digest Task Scheduler job manually from
DSM (Control Panel > Task Scheduler > kid-digest > Run).
"""

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

STATE_PATH = Path("/volume1/docker/kid-digest/state/state.json")

state = json.loads(STATE_PATH.read_text())

start = date(2026, 10, 4)
assert start.weekday() == 6, "expected Oct 4 2026 to be a Sunday"

school = "Ecole Secondaire Catholique de l'Ascension"
addr = "200 Aberdeen Ave (Langstaff Rd & Pine Valley Dr)"
loc = school + ", " + addr + ", Vaughan"
link = "https://maps.app.goo.gl/Q2ZTpZfdeypWAzmh6"
src_id = "manual-2026-09-29-jump-order"

new_events = []
for i in range(9):
    d = start + timedelta(weeks=i)
    title = "Basketball: Intro to Basketball (Gr 1,2)"
    title = title + " - Week " + str(i + 1) + "/9"
    desc = "JUMP Basketball, " + loc + ". Order #162792."
    ev = {}
    ev["id"] = "evt_" + uuid.uuid4().hex[:8]
    ev["title"] = title
    ev["date"] = d.isoformat()
    ev["time"] = "12:00"
    ev["category"] = "activity"
    ev["description"] = desc
    ev["links"] = [link]
    ev["status"] = "active"
    ev["sourceMessageIds"] = [src_id]
    new_events.append(ev)

state["events"].extend(new_events)
STATE_PATH.write_text(json.dumps(state, indent=2))
print("Added events:", len(new_events))
for ev in new_events:
    print(" ", ev["date"], ev["title"])
