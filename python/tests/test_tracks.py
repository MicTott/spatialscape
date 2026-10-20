"""Genome tracks: one bigWig per category from fragment files (one run or several, pooled) or copied from exported bigWigs."""
from __future__ import annotations

import json

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
    assert t is not None and t.by[0].field == "cluster" and t.genes == "tracks/genes" and t.peaks is None
    root = tmp_path / "bundle" / "samples" / "sampleA"
    assert (root / "tracks" / "chrom.sizes").read_text().startswith("chr1\t100000")
    # the BED of spans became gene models: an index of names plus one file per chromosome
    assert json.loads((root / "tracks" / "genes" / "index.json").read_text())["chroms"] == {"chr1": ["GENE1"]}
    assert json.loads((root / "tracks" / "genes" / "chr1.json").read_text()) == [["GENE1", 0, 900, 1200, [900], [1200]]]
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


def test_tracks_without_gene_models(tmp_path):
    """`genome: custom` has no RefSeq table, so the default `genes: refseq` quietly leaves the gene track out."""
    cfg_path = make_synthetic(tmp_path / "src", n_cells=30, n_genes=4)
    import anndata as ad

    obs = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad").obs
    frag = write_fragments(tmp_path / "src" / "frag.tsv.gz", [("chr1", 10, 70, str(obs.index[0]))])
    (tmp_path / "src" / "chrom.sizes").write_text("chr1\t1000\n")
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [doc["samples"][0]]
    doc["samples"][0]["tracks"] = {"fragments": frag.name, "by": ["cluster"], "genome": "custom", "chrom_sizes": "chrom.sizes"}
    cfg_path.write_text(yaml.safe_dump(doc))
    logs = []
    m = build_dataset(load_config(cfg_path), tmp_path / "bundle", log=logs.append)
    assert m.samples[0].tracks is not None and m.samples[0].tracks.genes is None
    assert any("no RefSeq gene table" in line for line in logs)


def _bigwig(path, sizes, entries, bin_=100):
    bw = pyBigWig.open(str(path), "w")
    bw.addHeader(list(sizes.items()))
    for chrom, start, val in entries:
        bw.addEntries([chrom], [start], ends=[start + bin_], values=[float(val)])
    bw.close()


def _sample_with_runs(tmp_path):
    """sampleA split into runs A and B whose barcodes are the same strings; every A cell is Astro, every B cell Micro;
    observation names carry the run the ArchR way (`A#BC3-1`)."""
    import anndata as ad
    import pandas as pd

    cfg_path = make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    a = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    half = a.n_obs // 2
    run = np.where(np.arange(a.n_obs) < half, "A", "B")
    a.obs["run"] = pd.Categorical(run)
    a.obs["bc"] = [f"BC{i % half}-1" for i in range(a.n_obs)]
    a.obs["cluster"] = pd.Categorical(np.where(run == "A", "Astro", "Micro"), categories=list(a.obs["cluster"].cat.categories))
    a.obs_names = [f"{r}#{b}" for r, b in zip(run, a.obs["bc"], strict=False)]
    a.write_h5ad(tmp_path / "src" / "sampleA.h5ad")
    return cfg_path, a.obs


def test_tracks_pool_several_runs_with_colliding_barcodes(tmp_path):
    cfg_path, obs = _sample_with_runs(tmp_path)
    bc_a = list(obs["bc"][obs["run"] == "A"])
    bc_b = list(obs["bc"][obs["run"] == "B"])
    rows_a = [("chr1", 1000 + i % 50, 1060 + i % 50, b) for i, b in enumerate(bc_a)] * 3 + [("chr2", 500, 560, bc_a[0])]
    rows_b = [("chr1", 5000 + i % 50, 5060 + i % 50, b) for i, b in enumerate(bc_b)] * 3  # same barcode strings, other cells
    fa = write_fragments(tmp_path / "src" / "A.tsv.gz", rows_a)
    fb = write_fragments(tmp_path / "src" / "B.tsv.gz", rows_b)
    (tmp_path / "src" / "chrom.sizes").write_text("chr1\t100000\nchr2\t100000\n")
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [doc["samples"][0]]
    doc["samples"][0]["tracks"] = {
        "fragments": {"A": fa.name, "B": fb.name}, "sample_column": "run", "by": ["cluster"],
        "genome": "custom", "chrom_sizes": "chrom.sizes", "bin": 10, "genes": "none",
    }
    cfg_path.write_text(yaml.safe_dump(doc))
    logs = []
    m = build_dataset(load_config(cfg_path), tmp_path / "bundle", log=logs.append)
    t = m.samples[0].tracks
    assert t is not None and t.all == "tracks/all.bw" and t.units == "insertions per million" and t.bin == 10
    root = tmp_path / "bundle" / "samples" / "sampleA"
    astro = pyBigWig.open(str(root / t.by[0].categories["Astro"]))
    micro = pyBigWig.open(str(root / t.by[0].categories["Micro"]))
    # run A's fragments (chr1:1000-1110) belong to the Astro cells and run B's (chr1:5000-5110) to the Micro cells,
    # although both files use the same barcode strings; a single barcode index would put B's insertions into Astro
    assert astro.stats("chr1", 1000, 1110, type="max")[0] > 0 and not (astro.stats("chr1", 5000, 5110, type="max")[0] or 0)
    assert micro.stats("chr1", 5000, 5110, type="max")[0] > 0 and not (micro.stats("chr1", 1000, 1110, type="max")[0] or 0)
    # per million over the cells pooled from both runs; chr1 came from both files and chr2 from one
    allbw = pyBigWig.open(str(root / "tracks" / "all.bw"))
    total = sum(sum(v[2] for v in (allbw.intervals(c) or [])) for c in ("chr1", "chr2"))
    assert total == pytest.approx(1e6, rel=1e-3) and allbw.intervals("chr2")
    assert sum(v[2] for v in astro.intervals("chr1")) + sum(v[2] for v in (astro.intervals("chr2") or [])) == pytest.approx(1e6, rel=1e-3)
    assert any("A.tsv.gz (A)" in line for line in logs) and any("B.tsv.gz (B)" in line for line in logs)


def test_tracks_from_exported_bigwigs(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=40, n_genes=4)
    sizes = {"chr1": 20000, "chr2": 20000}
    bws = tmp_path / "src" / "bws"
    bws.mkdir()
    _bigwig(bws / "Astro-tile.bw", sizes, [("chr1", 1000, 3.0), ("chr1", 1100, 1.0)])
    _bigwig(bws / "Micro-tile.bw", sizes, [("chr2", 500, 2.0)])
    _bigwig(bws / "all.bw", sizes, [("chr1", 1000, 1.0)])
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [doc["samples"][0]]
    doc["samples"][0]["tracks"] = {"bigwigs": {"by": {"cluster": "bws/{label}-tile.bw"}, "all": "bws/all.bw"}, "genome": "custom", "units": "CPM", "genes": "none"}
    cfg_path.write_text(yaml.safe_dump(doc))
    logs = []
    m = build_dataset(load_config(cfg_path), tmp_path / "bundle", log=logs.append)
    t = m.samples[0].tracks
    assert t is not None and t.by[0].field == "cluster" and set(t.by[0].categories) == {"Astro", "Micro"}  # the other clusters have no file
    assert t.bin == 100 and t.units == "CPM" and t.all == "tracks/all.bw"
    root = tmp_path / "bundle" / "samples" / "sampleA"
    assert (root / "tracks" / "chrom.sizes").read_text() == "chr1\t20000\nchr2\t20000\n"  # `custom` has no table: sizes come from the file
    assert (root / t.by[0].categories["Astro"]).read_bytes() == (bws / "Astro-tile.bw").read_bytes()
    assert any("no file for" in line and "Oligo" in line for line in logs)
    # files listed per label, no `all`, bin given; a raw label the vocabulary aliases onto a category still matches
    doc["fields"] = [dict(f, aliases={"Microglia": "Micro"}) if f["id"] == "cluster" else f for f in doc["fields"]]
    (bws / "Microglia.bw").write_bytes((bws / "Micro-tile.bw").read_bytes())
    doc["samples"][0]["tracks"] = {"bigwigs": {"by": {"cluster": {"Microglia": "bws/Microglia.bw"}}}, "genome": "custom", "bin": 50, "genes": "none"}
    cfg_path.write_text(yaml.safe_dump(doc))
    m = build_dataset(load_config(cfg_path), tmp_path / "bundle2", log=lambda *_: None)
    t = m.samples[0].tracks
    assert t is not None and t.all is None and t.bin == 50 and list(t.by[0].categories) == ["Micro"] and t.units == "signal"
    # nothing matched
    doc["samples"][0]["tracks"] = {"bigwigs": {"by": {"cluster": "bws/nothing-{label}.bw"}}, "genome": "custom", "genes": "none"}
    cfg_path.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="no file matched"):
        build_dataset(load_config(cfg_path), tmp_path / "bundle3", log=lambda *_: None)


def test_tracks_spec_rules(tmp_path):
    from pydantic import ValidationError

    from spatialscape.config import TracksSpec

    with pytest.raises(ValidationError, match="either"):
        TracksSpec(by=["x"])
    with pytest.raises(ValidationError, match="sample_column"):
        TracksSpec(fragments={"A": "a.tsv.gz"}, by=["x"])
    with pytest.raises(ValidationError, match="label"):
        TracksSpec(bigwigs={"by": {"x": "dir/file.bw"}})
    with pytest.raises(ValidationError, match="by"):
        TracksSpec(fragments="a.tsv.gz")
    s = TracksSpec(bigwigs={"by": {"x": "dir/{label}.bw"}})
    assert s.by == ["x"] and s.fragment_files == []
    s = TracksSpec(fragments={"A": "a.tsv.gz", "B": "b.tsv.gz"}, sample_column="run", by=["x"])
    assert [r for r, _ in s.fragment_files] == ["A", "B"]
    # the fingerprint sees every file behind a template
    (tmp_path / "a-x.bw").write_bytes(b"")
    (tmp_path / "b-x.bw").write_bytes(b"")
    s = TracksSpec(bigwigs={"by": {"f": str(tmp_path / "{label}-x.bw")}, "all": tmp_path / "all.bw"}, genes="none")
    assert sorted(p.name for p in s.input_files) == ["a-x.bw", "all.bw", "b-x.bw"]
