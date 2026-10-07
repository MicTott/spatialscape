"""Thumbnails: one spatial section colored by a categorical field, rendered from the bundle's own arrays."""
from __future__ import annotations

import json
from pathlib import Path

import zarr
from PIL import Image, ImageDraw

from .manifest import Manifest

BG = (17, 21, 27)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def pick_field(m: Manifest, sample) -> str | None:
    """Default color field if categorical and present on the sample, else the first categorical field it carries."""
    cats = [f.id for f in m.fields if f.type == "categorical"]
    if m.defaultColor.kind == "field" and m.defaultColor.field in cats and m.defaultColor.field in sample.fields:
        return m.defaultColor.field
    for fid in cats:
        if fid in sample.fields:
            return fid
    return None


def render_sample(root: Path, m: Manifest, sample, *, width: int = 512, height: int = 512, max_points: int = 80_000, pad: int = 16) -> Image.Image:
    d = root / "samples" / sample.id
    og = zarr.open_group(str(d / "obs.zarr"), mode="r")
    xy = og["xy"][:]
    n = len(xy)
    step = max(1, n // max_points)
    xy = xy[::step]
    fid = pick_field(m, sample)
    if fid:
        f = m.field_by_id(fid)
        codes = og["cat"][fid][::step]
        colors = [_hex(c) for c in m.vocabularies[f.vocabulary].colors]
        na = m.vocabularies[f.vocabulary].categories.index("NA") if "NA" in m.vocabularies[f.vocabulary].categories else -1
    else:
        codes = None
        colors = [(200, 200, 200)]
        na = -1
    x0, y0 = xy.min(axis=0)
    x1, y1 = xy.max(axis=0)
    sw, sh = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    scale = min((width - 2 * pad) / sw, (height - 2 * pad) / sh)
    ox = (width - sw * scale) / 2
    oy = (height - sh * scale) / 2
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    r = max(0.6, min(3.0, 0.45 * sample.pointRadius * scale)) if sample.kind == "spatial" else 1.2
    px = (xy[:, 0] - x0) * scale + ox
    py = (xy[:, 1] - y0) * scale + oy
    for i in range(len(xy)):
        c = colors[codes[i]] if codes is not None and codes[i] < len(colors) else (120, 120, 120)
        if codes is not None and codes[i] == na:
            c = (70, 74, 80)
        draw.ellipse([px[i] - r, py[i] - r, px[i] + r, py[i] + r], fill=c)
    return img


def write_thumbnails(root: Path, *, per_sample: bool = True, hero_id: str | None = None, log=lambda *_: None) -> list[Path]:
    root = Path(root)
    m = Manifest.model_validate_json((root / "manifest.json").read_text())
    out: list[Path] = []
    spatial = [s for s in m.samples if s.kind == "spatial"] or m.samples
    if not spatial:
        return out
    hero = next((s for s in m.samples if s.id == hero_id), None) if hero_id else None
    if hero_id and hero is None:
        raise KeyError(f"thumbnail sample {hero_id!r} not in bundle")
    hero = hero or next((s for s in spatial if s.id == (m.layout.order[0] if m.layout.order else None)), spatial[0])
    img = render_sample(root, m, hero)
    p = root / "thumbnail.png"
    img.save(p, optimize=True)
    out.append(p)
    log(f"thumbnail: {hero.id} -> {p.name}")
    if per_sample:
        for s in m.samples:
            img = render_sample(root, m, s, width=256, height=256, max_points=20_000, pad=8)
            sp = root / "samples" / s.id / "thumbnail.png"
            img.save(sp, optimize=True)
            out.append(sp)
    meta = {"hero": hero.id, "field": pick_field(m, hero)}
    (root / "thumbnail.json").write_text(json.dumps(meta))
    return out
