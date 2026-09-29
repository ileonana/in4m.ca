"""One-off: add the 9 weekly JUMP Basketball sessions from the forwarded order
confirmation (Order #162792, too old for the pipeline's incremental IMAP sync)
to state.json, then regenerate son.enc.json the same way kid-digest.py's
public_payload/encrypt_payload does.

Run on the NAS from the repo checkout, after `git pull`:

    python3 scripts/_manual_add_jump_events.py

Delete this file (and commit the deletion) once it's been run -- it's a
one-off, not part of the regular pipeline.
"""

import base64
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT.parent
STATE_PATH = BASE / "state" / "state.json"
ENV_PATH = BASE / "kid-digest.env"
OUT_PATH = REPO_ROOT / "src" / "data" / "son.enc.json"
ITERS = 600_000

passphrase = None
for line in ENV_PATH.read_text().splitlines():
    if line.startswith("KID_DIGEST_PASSPHRASE="):
        passphrase = line.split("=", 1)[1].strip()
assert passphrase, "KID_DIGEST_PASSPHRASE not found in " + str(ENV_PATH)

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

today = date.today().isoformat()
fields = ("title", "date", "time", "category", "description", "links")
events = []
for e in state["events"]:
    if e["status"] == "active" and e["date"] >= today:
        row = {}
        for k in fields:
            row[k] = e[k]
        events.append(row)
events.sort(key=lambda e: (e["date"], e["time"] or ""))

now = datetime.now(timezone.utc)
payload = {}
payload["generated"] = now.isoformat(timespec="seconds")
payload["events"] = events

salt = os.urandom(16)
iv = os.urandom(12)
kdf = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,
    salt=salt,
    iterations=ITERS,
)
key = kdf.derive(passphrase.encode())
plaintext = json.dumps(payload).encode()
ciphertext = AESGCM(key).encrypt(iv, plaintext, None)

out = {}
out["salt"] = base64.b64encode(salt).decode()
out["iv"] = base64.b64encode(iv).decode()
out["iterations"] = ITERS
out["ciphertext"] = base64.b64encode(ciphertext).decode()

OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
print("Wrote", OUT_PATH, "with", len(events), "events")
