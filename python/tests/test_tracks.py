"""Genome tracks from a fragment file: one bigWig per category, insertions per million."""
from __future__ import annotations

import numpy as np
import pytest
import yaml

from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic
from spatialscape.tracks import write_fragments

pyBigWig = pytest.importorskip("pyBigWig")


def test_tracks_per_category_and_all(tmp_path):
    import anndata as ad

    cfg_path = make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    obs = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad").obs
    rng = np.random.default_rng(0)
    rows = []
    for name, cl in zip(obs.index, obs["cluster"].astype(str), strict=False):
        # Astro cells pile up on chr1:1000-1100, the rest spread over chr2
        for _ in range(5):
            s = int(rng.integers(1000, 1100)) if cl == "Astro" else int(rng.integers(0, 50_000))
            rows.append(("chr1" if cl == "Astro" else "chr2", s, s + 60, name))
    frag = write_fragments(tmp_path / "src" / "frag.tsv.gz", rows)
    sizes = tmp_path / "src" / "chrom.sizes"
    sizes.write_text("chr1\t100000\nchr2\t100000\n")
    genes = tmp_path / "src" / "genes.bed"
    genes.write_text("chr1\t900\t1200\tGENE1\n")
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [doc["samples"][0]]
    doc["samples"][0]["tracks"] = {"fragments": frag.name, "by": ["cluster"], "genome": "custom", "chrom_sizes": sizes.name, "bin": 10, "genes": genes.name}
    cfg_path.write_text(yaml.safe_dump(doc))
    m = build_dataset(load_config(cfg_path), tmp_path / "bundle", log=lambda *_: None)
    t = m.samples[0].tracks
    assert t is not None and t.by[0].field == "cluster" and t.genes == "tracks/genes.bed" and t.peaks is None
    root = tmp_path / "bundle" / "samples" / "sampleA"
    assert (root / "tracks" / "chrom.sizes").read_text().startswith("chr1\t100000")
    astro = pyBigWig.open(str(root / t.by[0].categories["Astro"]))
    # insertions per million: the whole track sums to 1e6 (each fragment counts both ends)
    total = sum(v[2] for v in astro.intervals("chr1") or []) + sum(v[2] for v in (astro.intervals("chr2") or []))
    assert total == pytest.approx(1e6, rel=1e-3)
    assert astro.stats("chr1", 1000, 1100, type="max")[0] > 0 and not astro.intervals("chr2")
    allbw = pyBigWig.open(str(root / "tracks" / "all.bw"))
    assert allbw.chroms() == {"chr1": 100000, "chr2": 100000} and allbw.intervals("chr2")
    assert len(t.by[0].categories) == len(set(obs["cluster"].dropna().astype(str)))


def test_tracks_reject_unknown_barcodes(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=30, n_genes=4)
    frag = write_fragments(tmp_path / "src" / "frag.tsv.gz", [("chr1", 10, 70, "nobody-1")])
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [doc["samples"][0]]
    doc["samples"][0]["tracks"] = {"fragments": frag.name, "by": ["cluster"]}
    cfg_path.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="no fragment barcodes matched"):
        build_dataset(load_config(cfg_path), tmp_path / "bundle", log=lambda *_: None)
