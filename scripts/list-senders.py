"""One-off utility: list unique sender domains from an account's inbox over the
last N days, with a count and an example subject line each -- to help populate
kid-digest-known-senders.txt. Not part of the scheduled pipeline, never run
automatically. Reuses the same GMAIL_<LABEL>_EMAIL/APP_PASSWORD env vars as
kid-digest.py, so it can run with the same kid-digest.env file.

Usage:
    uv run scripts/list-senders.py --account wife --days 60
"""

import argparse
import email
import imaplib
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.header import decode_header


def decode_mime_header(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p for p, enc in parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", required=True, help="Account label matching GMAIL_<LABEL>_EMAIL, e.g. wife")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()

    prefix = f"GMAIL_{args.account.upper()}"
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(os.environ[f"{prefix}_EMAIL"], os.environ[f"{prefix}_APP_PASSWORD"])
    conn.select("INBOX")

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%d-%b-%Y")
    status, data = conn.uid("search", None, f'(SINCE "{since}")')
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    uids = data[0].split() if data and data[0] else []

    counts = Counter()
    examples = {}
    for uid in uids:
        status, d = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        if status != "OK" or not d or not isinstance(d[0], tuple):
            continue
        msg = email.message_from_bytes(d[0][1])
        frm = decode_mime_header(msg.get("From", ""))
        subj = decode_mime_header(msg.get("Subject", ""))
        domain = frm.split("@")[-1].strip("> ").lower() if "@" in frm else frm.lower()
        counts[domain] += 1
        examples.setdefault(domain, subj)

    conn.logout()
    print(f"{len(uids)} messages scanned, {len(counts)} unique sender domains:\n")
    for domain, n in counts.most_common():
        print(f"{n:4d}  {domain:40s}  e.g. {examples[domain]!r}")


if __name__ == "__main__":
    main()
