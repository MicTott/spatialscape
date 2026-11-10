"""Bytes per store of a built bundle, for the build table in docs/reference/benchmarks.md.

    python benchmarks/bundle_size.py examples/amygdala [--json out.json]

Walks <bundle>/samples/<id>/ and sums file sizes by store: expression (expr.zarr), rows (rows.zarr), cells
(obs.zarr, ids, genes.json, build.json, zero_genes.json, thumbnail), images (*.ome.zarr), shapes (shapes.bin,
shapes.json, segmentations, outlines), molecules (molecules.bin, molecules.json), tracks (tracks/), and anything
else. Then the ratios the protocol asks for: bytes per cell for expression and rows, bytes per transcript, from the
manifest's nObs and the molecule index's count. Sizes are byte counts (st_size), not blocks on disk.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

STORES = ("expression", "rows", "cells", "images", "shapes", "molecules", "tracks", "other")


def classify(rel: str) -> str:
    top = rel.split("/", 1)[0]
    if top == "expr.zarr":
        return "expression"
    if top == "rows.zarr":
        return "rows"
    if top.endswith(".ome.zarr"):
        return "images"
    if top in ("shapes.bin", "shapes.json", "segmentations", "outlines"):
        return "shapes"
    if top in ("molecules.bin", "molecules.json"):
        return "molecules"
    if top == "tracks":
        return "tracks"
    if top in ("obs.zarr", "ids", "genes.json", "build.json", "zero_genes.json", "thumbnail.png"):
        return "cells"
    return "other"


def tree_bytes(root: Path) -> dict[str, int]:
    out = dict.fromkeys(STORES, 0)
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            rel = str(p.relative_to(root))
            out[classify(rel)] += p.stat().st_size
    return out


def measure(bundle: Path) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text())
    samples = []
    totals = dict.fromkeys(STORES, 0)
    n_obs = 0
    n_mol = 0
    for s in manifest["samples"]:
        d = bundle / "samples" / s["id"]
        if not d.is_dir():
            continue
        sizes = tree_bytes(d)
        mol = d / "molecules.json"
        count = json.loads(mol.read_text()).get("count", 0) if mol.exists() else 0
        samples.append({"id": s["id"], "platform": s.get("platform"), "nObs": s.get("nObs", 0), "nGenes": s.get("nGenes", 0), "molecules": count, **sizes})
        for k in STORES:
            totals[k] += sizes[k]
        n_obs += s.get("nObs", 0)
        n_mol += count
    top = sum(p.stat().st_size for p in bundle.iterdir() if p.is_file())
    totals["dataset_files"] = top
    total = sum(totals.values())
    return {
        "bundle": str(bundle),
        "id": manifest.get("id"),
        "samples": len(samples),
        "nObs": n_obs,
        "molecules": n_mol,
        "bytes": totals,
        "total_bytes": total,
        "bytes_per_cell": {"expression": totals["expression"] / n_obs if n_obs else None, "rows": totals["rows"] / n_obs if n_obs else None},
        "bytes_per_molecule": totals["molecules"] / n_mol if n_mol else None,
        "per_sample": samples,
    }


def gb(n: int) -> str:
    return f"{n / 1e9:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--json", type=Path, help="also write the full report here")
    a = ap.parse_args()
    r = measure(a.bundle)
    b = r["bytes"]
    print(f"{r['id']}: {r['samples']} samples, {r['nObs']:,} cells, {r['molecules']:,} molecules, {gb(r['total_bytes'])} GB")
    print("| store | GB | share |")
    print("|---|---|---|")
    for k in STORES + ("dataset_files",):
        if b[k]:
            print(f"| {k} | {gb(b[k])} | {100 * b[k] / r['total_bytes']:.1f}% |")
    bpc = r["bytes_per_cell"]
    if bpc["expression"]:
        print(f"expression {bpc['expression']:.0f} B/cell, rows {bpc['rows']:.0f} B/cell" + (f", molecules {r['bytes_per_molecule']:.2f} B/transcript" if r["bytes_per_molecule"] else ""))
    if a.json:
        a.json.write_text(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
