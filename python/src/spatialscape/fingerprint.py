"""Per-sample build fingerprints: how `build` decides whether a sample folder is still current.

After building a sample, `build` writes `samples/<id>/build.json` holding a fingerprint of everything that
went into it: the resolved sample settings, the size and modification time of every input file, the
declarations of the fields it maps (type, vocabulary, category order, aliases), the shard settings and the
format and recipe versions. The next `build` recomputes the fingerprint from the yaml and the files and
rebuilds the sample only when it differs. Display names, group labels and palette colors are not part of it:
they live in the dataset-level files, which every `build` rewrites.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import DatasetConfig, MicronsSpec, SampleSpec
from .discover import auto_images
from .manifest import FORMAT_VERSION

IMAGE_RECIPE = 2  # bump when images are written differently; rebuilds only samples that have one (2: empty chunks written)

BUILD_RECIPE = 1  # bump when build_sample writes something different for the same inputs and settings
SIDECAR = "build.json"


def _remote_stat(url: str) -> dict:
    """Size and mtime of an `ssh://host/path` file, asked over ssh (read-only); the URL alone when that fails."""
    import subprocess

    from .tracks import split_ssh_url

    host, remote = split_ssh_url(url)
    cmd = f"stat -c '%s %Y' {_q(remote)} 2>/dev/null || stat -f '%z %m' {_q(remote)}"
    try:
        out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", host, cmd], capture_output=True, text=True, timeout=60)
        size, mtime = out.stdout.split()[:2]
        return {"size": int(size), "mtime_ns": int(mtime) * 1_000_000_000}
    except Exception:
        return {"remote": url}


def _q(s: str) -> str:
    import shlex

    return shlex.quote(s)


def _stat(path: Path | str) -> dict | None:
    """Size and mtime of a file, or a digest over the file list of a directory (Zarr stores, OME-Zarr images)."""
    if isinstance(path, str) and path.startswith("ssh://"):
        return _remote_stat(path)
    p = Path(path)
    if not p.exists():
        return None
    if p.is_file():
        st = p.stat()
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    h = hashlib.sha1()
    n = 0
    for root, dirs, files in os.walk(p):
        dirs.sort()
        for f in sorted(files):
            fp = Path(root) / f
            try:
                st = fp.stat()
            except OSError:
                continue
            h.update(f"{fp.relative_to(p)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
            n += 1
    return {"tree": h.hexdigest(), "files": n}


def resolve_auto_images(spec: SampleSpec) -> SampleSpec:
    """`images: auto` and the micron rule the files next to the sample imply (SpaceRanger scale factors), resolved
    the way build_sample does it. The scale is taken even when the images are listed or switched off (`images: []`),
    so dropping a section's image does not lose its scale."""
    auto = spec.images == "auto"
    if not auto and spec.microns != MicronsSpec():
        return spec
    imgs, microns = auto_images(spec if auto else spec.model_copy(update={"images": "auto"}))
    upd: dict = {"images": imgs} if auto else {}
    if microns is not None and spec.microns == MicronsSpec():
        upd["microns"] = microns
    return spec.model_copy(update=upd) if upd else spec


def sample_fingerprint(spec: SampleSpec, cfg: DatasetConfig, *, sharded: bool) -> dict:
    resolved = resolve_auto_images(spec)
    spec_json = resolved.model_dump(mode="json", exclude={"name", "group"})
    # a meta value typed in the yaml is applied to the manifest without a rebuild; one read from a column is fixed at build time
    spec_json["meta"] = {k: v for k, v in (spec_json.get("meta") or {}).items() if isinstance(v, dict)}
    paths: list[Path | None] = [resolved.path, resolved.microns.scalefactors_json]
    paths += [im.path for im in resolved.images]
    # a Xenium morphology_focus/ series reads every stain file through its first one: watch the folder
    paths += [im.path.parent for im in resolved.images if im.path is not None and im.path.parent.name == "morphology_focus"]
    if resolved.images:
        spec_json["image_recipe"] = IMAGE_RECIPE
    if resolved.kind == "spatial":  # polygons may be found in obsm at build time, so every spatial sample carries it
        from .shapes import SHAPES_RECIPE

        spec_json["shapes_recipe"] = SHAPES_RECIPE  # cell shapes are tiled since recipe 1
    if resolved.polygons is not None and resolved.polygons.path is not None:
        paths.append(resolved.polygons.path)
    if resolved.tracks is not None:
        from .tracks import TRACKS_RECIPE

        paths += resolved.tracks.input_files
        spec_json["tracks"]["recipe"] = TRACKS_RECIPE  # a changed track writer rebuilds only the samples that carry tracks
    inputs = {str(p): _stat(p) for p in paths if p is not None}
    fields = []
    for fid in resolved.fields if isinstance(resolved.fields, dict) else {}:
        f = cfg.field_spec(fid)
        if f is not None:
            fields.append({"id": f.id, "type": f.type, "vocabulary": f.vocabulary or f.id, "categories": f.categories, "aliases": f.aliases})
    fp = {
        "recipe": BUILD_RECIPE,
        "format": FORMAT_VERSION,
        "spec": spec_json,
        "inputs": inputs,
        "fields": fields,
        "shard_genes": cfg.shard_genes,
        "sharded": sharded,
    }
    return json.loads(json.dumps(fp, sort_keys=True, default=str))  # the same shape the sidecar comes back in


def why_stale(old: dict | None, new: dict) -> str | None:
    """None when the sample folder is current, else a short reason for rebuilding it."""
    if old is None:
        return "new"
    if old == new:
        return None
    if old.get("recipe") != new["recipe"] or old.get("format") != new["format"]:
        return "format changed"
    if old.get("inputs") != new["inputs"]:
        return "source changed"
    if old.get("sharded") != new["sharded"]:
        return "sharding changed"
    if old.get("shard_genes") != new["shard_genes"]:
        return "shard size changed"
    if old.get("spec") != new["spec"]:
        return "settings changed"
    if old.get("fields") != new["fields"]:
        return "field declarations changed"
    return "settings changed"


def read_sidecar(sample_dir: Path) -> dict | None:
    p = Path(sample_dir) / SIDECAR
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("fingerprint")
    except (OSError, ValueError, AttributeError):
        return None


def write_sidecar(sample_dir: Path, fingerprint: dict) -> Path:
    p = Path(sample_dir) / SIDECAR
    p.write_text(json.dumps({"fingerprint": fingerprint, "built": datetime.now(UTC).isoformat(timespec="seconds"), "spatialscape": __version__}, indent=1))
    return p
