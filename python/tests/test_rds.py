"""R objects straight from .rds / .rda: the reader, the conversion cache, and `init` / `build` on them."""
from __future__ import annotations

import json
from pathlib import Path

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
