"""Registry (datasets.json) entries derived from bundles on disk.

The viewer's landing gallery reads `datasets.json` next to its `index.html`. `spatialscape serve` generates
one on the fly for every bundle in the served folder; `spatialscape site build` writes one from `site.yaml`
(or, for a plain folder of bundles, from their manifests alone).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .manifest import Manifest


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


def placeholder_entry(dataset_id: str, name: str, description: str | None = None, platforms: list[str] | None = None) -> dict[str, Any]:
    """A complete "coming soon" card: every key the gallery reads is present, so the viewer never sees a half entry."""
    return {
        "id": dataset_id,
        "name": name,
        "description": description or "",
        "platforms": list(platforms or []),
        "samples": 0,
        "cells": 0,
        "url": "",
        "status": "coming soon",
    }


def build_registry(bundles: list[Path], *, url_for: Any, title: str | None = None, intro: str | None = None) -> dict[str, Any]:
    """A datasets.json document from bundles alone. `url_for(bundle_dir, manifest_id) -> str` decides where each is served."""
    datasets = []
    for b in bundles:
        try:
            m_id = json.loads((b / "manifest.json").read_text()).get("id") or b.name
            datasets.append(bundle_entry(b, url_for(b, m_id)))
        except Exception as e:  # one stale or half-written bundle must not take the gallery down with it
            print(f"registry: skipping {b}: {str(e).splitlines()[0][:160]}", file=sys.stderr)
    doc: dict[str, Any] = {"title": title or "spatialscape"}
    if intro is not None:
        doc["intro"] = intro
    doc["datasets"] = datasets
    return doc


def packaged_app_dir() -> Path | None:
    """The viewer build shipped inside the package, or None for a source checkout without one."""
    d = Path(__file__).resolve().parent / "_app"
    return d if (d / "index.html").exists() else None
