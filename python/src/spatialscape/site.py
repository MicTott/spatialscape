"""Assemble a deployable static site: the packaged viewer, a registry and (copies of) the bundles."""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from .registry import build_registry, find_bundles, packaged_app_dir

Log = Callable[[str], None]


def copy_app(app_dir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_dir / "index.html", out / "index.html")
    assets_out = out / "assets"
    if assets_out.exists():
        shutil.rmtree(assets_out)
    shutil.copytree(app_dir / "assets", assets_out)


def build_site(
    out: Path,
    bundles: list[Path],
    *,
    data_url: str | None = None,
    link: bool = False,
    title: str | None = None,
    intro: str | None = None,
    app_dir: Path | None = None,
    log: Log = print,
) -> Path:
    """Write `out/` with index.html, assets/, datasets.json and one folder per bundle.

    `data_url`: bundles are already hosted at `<data_url>/<id>`; nothing is copied.
    `link`: symlink bundle folders instead of copying (local previews of large data).
    An existing `out/datasets.json` is merged, so titles, paper links, tags and placeholder entries survive.
    """
    out = Path(out)
    app_dir = app_dir or packaged_app_dir()
    if app_dir is None:
        raise FileNotFoundError(
            "this install has no packaged viewer. Install spatialscape from PyPI, or in a source checkout run "
            "`npm run build` then `python python/scripts/bundle_app.py`"
        )
    copy_app(app_dir, out)
    log(f"viewer -> {out}")
    expanded: list[Path] = []
    for b in bundles:
        found = find_bundles(Path(b))
        if not found:
            raise FileNotFoundError(f"{b}: no bundle here (no manifest.json in it or directly under it)")
        expanded += found
    ids: dict[Path, str] = {}
    for b in expanded:
        ids[b] = json.loads((b / "manifest.json").read_text()).get("id") or b.name
    if data_url is None:
        for b, bid in ids.items():
            dest = out / bid
            if dest.resolve() == b.resolve():
                continue
            if dest.is_symlink() or dest.exists():
                if dest.is_symlink() or dest.is_file():
                    dest.unlink()
                else:
                    shutil.rmtree(dest)
            if link:
                os.symlink(b.resolve(), dest, target_is_directory=True)
            else:
                shutil.copytree(b, dest)
            log(f"{'linked' if link else 'copied'} {b} -> {dest}")
    existing = None
    reg_path = out / "datasets.json"
    if reg_path.exists():
        existing = json.loads(reg_path.read_text())
    doc = build_registry(
        expanded,
        url_for=(lambda b, bid: f"{data_url.rstrip('/')}/{bid}") if data_url else (lambda b, bid: bid),
        existing=existing,
        title=title,
        intro=intro,
    )
    reg_path.write_text(json.dumps(doc, indent=2) + "\n")
    log(f"registry -> {reg_path} ({len(doc['datasets'])} dataset(s))")
    return out
