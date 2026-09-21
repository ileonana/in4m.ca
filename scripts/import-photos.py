#!/usr/bin/env python3
"""Convert photos from a source folder into src/assets/photos.

Usage:
    uv run scripts/import-photos.py [SOURCE_DIR] [--prune] [--size 2500]

Reads JPG/PNG/HEIC/DNG, applies EXIF rotation, resizes to --size on the long edge and
writes `YYYY-MM-DD_<original-name>.jpg`, so the gallery (sorted by filename) runs in date
order. Photos that were already converted are skipped; --prune removes outputs whose
source is no longer in SOURCE_DIR.

One-time setup:
    uv sync
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

try:
    import pillow_heif
    import rawpy
    from PIL import Image, ImageOps
except ImportError:
    sys.exit(
        "Missing packages. Run:\n"
        "  uv sync"
    )

DEFAULT_SOURCE = "/run/user/1000/gvfs/smb-share:server=100.98.230.125,share=photo/website"
DEST = Path(__file__).resolve().parent.parent / "src" / "assets" / "photos"
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".dng"}

pillow_heif.register_heif_opener()
Image.MAX_IMAGE_PIXELS = None


def capture_date(path: Path) -> str:
    """EXIF capture date, falling back to the file's modified time."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
        if raw:
            return dt.datetime.strptime(str(raw)[:10], "%Y:%m:%d").strftime("%Y-%m-%d")
    except Exception:
        pass
    return dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def slug(stem: str) -> str:
    return re.sub(r"\s+", "-", stem.strip())


def output_suffix(path: Path, taken: dict) -> str:
    """`<stem>` normally; `<stem>-<ext>` if another source file shares the stem."""
    base = slug(path.stem)
    other = taken.get(base)
    if other is not None and other != path:
        return f"{base}-{path.suffix.lower().lstrip('.')}"
    taken[base] = path
    return base


def convert(path: Path, out: Path, size: int) -> None:
    if path.suffix.lower() == ".dng":
        with rawpy.imread(str(path)) as raw:
            im = Image.fromarray(raw.postprocess(use_camera_wb=True))
    else:
        im = ImageOps.exif_transpose(Image.open(path))
    im = im.convert("RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    im.save(out, quality=85, optimize=True, progressive=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("source", nargs="?", default=DEFAULT_SOURCE)
    ap.add_argument("--size", type=int, default=2500)
    ap.add_argument("--prune", action="store_true", help="delete outputs whose source is gone")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_dir():
        sys.exit(f"Source folder not found: {src}")
    DEST.mkdir(parents=True, exist_ok=True)

    sources = sorted(p for p in src.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    taken: dict = {}
    wanted = {}  # suffix -> source path
    for p in sources:
        wanted[output_suffix(p, taken)] = p

    existing = {f: f.stem.split("_", 1)[-1] for f in DEST.glob("*.jpg")}
    done = set(existing.values())

    added = 0
    for suffix, p in wanted.items():
        if suffix in done:
            continue
        out = DEST / f"{capture_date(p)}_{suffix}.jpg"
        try:
            convert(p, out, args.size)
            added += 1
            print(f"added   {out.name}")
        except Exception as e:
            print(f"FAILED  {p.name}: {e}", file=sys.stderr)

    removed = 0
    stale = [f for f, s in existing.items() if s not in wanted]
    if args.prune:
        for f in stale:
            f.unlink()
            removed += 1
            print(f"removed {f.name}")
    elif stale:
        print(f"{len(stale)} photo(s) no longer in the source; use --prune to remove them.")

    print(f"Done: {added} added, {removed} removed, {len(done)} already present.")


if __name__ == "__main__":
    main()
