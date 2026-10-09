"""Validate a bundle on disk or over HTTP (schema, shapes, codes, range requests)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np

from .manifest import Manifest


def _problem(problems: list[str], msg: str) -> None:
    problems.append(msg)


def validate_local(root: Path) -> list[str]:
    import zarr

    p: list[str] = []
    root = Path(root)
    mpath = root / "manifest.json"
    if not mpath.exists():
        return [f"missing {mpath}"]
    try:
        m = Manifest.model_validate_json(mpath.read_text())
    except Exception as e:
        return [f"manifest.json invalid: {e}"]
    genes_union = json.loads((root / "genes.json").read_text()) if (root / "genes.json").exists() else None
    if genes_union is None:
        _problem(p, "missing genes.json")
    if m.defaultGene and genes_union is not None and m.defaultGene not in set(genes_union):
        _problem(p, f"defaultGene {m.defaultGene!r} not in genes.json")
    fpath = root / "features.json"
    if fpath.exists():
        try:
            feats = json.loads(fpath.read_text())
            assert isinstance(feats.get("genes"), list) and isinstance(feats.get("groups"), list)
            for g in feats["groups"]:
                assert all({"id", "label"} <= set(f) for f in g["features"])
        except Exception as e:
            _problem(p, f"features.json malformed: {e}")
    field_ids = {f.id for f in m.fields}
    for f in m.fields:
        if f.type == "categorical" and f.vocabulary not in m.vocabularies:
            _problem(p, f"field {f.id}: vocabulary {f.vocabulary!r} missing")
    for v_id, v in m.vocabularies.items():
        if len(v.categories) != len(v.colors):
            _problem(p, f"vocabulary {v_id}: categories/colors length mismatch")
    for sid in m.layout.order:
        if sid not in {s.id for s in m.samples}:
            _problem(p, f"layout.order references unknown sample {sid!r}")
    for s in m.samples:
        d = root / "samples" / s.id
        if not d.is_dir():
            _problem(p, f"{s.id}: missing sample directory")
            continue
        try:
            g = zarr.open_group(str(d / "expr.zarr"), mode="r")
            u8 = g["u8"]
            if tuple(u8.shape) != (s.nGenes, s.nObs):
                _problem(p, f"{s.id}: expr u8 shape {u8.shape} != ({s.nGenes}, {s.nObs})")
            if u8.chunks[0] != 1:
                _problem(p, f"{s.id}: expr u8 chunk shape {u8.chunks} is not gene-major (1, n_obs)")
            if g["gmax"].shape[0] != s.nGenes:
                _problem(p, f"{s.id}: gmax length mismatch")
            if s.nGenes:
                _ = u8[0, :]  # exercise one chunk read (and the shard index)
        except Exception as e:
            _problem(p, f"{s.id}: expr.zarr unreadable: {e}")
        genes = json.loads((d / "genes.json").read_text()) if (d / "genes.json").exists() else None
        if genes is None or len(genes) != s.nGenes:
            _problem(p, f"{s.id}: genes.json missing or length != nGenes")
        try:
            og = zarr.open_group(str(d / "obs.zarr"), mode="r")
            if tuple(og["xy"].shape) != (s.nObs, 2):
                _problem(p, f"{s.id}: obs xy shape {og['xy'].shape}")
            if tuple(og["order"].shape) != (s.nObs,):
                _problem(p, f"{s.id}: obs order shape")
            for fid in s.fields:
                if fid not in field_ids:
                    _problem(p, f"{s.id}: field {fid!r} not declared in manifest.fields")
                    continue
                f = m.field_by_id(fid)
                if f.type == "categorical":
                    if fid not in og["cat"]:
                        _problem(p, f"{s.id}: obs.zarr/cat/{fid} missing")
                        continue
                    codes = og["cat"][fid][:]
                    ncat = len(m.vocabularies[f.vocabulary].categories)
                    if codes.size and int(codes.max()) >= ncat:
                        _problem(p, f"{s.id}: field {fid} has code {int(codes.max())} >= {ncat} categories")
                else:
                    if fid not in og["num"]:
                        _problem(p, f"{s.id}: obs.zarr/num/{fid} missing")
        except Exception as e:
            _problem(p, f"{s.id}: obs.zarr unreadable: {e}")
        nblocks = -(-s.nObs // s.idBlock)
        for b in range(nblocks):
            if not (d / "ids" / f"{b}.json").exists():
                _problem(p, f"{s.id}: ids/{b}.json missing")
                break
        if s.polygons:
            off = d / "polygons.offsets.u32"
            dl = d / "polygons.i16"
            if not off.exists() or not dl.exists():
                _problem(p, f"{s.id}: polygon files missing")
            elif off.stat().st_size != 4 * (s.nObs + 1) or dl.stat().st_size != 4 * s.polygons.vertices:
                _problem(p, f"{s.id}: polygon file sizes do not match nObs/vertices")
        for im in s.images:
            try:
                ig = zarr.open_group(str(d / im.path), mode="r")
                lv0 = ig[ig.attrs["multiscales"][0]["datasets"][0]["path"]]
                if tuple(lv0.shape[1:]) != tuple(im.size):
                    _problem(p, f"{s.id}: image {im.id} size {lv0.shape[1:]} != {im.size}")
            except Exception as e:
                _problem(p, f"{s.id}: image {im.id} unreadable: {e}")
        if not np.isfinite(s.bbox).all():
            _problem(p, f"{s.id}: bbox not finite")
    return p


ORIGIN = "https://viewer.example.org"  # any browser origin; servers that gate CORS on it answer as they would for the viewer


def validate_remote(url: str) -> list[str]:
    p: list[str] = []
    url = url.rstrip("/")
    try:
        req = urllib.request.Request(url + "/manifest.json", headers={"Origin": ORIGIN})
        with urllib.request.urlopen(req, timeout=20) as r:
            m = Manifest.model_validate_json(r.read())
            if not r.headers.get("Access-Control-Allow-Origin"):
                _problem(p, "manifest.json: no Access-Control-Allow-Origin header; the browser will refuse to load the bundle (configure CORS on the host)")
    except Exception as e:
        return [f"cannot fetch manifest: {e}"]
    if not m.samples:
        return p + ["manifest has no samples"]
    s = m.samples[0]
    sharded = s.expr.sharded
    chunk = f"{url}/samples/{s.id}/expr.zarr/u8/c/0/0"
    headers = {"Origin": ORIGIN}
    if sharded:
        headers["Range"] = "bytes=0-15"
    req = urllib.request.Request(chunk, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if sharded:
                if r.status != 206:
                    _problem(p, f"range request returned {r.status}, expected 206: this bundle is sharded, so the host must support HTTP Range (or rebuild with --no-shard)")
                exp = r.headers.get("Access-Control-Expose-Headers", "")
                if "content-range" not in exp.lower() and "*" not in exp:
                    _problem(p, "Access-Control-Expose-Headers should include Content-Range for sharded bundles")
            elif r.status != 200:
                _problem(p, f"gene chunk request returned {r.status}")
    except Exception as e:
        _problem(p, f"gene chunk request failed for {chunk}: {e}")
    return p


def validate(target: str) -> list[str]:
    if target.startswith(("http://", "https://")):
        return validate_remote(target)
    return validate_local(Path(target))
