"""Try `spatialscape.show()` on your own objects, outside a notebook.

    python/.venv/bin/python examples/scripts/try_show.py                 # from a checkout of spatialscape
    SPATIAL_AMYGDALA=~/Documents/R/spatialAmygdala SN_H5AD=... python examples/scripts/try_show.py

Part 1 shows an snRNA-seq AnnData held in memory; draw a lasso in the browser, press Enter here, and the cells come
back as obs names: the subset and a quick in-versus-out gene ranking are printed. Part 2 shows a Visium
SpatialExperiment straight from its .rds (the first time reads and builds it, about three minutes for 2 GB; after
that it is instant). `--check` runs both without waiting for a lasso, to see that everything is in place.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import anndata as ad
import numpy as np
import spatialscape

AMY = Path(os.environ.get("SPATIAL_AMYGDALA", "~/Documents/R/spatialAmygdala")).expanduser()
SN_H5AD = Path(os.environ.get("SN_H5AD", "examples/amygdala-src/sce_amy_human.h5ad")).expanduser()
SPE_RDS = Path(os.environ.get("SPE_RDS", AMY / "Vitessce_app" / "spe_amy_shinyapp.rds")).expanduser()
CHECK = "--check" in sys.argv


def pause(msg: str) -> None:
    if not CHECK:
        input(msg)


def rank_in_vs_out(adata: ad.AnnData, cells, k: int = 12) -> None:
    """Mean log-expression inside the lasso minus outside, top genes: the kind of first look a selection invites."""
    mask = adata.obs_names.isin(cells)
    if mask.sum() == 0 or mask.sum() == adata.n_obs:
        return
    X = adata.X
    inside = np.asarray(X[mask].mean(axis=0)).ravel()
    outside = np.asarray(X[~mask].mean(axis=0)).ravel()
    diff = inside - outside
    top = np.argsort(diff)[::-1][:k]
    print("  genes up inside the lasso (mean log-expr in - out):")
    for i in top:
        print(f"    {adata.var_names[i]:<12} {diff[i]:+.2f}")


# ---------------------------------------------------------------- 1. an AnnData in memory
if SN_H5AD.exists():
    t = time.perf_counter()
    adata = ad.read_h5ad(SN_H5AD)
    print(f"read {SN_H5AD.name}: {adata.n_obs:,} cells x {adata.n_vars:,} genes in {time.perf_counter() - t:.1f} s")
    color = "fine_celltype" if "fine_celltype" in adata.obs else None
    coords = "obsm/X_umap_harmony" if "X_umap_harmony" in adata.obsm else None
    s = spatialscape.show(adata, color=color, coords=coords, open_browser=not CHECK)
    print(f"  {s.url}")
    pause("Draw a lasso in the browser (the lasso tool top left, or press l), then press Enter here... ")
    cells = s.selection()
    print(f"  {len(cells):,} cells in the selection")
    if len(cells):
        sub = adata[cells]
        print(f"  subset: {sub.shape}")
        if color:
            print("  composition:", sub.obs[color].value_counts().head(6).to_dict())
        rank_in_vs_out(adata, cells)
else:
    print(f"skipping part 1: {SN_H5AD} not found (set SN_H5AD=<path to an .h5ad>)")

# ---------------------------------------------------------------- 2. a SpatialExperiment from its .rds
if SPE_RDS.exists():
    t = time.perf_counter()
    s2 = spatialscape.show(SPE_RDS, open_browser=not CHECK)
    print(f"  {s2.url}  ({time.perf_counter() - t:.0f} s)")
    pause("Lasso some spots in a section (or several), then press Enter here... ")
    ids = s2.selection()
    print(f"  {len(ids):,} spots: {ids[:5]}{' ...' if len(ids) > 5 else ''}")
    print("  (for a file, the selection comes back as ids; match them to colnames(spe) in R)")
else:
    print(f"skipping part 2: {SPE_RDS} not found (set SPE_RDS=<path to a .rds>)")

if not CHECK:
    input("The viewers stay open while this script runs. Press Enter to stop. ")
