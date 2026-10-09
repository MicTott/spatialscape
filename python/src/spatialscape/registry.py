"""Registry (datasets.json) entries derived from bundles on disk.

The viewer's landing gallery reads `datasets.json` next to its `index.html`. `spatialscape serve`
generates one on the fly for every bundle in the served folder; `spatialscape site build` writes one
into a deployable site. Hand-edited keys (paper, tags, accent, status, a custom url) survive regeneration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import Manifest

GENERATED_KEYS = ("name", "description", "platforms", "samples", "cells", "genes")


def find_bundles(root: Path) -> list[Path]:
    """Bundle directories directly under `root` (those holding a manifest.json), plus `root` itself if it is one."""
    root = Path(root)
    if (root / "manifest.json").exists():
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def bundle_entry(bundle: Path, url: str) -> dict[str, Any]:
    """Registry entry for one bundle, read from its manifest and gene list."""
    m = Manifest.model_validate_json((bundle / "manifest.json").read_text())
    genes_path = bundle / "genes.json"
    n_genes = len(json.loads(genes_path.read_text())) if genes_path.exists() else None
    platforms: list[str] = []
    for s in m.samples:
        p = "snrnaseq" if s.kind == "embedding" else s.platform
        if p not in platforms:
            platforms.append(p)
    entry: dict[str, Any] = {
        "id": m.id,
        "name": m.name,
        "description": m.description or "",
        "platforms": platforms,
        "samples": len(m.samples),
        "cells": sum(s.nObs for s in m.samples),
        "url": url,
        "status": "live",
    }
    if n_genes is not None:
        entry["genes"] = n_genes
    return entry


def merge_entry(generated: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """Generated facts win; everything else a person added to the existing entry is kept."""
    if not existing:
        return generated
    out = dict(existing)
    out.update({k: v for k, v in generated.items() if k in GENERATED_KEYS or k == "id"})
    out.setdefault("url", generated["url"])
    out.setdefault("status", generated["status"])
    return out


def build_registry(
    bundles: list[Path],
    *,
    url_for: Any,
    existing: dict[str, Any] | None = None,
    title: str | None = None,
    intro: str | None = None,
) -> dict[str, Any]:
    """A datasets.json document. `url_for(bundle_dir, manifest_id) -> str` decides where each bundle is served."""
    existing = existing or {}
    by_id = {d.get("id"): d for d in existing.get("datasets", []) if isinstance(d, dict)}
    datasets = []
    seen = set()
    for b in bundles:
        m_id = json.loads((b / "manifest.json").read_text()).get("id") or b.name
        entry = bundle_entry(b, url_for(b, m_id))
        datasets.append(merge_entry(entry, by_id.get(entry["id"])))
        seen.add(entry["id"])
    # keep hand-written entries that are not built here (e.g. "coming soon" placeholders or remote bundles)
    datasets += [d for i, d in by_id.items() if i not in seen]
    doc: dict[str, Any] = {k: v for k, v in existing.items() if k not in ("datasets",)}
    if title is not None:
        doc["title"] = title
    if intro is not None:
        doc["intro"] = intro
    doc.setdefault("title", "spatialscape")
    doc["datasets"] = datasets
    return doc


def packaged_app_dir() -> Path | None:
    """The viewer build shipped inside the package, or None for a source checkout without one."""
    d = Path(__file__).resolve().parent / "_app"
    return d if (d / "index.html").exists() else None
