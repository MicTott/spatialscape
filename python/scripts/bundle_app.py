"""Copy the built viewer (app/dist) into the Python package so the wheel ships it.

    npm run build && python python/scripts/bundle_app.py

Only index.html and assets/ are copied: no source maps, no registry, no site drafts. The copy lives at
src/spatialscape/_app (gitignored) and is picked up by `spatialscape serve` and `spatialscape site build`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "app" / "dist"
DEST = ROOT / "python" / "src" / "spatialscape" / "_app"


def main() -> None:
    if not (DIST / "index.html").exists():
        sys.exit(f"{DIST} has no build; run `npm run build` first")
    if DEST.exists():
        shutil.rmtree(DEST)
    (DEST / "assets").mkdir(parents=True)
    shutil.copy2(DIST / "index.html", DEST / "index.html")
    n = 0
    for f in (DIST / "assets").iterdir():
        if f.suffix == ".map":
            continue
        shutil.copy2(f, DEST / "assets" / f.name)
        n += 1
    size = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    print(f"packaged viewer: index.html + {n} assets, {size / 1e6:.1f} MB -> {DEST}")


if __name__ == "__main__":
    main()
