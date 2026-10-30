"""R objects straight from .rds / .rda: the reader, the conversion cache, and `init` / `build` on them."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from spatialscape.build import build_bundle
from spatialscape.cli import app
from spatialscape.config import RObjectEntry, load_config
from spatialscape.convert import cache_key, read_index, write_cache
from spatialscape.rds import read_experiment

FIX = Path(__file__).parent / "fixtures"
runner = CliRunner()


def quiet(*_):
    pass


def _yaml(tmp_path: Path, entries: list[dict], **top) -> Path:
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": entries, **top}))
    return p


def test_reader_covers_spe_sce_and_rda():
    spe = read_experiment(FIX / "tiny_spe.rds")
    assert spe.class_name == "SpatialExperiment" and spe.n_vars == 12 and spe.n_obs == 40
    assert set(spe.assays) == {"counts", "logcounts"}
    assert spe.assays["logcounts"].shape == (12, 40)
    assert str(spe.obs["label"].dtype) == "category" and spe.obs["label"].isna().sum() > 0  # NA level kept as missing
    assert spe.obs["flag"].dtype.kind == "b" and str(spe.obs["note"].dtype) == "category"
    assert spe.obs.index[0] == "c1" and spe.var.index[0] == "G1" and spe.var["gene_name"].iloc[0] == "g1"
    assert spe.spatial.shape == (40, 2)
    loaded = [i for i in spe.images if i.rgb is not None]
    stored = [i for i in spe.images if i.rgb is None]
    assert len(loaded) == 1 and loaded[0].rgb.shape == (6, 8, 3) and loaded[0].scale_factor == 0.05
    assert len(stored) == 1 and stored[0].path.endswith(".png")
    sce = read_experiment(FIX / "tiny_sce.rds")
    assert sce.spatial is None and set(sce.reduced_dims) == {"UMAP", "PCA"} and sce.reduced_dims["UMAP"].shape == (40, 2)
    rda = read_experiment(FIX / "tiny_spe.rda")
    assert rda.n_obs == 40 and rda.class_name == "SpatialExperiment"


def test_spatial_object_builds_through_the_cache(tmp_path):
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "visium", "id": "vis_{name}", "fields": {"celltype": "label", "score": "score"}}])
    cfg = load_config(p)
    assert cfg.samples == [] and len(cfg.r_objects) == 1 and cfg.r_objects[0].template["platform"] == "visium"
    r = build_bundle(cfg, log=quiet)
    assert r.problems == [] and [s.id for s in r.manifest.samples] == ["vis_A", "vis_B"]
    a = r.manifest.samples[0]
    assert a.nObs == 20 and a.images and a.images[0].pixelSize == pytest.approx(1 / 0.05, rel=0.2) and a.fields == ["celltype", "score"]
    cache = tmp_path / "bundles" / ".cache" / "t"
    keys = [d for d in cache.iterdir() if d.is_dir()]
    assert len(keys) == 1
    idx = read_index(keys[0])
    assert idx["spatial"] and idx["samples"] == ["A", "B"] and idx["assay"] == "logcounts"
    sf = json.loads((keys[0] / "A" / "spatial" / "scalefactors_json.json").read_text())
    assert sf["tissue_lowres_scalef"] == 0.05 and sf["spot_diameter_fullres"] == pytest.approx(55.0)
    assert (keys[0] / "A" / "spatial" / "tissue_lowres_image.png").exists()
    r2 = build_bundle(load_config(p), log=quiet)  # second build: cache hit, nothing rebuilt
    assert r2.plan.sources[0].state == "cached" and all(not x.build for x in r2.plan.actions)


def test_changed_assay_makes_a_new_key_and_prunes_the_old(tmp_path):
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "visium"}])
    build_bundle(load_config(p), log=quiet)
    doc = yaml.safe_load(p.read_text())
    doc["samples"][0]["assay"] = "counts"
    p.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(p), log=quiet)
    assert r.plan.sources[0].state == "converted"
    assert len([d for d in (tmp_path / "bundles" / ".cache" / "t").iterdir() if d.is_dir()]) == 1
    assert {a.reason for a in r.plan.actions} == {"source changed"} and r.problems == []


def test_embedding_object_rda_and_xenium_defaults(tmp_path):
    p = _yaml(
        tmp_path,
        [
            {"path": str(FIX / "tiny_sce.rds"), "fields": {"celltype": "label"}},
            {"path": str(FIX / "tiny_spe.rda"), "platform": "visium", "id": "rda_{name}"},
            {"path": str(FIX / "tiny_spe.rds"), "platform": "xenium", "id": "xen_{name}"},
        ],
    )
    r = build_bundle(load_config(p), log=quiet)
    assert [s.id for s in r.manifest.samples] == ["tiny_sce", "rda_A", "rda_B", "xen_A", "xen_B"]
    sn = r.manifest.samples[0]
    assert sn.kind == "embedding" and sn.platform == "snrnaseq" and sn.nObs == 40
    assert r.manifest.samples[3].pointRadius == 5.0  # xenium: coordinates taken as microns
    assert r.problems == []


def test_errors_name_the_setting(tmp_path):
    with pytest.raises(KeyError, match="assay 'nope'"):
        build_bundle(load_config(_yaml(tmp_path, [{"path": str(FIX / "tiny_sce.rds"), "assay": "nope"}])), log=quiet)
    with pytest.raises(ValueError, match="no 2-D embedding"):
        build_bundle(load_config(_yaml(tmp_path, [{"path": str(FIX / "tiny_sce.rds"), "embedding": "nope"}])), log=quiet)
    with pytest.raises(Exception, match="platform"):  # the entry's template is checked when the yaml loads
        load_config(_yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "nope"}]))
    with pytest.raises(FileNotFoundError):
        build_bundle(load_config(_yaml(tmp_path, [{"path": str(tmp_path / "missing.rds"), "platform": "visium"}])), log=quiet)


def test_dry_run_reports_pending_without_parsing(tmp_path, monkeypatch):
    import spatialscape.convert as cv

    def boom(*_a, **_k):
        raise AssertionError("the dry run parsed the object")

    monkeypatch.setattr(cv, "read_experiment", boom)
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "visium"}])
    r = build_bundle(load_config(p), dry_run=True, log=quiet)
    assert r.manifest is None and r.plan.sources[0].state == "pending" and r.plan.actions == []
    assert not (tmp_path / "bundles").exists()


def test_write_cache_keys_on_file_and_settings(tmp_path):
    e1 = RObjectEntry(path=FIX / "tiny_spe.rds")
    assert cache_key(e1) == cache_key(RObjectEntry(path=FIX / "tiny_spe.rds"))
    assert cache_key(e1) != cache_key(RObjectEntry(path=FIX / "tiny_spe.rds", assay="counts"))
    idx = write_cache(e1, tmp_path / "cache", log=quiet)
    assert idx["samples"] == ["A", "B"] and (tmp_path / "cache" / cache_key(e1) / "index.json").exists()
    import anndata as ad

    a = ad.read_h5ad(tmp_path / "cache" / cache_key(e1) / "A" / "adata.h5ad")
    assert {"label", "score", "flag", "note"} <= set(a.obs.columns)  # every column is kept; the yaml picks


def test_inspect_reads_r_objects():
    r = runner.invoke(app, ["inspect", str(FIX / "tiny_spe.rds")])
    assert r.exit_code == 0, r.output
    assert "SpatialExperiment" in r.output and "A (20)" in r.output and "lowres" in r.output and "spatialscape init" in r.output


def test_raster_colours_are_stored_row_by_row():
    """R rasters are the one R matrix stored row-major: as.vector(as.raster(m)) walks row 1 first. Decoding them
    column-major turns an H&E into vertical streaks (seen on a real SpatialExperiment)."""
    from spatialscape.rds import _hex_to_rgb

    # a 2 x 3 raster whose colour encodes (row, col) as (R, G), in the order R serialises it
    flat = [f"#{i * 16:02X}{j * 16:02X}00" for i in (1, 2) for j in (1, 2, 3)]
    rgb = _hex_to_rgb(flat, 2, 3)
    assert rgb.shape == (2, 3, 3)
    assert rgb[0, 2, :2].tolist() == [16, 48] and rgb[1, 0, :2].tolist() == [32, 16]
    # magick-made rasters carry an alpha byte (#RRGGBBAA); it is ignored
    assert _hex_to_rgb(["#102030ff"], 1, 1)[0, 0].tolist() == [16, 32, 48]


def test_seurat_object_reader():
    """tiny_seurat.rds (python/tests/fixtures/make_tiny_seurat.R): a v5 RNA assay split into two runs, a v3 'ATAC'
    assay named by peak coordinates, meta.data of several types, an ident and two reductions."""
    x = read_experiment(FIX / "tiny_seurat.rds")
    assert x.class_name == "Seurat" and x.assay_name == "RNA" and set(x.assays) == {"counts", "data"}
    assert x.assays["counts"].shape == (8, 24) and x.obs.index[0] == "run1#BC01-1" and x.var.index[0] == "G1"
    g1 = x.assays["counts"][0].toarray().ravel()  # split layers are joined back in the object's cell order: G1 marks run1
    assert g1[:12].min() >= 20 and g1[12:].max() < 20
    assert list(x.obs["ident"][:3]) == ["Astro", "Micro", "Oligo"] and str(x.obs["cell_type"].dtype) == "category"
    assert x.obs["flag"].dtype.kind == "b" and x.obs["score"].dtype.kind == "f" and list(x.obs["sample"][:1]) == ["run1"]
    assert {k: v.shape for k, v in x.reduced_dims.items()} == {"umap": (24, 2), "pca": (24, 3)}
    (fs,) = x.feature_sets
    assert fs.name == "ATAC" and fs.prefix == "peak: " and list(fs.var.index) == ["chr1-100-200", "chr1-500-650", "chr2-10-90"]
    assert fs.assays["data"].shape == (3, 24) and x.fragments == [] and x.notes == [] and x.spatial is None
    assert list(x.obs["idx"][:3]) == [1, 2, 3]  # an ALTREP compact sequence; the closure in @commands was walked past


def test_seurat_object_builds_with_its_peaks_as_features(tmp_path):
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_seurat.rds"), "platform": "snrnaseq", "id": "sn", "fields": {"celltype": "cell_type", "run": "sample"}}])
    r = build_bundle(load_config(p), log=quiet)
    assert r.problems == [] and len(r.manifest.samples) == 1
    s = r.manifest.samples[0]
    assert s.kind == "embedding" and s.nObs == 24 and s.fields == ["celltype", "run"]
    genes = json.loads((r.out / "genes.json").read_text())
    assert "G1" in genes and "peak: chr1-100-200" in genes and len(genes) == 11
    cache = tmp_path / "bundles" / ".cache" / "t"
    idx = read_index(next(d for d in cache.iterdir() if d.is_dir()))
    assert idx["assay"] == "logcounts" and idx["class"] == "Seurat" and idx["embedding"] == "umap"
    assert idx["feature_sets"] == [{"name": "ATAC", "prefix": "peak: ", "features": 3}] and idx["fragments"] == []


def test_inspect_and_init_describe_a_seurat_object(tmp_path):
    out = runner.invoke(app, ["inspect", str(FIX / "tiny_seurat.rds")])
    assert out.exit_code == 0, out.output
    assert "Seurat assay drawn as expression: RNA" in out.output and "feature set ATAC: 3 features drawn as 'peak: '" in out.output
    y = tmp_path / "sn.yaml"
    r = runner.invoke(app, ["init", str(FIX / "tiny_seurat.rds"), "--id", "sn", "-o", str(y)])
    assert r.exit_code == 0, r.output
    doc = yaml.safe_load(y.read_text())
    assert doc["samples"][0]["assay"] == "data" and doc["samples"][0]["kind"] == "embedding"
    assert "ATAC as peak: features" in y.read_text()


def test_fragment_records_become_run_and_barcode_columns():
    from spatialscape.init import EntryMenu, Menu, _entry_lines
    from spatialscape.rds import RFragments, fragment_columns

    frs = [
        RFragments("/proj/cellrangerARC/4S_Hb_KDM/outs/atac_fragments.tsv.gz", {"S04_AAAC-1": "AAAC-1", "S04_GGGG-1": "GGGG-1"}),
        RFragments("/proj/run2/fragments.tsv.gz", {"S05_AAAC-1": "AAAC-1"}),
    ]
    assert [f.run for f in frs] == ["4S_Hb_KDM", "fragments"]
    run, bc = fragment_columns(["S04_AAAC-1", "S05_AAAC-1", "S04_GGGG-1", "orphan"], frs)
    assert list(run.astype(object)[:3]) == ["4S_Hb_KDM", "fragments", "4S_Hb_KDM"] and pd.isna(run.iloc[3])  # a cell no file covers
    assert list(bc[:3]) == ["AAAC-1", "AAAC-1", "GGGG-1"] and bc.iloc[3] is None
    assert fragment_columns(["a"], [RFragments("x.tsv.gz", None)]) is None
    menu = Menu()
    menu.mapped["celltype"] = "ident"
    menu.kinds["celltype"] = "categorical"
    e = EntryMenu(source="obj.rds", source_note="", r_object=True, embedding=True, platform="snrnaseq", id_tpl="sn", name_tpl="sn", group_tpl="sn",
                  menu=menu, samples=["obj"], assay="data", assays=["counts", "data"], embedding_key="umap", embeddings=["umap"],
                  fragments={f.run: f.path for f in frs})
    text = "\n".join(_entry_lines(e))
    assert "#   sample_column: fragment_run" in text and "#   barcode_column: fragment_barcode" in text and "by: [celltype]" in text
    assert "4S_Hb_KDM:" in text and "/proj/cellrangerARC/4S_Hb_KDM/outs/atac_fragments.tsv.gz" in text  # the path may be quoted


def test_overrides_apply_to_the_samples_of_an_r_object(tmp_path):
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "visium", "id": "vis_{name}", "fields": {"celltype": "label"}, "overrides": {"B": {"name": "Section B", "images": []}}}])
    cfg = load_config(p)
    assert cfg.r_objects[0].template["overrides"] == {"B": {"name": "Section B", "images": []}}
    r = build_bundle(cfg, log=quiet)
    assert r.problems == [] and [s.id for s in r.manifest.samples] == ["vis_A", "vis_B"]
    a, b = r.manifest.samples
    assert a.images and a.name == "vis_A" and b.name == "Section B" and b.images == []
    p = _yaml(tmp_path, [{"path": str(FIX / "tiny_spe.rds"), "platform": "visium", "overrides": {"C": {"images": []}}}])
    with pytest.raises(ValueError, match="overrides name no sample: C"):
        build_bundle(load_config(p), log=quiet)


def test_sample_names_that_sanitize_alike_are_refused():
    import pytest

    from spatialscape.convert import _folder_names

    assert _folder_names(["A B", "C"]) == {"A B": "A_B", "C": "C"}
    with pytest.raises(ValueError, match="both become the folder"):
        _folder_names(["A B", "A/B"])
    with pytest.raises(ValueError):
        _folder_names([".."])
