"""Build src/data/son.enc.json: upcoming school/activity events for [son], triaged from email.

Runs on the NAS (Synology Task Scheduler, hourly) -- never in CI. Reads new mail from
two Gmail accounts over IMAP, asks DeepSeek to classify which messages are about the
kid's school or extracurricular activities, extracts structured events from the relevant
ones, merges them into a private local state file, encrypts the current upcoming-events
list, and (if it changed) commits + pushes it so the existing GitHub Pages workflow
redeploys.

Each Gmail account needs 2-Step Verification enabled, plus a 16-character App Password
generated at https://myaccount.google.com/apppasswords -- no Google Cloud project or
OAuth consent screen needed.

Configuration is read entirely from environment variables (see NAS-local .env, never
committed to this repo):

    KID_NAME                    Name to use in AI prompts, e.g. "Sam"
    KID_DIGEST_ACCOUNTS         Comma-separated account labels, e.g. "lawrence,wife"
    GMAIL_<LABEL>_EMAIL         Per account (LABEL uppercased), e.g. GMAIL_LAWRENCE_EMAIL
    GMAIL_<LABEL>_APP_PASSWORD  The 16-character Gmail App Password
    DEEPSEEK_API_KEY
    DEEPSEEK_BASE_URL           default: https://api.deepseek.com
    DEEPSEEK_MODEL              default: deepseek-chat
    KID_DIGEST_PASSPHRASE       shared encryption passphrase (long, random)
    KID_DIGEST_STATE            path to the private state file, default ~/kid-digest/state.json
    KID_DIGEST_INITIAL_DAYS     lookback window for an account's first-ever run, default 14

Verify DEEPSEEK_MODEL and the JSON-mode request shape against DeepSeek's current docs
before relying on this in production -- their exact model IDs/params are outside this
script's knowledge and may have moved on.

Usage:
    uv run scripts/kid-digest.py [--dry-run]
"""

import base64
import email
import html.parser
import imaplib
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header
from pathlib import Path

import pymupdf
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "src" / "data" / "son.enc.json"
STATE_PATH = Path(os.environ.get("KID_DIGEST_STATE", str(Path.home() / "kid-digest" / "state.json")))

KID_NAME = os.environ.get("KID_NAME", "my son")
ACCOUNTS = [a.strip() for a in os.environ.get("KID_DIGEST_ACCOUNTS", "lawrence,wife").split(",") if a.strip()]
INITIAL_DAYS = int(os.environ.get("KID_DIGEST_INITIAL_DAYS", "14"))

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# deepseek-flash is the current vision-capable model (needed for the PDF-attachment
# best-effort path below) -- verify this is still current against DeepSeek's docs
# periodically, since model IDs and capabilities have moved before.
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

PBKDF2_ITERATIONS = 600_000
IMAP_HOST = "imap.gmail.com"
CLASSIFY_BATCH = 20
BODY_CHAR_CAP = 6000
MAX_PDF_ATTACHMENTS_PER_EMAIL = 2
MAX_PDF_PAGES = 2
PDF_RENDER_DPI = 150


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------


def imap_connect(account: str) -> imaplib.IMAP4_SSL:
    prefix = f"GMAIL_{account.upper()}"
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(os.environ[f"{prefix}_EMAIL"], os.environ[f"{prefix}_APP_PASSWORD"])
    conn.select("INBOX")
    return conn


def list_new_uids(conn: imaplib.IMAP4_SSL, since: datetime, processed_ids: set[str]) -> list[str]:
    date_str = since.strftime("%d-%b-%Y")
    status, data = conn.uid("search", None, f'(SINCE "{date_str}")')
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    uids = data[0].split() if data and data[0] else []
    return [u.decode() for u in uids if u.decode() not in processed_ids]


def decode_mime_header(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p for p, enc in parts)


def fetch_headers(conn: imaplib.IMAP4_SSL, uid: str) -> dict:
    # BODY.PEEK avoids marking the user's real inbox messages as read.
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
    if status != "OK" or not data or not isinstance(data[0], tuple):
        return {"id": uid, "subject": "", "from": ""}
    msg = email.message_from_bytes(data[0][1])
    return {"id": uid, "subject": decode_mime_header(msg.get("Subject", "")), "from": decode_mime_header(msg.get("From", ""))}


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def strip_html(text: str) -> str:
    p = _TextExtractor()
    p.feed(text)
    return " ".join(p.chunks)


def clean_body(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        # These mark the start of quoted history / a signature block -- everything
        # from here on is old thread content or a sign-off, not new information.
        if stripped == "--" or stripped.startswith("-----Original Message-----"):
            break
        if stripped.lower().startswith("on ") and stripped.endswith("wrote:"):
            break
        lines.append(line)
    return "\n".join(lines).strip()[:BODY_CHAR_CAP]


def render_pdf_pages(pdf_bytes: bytes) -> list[str]:
    """Best-effort: render the first few pages of a PDF attachment to base64 PNG data
    URLs, for the vision-capable model to read directly. Returns [] on any failure
    (corrupt PDF, unsupported content, etc.) -- attachment reading is a bonus, never
    something that should break the run."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for page in doc[:MAX_PDF_PAGES]:
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI)
            images.append(f"data:image/png;base64,{base64.b64encode(pix.tobytes('png')).decode()}")
        return images
    except Exception as e:
        print(f"PDF render failed, skipping attachment: {e}", file=sys.stderr)
        return []


def extract_body_from_email(msg: email.message.Message) -> tuple[str, list[str]]:
    plain, html_text = None, None
    images: list[str] = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            if part.get_content_type() == "application/pdf" and len(images) < MAX_PDF_ATTACHMENTS_PER_EMAIL * MAX_PDF_PAGES:
                payload = part.get_payload(decode=True)
                if payload:
                    images.extend(render_pdf_pages(payload))
            continue
        charset = part.get_content_charset() or "utf-8"
        if plain is None and part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                plain = payload.decode(charset, "replace")
        if html_text is None and part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                html_text = strip_html(payload.decode(charset, "replace"))
    return clean_body(plain or html_text or ""), images


def fetch_body(conn: imaplib.IMAP4_SSL, uid: str) -> dict:
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[])")
    if status != "OK" or not data or not isinstance(data[0], tuple):
        return {"body": "", "images": []}
    msg = email.message_from_bytes(data[0][1])
    body, images = extract_body_from_email(msg)
    return {"body": body, "images": images}


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------


def deepseek_client() -> OpenAI:
    return OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=DEEPSEEK_BASE_URL)


def classify_batch(client: OpenAI, items: list[dict]) -> set[str]:
    """Return the subset of message ids about the kid's school or activities."""
    numbered = "\n".join(f"{i}. Subject: {m['subject']!r} From: {m['from']!r}" for i, m in enumerate(items))
    prompt = (
        f"Emails below are numbered 0..{len(items) - 1}. Return the indices that are about "
        f"{KID_NAME}'s school (announcements, field trips, PD days, permission forms) or "
        f"{KID_NAME}'s afterschool/extracurricular activities (lessons, sports, camps, clubs). "
        "Ignore unrelated personal, work, or promotional email.\n\n"
        f"{numbered}\n\n"
        'Respond as JSON: {"relevant_indices": [0, 2, ...]}'
    )
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    indices = result.get("relevant_indices", [])
    return {items[i]["id"] for i in indices if 0 <= i < len(items)}


def _extraction_instructions(existing_events: list[dict]) -> str:
    existing_summary = [
        {"id": e["id"], "title": e["title"], "date": e["date"]} for e in existing_events if e["status"] == "active"
    ]
    return (
        f"You're extracting calendar events about {KID_NAME} from parent email for a family dashboard.\n"
        f"Known upcoming events already on record: {json.dumps(existing_summary)}\n\n"
        "For each event you find in the emails (and any attached images/scanned pages) below, decide:\n"
        "- action 'add' for a new event not already on record\n"
        "- action 'update' with match_id set to an existing event's id, if this email adds detail to "
        "  or corrects/reschedules something already known\n"
        "- action 'cancel' with match_id set, if this email says an existing event is cancelled/off\n"
        "Only extract events with a specific date. Ignore vague future mentions. If multiple emails "
        "describe the same event, merge them into one entry preferring the most recent details.\n\n"
    )


def _extraction_content(bodies: list[dict], existing_events: list[dict], include_images: bool) -> list[dict]:
    content = [{"type": "text", "text": _extraction_instructions(existing_events)}]
    for b in bodies:
        content.append({"type": "text", "text": f"--- Email (id={b['id']}, subject: {b['subject']!r}) ---\n{b['body']}"})
        if include_images:
            for img in b.get("images", []):
                content.append({"type": "image_url", "image_url": {"url": img}})
    content.append(
        {
            "type": "text",
            "text": (
                'Respond as JSON: {"events": [{"action": "add", "match_id": null, "title": "...", '
                '"date": "YYYY-MM-DD", "time": "HH:MM" or null, "category": "school" or "activity", '
                '"description": "..." or null, "links": ["..."]}]}'
            ),
        }
    )
    return content


def extract_events(client: OpenAI, bodies: list[dict], existing_events: list[dict]) -> list[dict]:
    """bodies: [{id, subject, body, images}]. Returns a list of {action, match_id, title, date,
    time, category, description, links} where action is 'add' | 'update' | 'cancel'.

    Attached PDF pages (rendered as images) are sent alongside the text on a best-effort
    basis -- if the model/request rejects the images for any reason, we fall back to a
    text-only call rather than losing the whole batch."""
    has_images = any(b.get("images") for b in bodies)
    try:
        content = _extraction_content(bodies, existing_events, include_images=has_images)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        if not has_images:
            raise
        print(f"Extraction with attachment images failed ({e}); retrying text-only.", file=sys.stderr)
        content = _extraction_content(bodies, existing_events, include_images=False)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
    result = json.loads(resp.choices[0].message.content)
    return result.get("events", [])


# ---------------------------------------------------------------------------
# State + merge
# ---------------------------------------------------------------------------


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"accounts": {}, "events": []}


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def merge_extracted(state: dict, extracted: list[dict], source_ids: list[str]):
    by_id = {e["id"]: e for e in state["events"]}
    for item in extracted:
        action = item.get("action", "add")
        match = by_id.get(item.get("match_id"))
        if action in ("update", "cancel") and match:
            match["sourceMessageIds"] = sorted(set(match["sourceMessageIds"]) | set(source_ids))
            if action == "cancel":
                match["status"] = "cancelled"
                continue
            match.update(
                {
                    "title": item["title"],
                    "date": item["date"],
                    "time": item.get("time"),
                    "category": item.get("category", match.get("category", "school")),
                    "description": item.get("description"),
                    "links": item.get("links", []),
                }
            )
        else:
            new_id = f"evt_{uuid.uuid4().hex[:8]}"
            event = {
                "id": new_id,
                "title": item["title"],
                "date": item["date"],
                "time": item.get("time"),
                "category": item.get("category", "school"),
                "description": item.get("description"),
                "links": item.get("links", []),
                "status": "active",
                "sourceMessageIds": list(source_ids),
            }
            state["events"].append(event)
            by_id[new_id] = event


def public_payload(state: dict) -> dict:
    today = date.today().isoformat()
    events = [
        {k: e[k] for k in ("title", "date", "time", "category", "description", "links")}
        for e in state["events"]
        if e["status"] == "active" and e["date"] >= today
    ]
    events.sort(key=lambda e: (e["date"], e["time"] or ""))
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "events": events}


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


def encrypt_payload(payload: dict, passphrase: str) -> dict:
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS).derive(
        passphrase.encode()
    )
    ciphertext = AESGCM(key).encrypt(iv, json.dumps(payload).encode(), None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "iterations": PBKDF2_ITERATIONS,
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def publish():
    rel = str(OUT.relative_to(REPO_ROOT))
    unchanged = subprocess.run(["git", "diff", "--quiet", "--", rel], cwd=REPO_ROOT).returncode == 0
    if unchanged:
        print("No change in son.enc.json; skipping commit.", file=sys.stderr)
        return
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME="kid-digest-bot",
        GIT_AUTHOR_EMAIL="kid-digest-bot@in4m.ca",
        GIT_COMMITTER_NAME="kid-digest-bot",
        GIT_COMMITTER_EMAIL="kid-digest-bot@in4m.ca",
    )
    subprocess.run(["git", "add", rel], cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "commit", "-m", "Refresh kid dashboard"], cwd=REPO_ROOT, check=True, env=env)
    subprocess.run(["git", "push", "origin", "main"], cwd=REPO_ROOT, check=True)
    print("Pushed updated son.enc.json.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(dry_run: bool):
    state = load_state()
    client = deepseek_client()
    now = datetime.now(timezone.utc)

    for account in ACCOUNTS:
        acct_state = state["accounts"].setdefault(account, {"last_checked": None, "processed_ids": []})
        since = (
            datetime.fromisoformat(acct_state["last_checked"])
            if acct_state["last_checked"]
            else now - timedelta(days=INITIAL_DAYS)
        )
        processed = set(acct_state["processed_ids"])

        conn = imap_connect(account)
        try:
            new_ids = list_new_uids(conn, since, processed)
            if not new_ids:
                if not dry_run:
                    acct_state["last_checked"] = now.isoformat(timespec="seconds")
                continue

            meta = [fetch_headers(conn, uid) for uid in new_ids]
            relevant_ids = set()
            for i in range(0, len(meta), CLASSIFY_BATCH):
                relevant_ids |= classify_batch(client, meta[i : i + CLASSIFY_BATCH])

            if relevant_ids:
                bodies = [
                    {"id": m["id"], "subject": m["subject"], **fetch_body(conn, m["id"])}
                    for m in meta
                    if m["id"] in relevant_ids
                ]
                extracted = extract_events(client, bodies, state["events"])
                if dry_run:
                    print(json.dumps({"account": account, "extracted": extracted}, indent=2))
                else:
                    merge_extracted(state, extracted, list(relevant_ids))

            if not dry_run:
                acct_state["processed_ids"] = list(processed | set(new_ids))
                acct_state["last_checked"] = now.isoformat(timespec="seconds")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    if dry_run:
        print(json.dumps(public_payload(state), indent=2))
        return

    save_state(state)
    encrypted = encrypt_payload(public_payload(state), os.environ["KID_DIGEST_PASSPHRASE"])
    OUT.write_text(json.dumps(encrypted, indent=2) + "\n")
    publish()


def main():
    dry_run = "--dry-run" in sys.argv
    try:
        run(dry_run)
    except Exception as e:
        print(f"kid-digest failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
