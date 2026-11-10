"""Render the benchmark tables for docs/reference/benchmarks.md from benchmarks/results/*.json.

    python benchmarks/tables.py            # prints the markdown tables
    python benchmarks/tables.py --write    # also replaces the tables between the markers in docs/reference/benchmarks.md

Build rows come from build-*.json (build_bench.sh on the laptop, build-jhpce-*.json from the cluster's job accounting
and bundle_size.py); viewer rows from viewer-*.json (viewer_bench.mjs). Nothing here is typed in by hand.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks" / "results"
DOC = ROOT / "docs" / "reference" / "benchmarks.md"

ORDER = ["synthetic", "visium-cytassist-mouse-brain", "visium-human-dlpfc", "dacc", "bla", "habenula_multiome", "amygdala",
         "spatial-atac-rna-mouse-brain", "visium-hd-mouse-brain", "xenium-mouse-brain", "merscope-mouse-brain", "cosmx-nsclc", "atera", "abc-atlas"]
LABEL = {
    "synthetic": "synthetic (3 sections)", "visium-cytassist-mouse-brain": "Visium CytAssist, mouse brain", "visium-human-dlpfc": "Visium, human DLPFC (12 sections)",
    "dacc": "dACC: Visium + snRNA-seq (18 samples)", "bla": "BLA cross-species snRNA-seq (9 embeddings)", "habenula_multiome": "habenula multiome: Visium HD, Visium, snMultiome + tracks",
    "amygdala": "amygdala atlas: Xenium, Visium, Visium HD, 2 references (18 samples)", "spatial-atac-rna-mouse-brain": "spatial ATAC + RNA, mouse brain (3 sections, tracks)",
    "visium-hd-mouse-brain": "Visium HD 8 µm, mouse brain", "xenium-mouse-brain": "Xenium Prime 5K, mouse brain", "merscope-mouse-brain": "MERSCOPE, mouse brain (3 slices)",
    "cosmx-nsclc": "CosMx, NSCLC (8 sections)", "atera": "Atera, whole transcriptome in situ (2 sections)", "abc-atlas": "Allen Brain Cell Atlas (59 MERFISH + whole-brain nuclei)",
}


def order_key(name: str) -> tuple[int, str]:
    return (ORDER.index(name) if name in ORDER else len(ORDER), name)


def fmt_s(s: float | None) -> str:
    if s is None:
        return ""
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


def gb(b: float | None, digits: int = 2) -> str:
    return "" if b is None else f"{b / 1e9:.{digits}f}"


def mb(b: float | None) -> str:
    return "" if b is None else f"{b / 1e6:.1f}"


def n(x: float | None) -> str:
    return "" if x is None else f"{x:,.0f}"


def build_table() -> str:
    rows = []
    for p in sorted(RESULTS.glob("build-*.json")):
        if p.name.endswith(".log"):
            continue
        r = json.loads(p.read_text())
        rows.append((order_key(r["name"]), "jhpce" in p.name, r))
    rows.sort(key=lambda t: (t[0], t[1]))
    out = ["| Dataset | Where | Cells | Wall | CPU | Peak RSS | Bundle (GB) | expression | rows | images | shapes | molecules | tracks | B/cell expr | B/cell rows | B/transcript |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _k, jhpce, r in rows:
        b = r["bytes"]
        where = f"JHPCE, {r['machine']['request']}" if jhpce else "laptop"
        bpc = r["bytes_per_cell"]
        bpm = f"{r['bytes_per_molecule']:.2f}" if r["bytes_per_molecule"] else ""
        out.append(
            f"| {LABEL.get(r['name'], r['name'])} | {where} | {n(r['nObs'])} | {fmt_s(r['wall_s'])} | {fmt_s(r['user_s'])} | {gb(r['max_rss_bytes'], 1)} GB{'*' if r['name'] == 'abc-atlas' and jhpce else ''} | {gb(r['bundle_bytes'])} "
            f"| {gb(b['expression'])} | {gb(b['rows'])} | {gb(b['images'])} | {gb(b['shapes'])} | {gb(b['molecules'])} | {gb(b['tracks'])} "
            f"| {n(bpc['expression'])} | {n(bpc['rows'])} | {bpm} |"
        )
    return "\n".join(out)


def viewer_tables() -> str:
    rows = []
    for p in sorted(RESULTS.glob("viewer-*.json")):
        r = json.loads(p.read_text())
        rows.append((order_key(r["name"]), r))
    rows.sort(key=lambda t: t[0])
    load = ["| Dataset | Cells | Ready | First frame with cells | Fetched | Requests | Gene switch, cold: data / frame | requests / bytes per cold switch | cached: data / frame |",
            "|---|---|---|---|---|---|---|---|---|"]
    states = ["| Dataset | State | Dots drawn | Polygons | Molecules | Fetched to reach it | Requests | Pan frame time, median / p95 | Frames over 16.7 ms | JS heap |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _k, r in rows:
        g = r["geneSwitch"]
        cl = r["coldLoad"]
        load.append(
            f"| {LABEL.get(r['name'], r['name'])} | {n(r['dataset']['cells'])} | {cl['readyMs']:.0f} ms | {cl['firstFrameWithCellsMs']} ms | {mb(cl['bytes'])} MB | {cl['requests']} "
            f"| {g['cold']['dataReadyMs']['median']:.0f} / {g['cold']['firstFrameMs']['median']:.0f} ms (p95 {g['cold']['dataReadyMs']['p95']:.0f}) | {g['cold']['requestsPerSwitch']:.1f} / {mb(g['cold']['bytesPerSwitch'])} MB "
            f"| {g['cached']['dataReadyMs']['median']:.0f} / {g['cached']['firstFrameMs']['median']:.0f} ms |"
        )
        names = {"overview": "overview", "section": "one section", "window1mm": "1 mm window", "windowMolecules": "window with molecules"}
        for key, s in r["states"].items():
            label = names.get(key, key) + (f" ({s['windowMm']} mm)" if key == "windowMolecules" else "")
            d = s["drawn"]
            states.append(
                f"| {LABEL.get(r['name'], r['name'])} | {label} | {n(d['points'])} | {n(d['shapes'])} | {n(d['molecules'])} | {mb(s['reached']['bytes'])} MB | {s['reached']['requests']} "
                f"| {s['pan']['median']:.1f} / {s['pan']['p95']:.1f} ms | {100 * s['pan']['over16_7ms']:.0f}% | {mb(s['heapBytes'])} MB |"
            )
    return "\n".join(load) + "\n\n" + "\n".join(states)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    build = build_table()
    viewer = viewer_tables()
    if a.write:
        text = DOC.read_text()
        text = re.sub(r"(<!-- build-table -->\n).*?(\n<!-- /build-table -->)", lambda m: m.group(1) + build + m.group(2), text, flags=re.S)
        text = re.sub(r"(<!-- viewer-tables -->\n).*?(\n<!-- /viewer-tables -->)", lambda m: m.group(1) + viewer + m.group(2), text, flags=re.S)
        DOC.write_text(text)
        print(f"wrote {DOC}")
    else:
        print(build)
        print()
        print(viewer)


if __name__ == "__main__":
    main()
