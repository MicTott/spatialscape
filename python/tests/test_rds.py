"""R objects straight from .rds / .rda: the reader, `convert`, and the chain into init / build."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from spatialscape.build import build_dataset
from spatialscape.cli import app
from spatialscape.config import load_config
from spatialscape.convert import convert_object
from spatialscape.rds import read_experiment

FIX = Path(__file__).parent / "fixtures"
runner = CliRunner()


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


def test_convert_writes_the_spaceranger_layout_and_builds(tmp_path):
    out = tmp_path / "visium"
    written = convert_object(FIX / "tiny_spe.rds", out, cols=["label", "score"], log=lambda *_: None)
    assert sorted(w.parent.name for w in written) == ["A", "B"]
    sf = json.loads((out / "A" / "spatial" / "scalefactors_json.json").read_text())
    assert sf["tissue_lowres_scalef"] == 0.05 and sf["spot_diameter_fullres"] == pytest.approx(55.0)
    assert (out / "A" / "spatial" / "tissue_lowres_image.png").exists()
    # the whole chain: init -> build on the converted folder, images and scale picked up automatically
    cfg = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(out / "*" / "adata.h5ad"), "--platform", "visium", "--id", "t", "-o", str(cfg)])
    assert r.exit_code == 0, r.output
    m = build_dataset(load_config(cfg), tmp_path / "bundle", log=lambda *_: None)
    a = next(s for s in m.samples if s.id == "vis_A")
    assert a.nObs == 20 and a.images and a.images[0].pixelSize == pytest.approx(55 / 55 / 0.05 * 1.0, rel=0.2)
    assert "label" in a.fields and "score" in a.fields


def test_convert_embedding_and_errors(tmp_path):
    out = tmp_path / "sn"
    written = convert_object(FIX / "tiny_sce.rds", out, cols=["label"], log=lambda *_: None)
    assert written == [out / "tiny_sce.h5ad"]
    import anndata as ad

    a = ad.read_h5ad(written[0])
    assert a.obsm["X_umap"].shape == (40, 2) and list(a.obs.columns) == ["label"]
    with pytest.raises(KeyError, match="assay 'nope'"):
        convert_object(FIX / "tiny_sce.rds", out, assay="nope", log=lambda *_: None)
    with pytest.raises(KeyError, match="missing_col"):
        convert_object(FIX / "tiny_spe.rds", out, cols=["missing_col"], log=lambda *_: None)
    with pytest.raises(ValueError, match="no 2-D embedding"):
        convert_object(FIX / "tiny_sce.rds", out, embedding="nope", log=lambda *_: None)


def test_convert_microns_per_pixel_and_cli(tmp_path):
    r = runner.invoke(app, ["convert", str(FIX / "tiny_spe.rds"), "-o", str(tmp_path / "hd"), "--microns-per-pixel", "0.25", "--cols", "label"])
    assert r.exit_code == 0, r.output
    sf = json.loads((tmp_path / "hd" / "A" / "spatial" / "scalefactors_json.json").read_text())
    assert sf["microns_per_pixel"] == 0.25 and "spot_diameter_fullres" not in sf
    assert "next:" in r.output and "spatialscape init" in r.output


def test_inspect_reads_r_objects():
    r = runner.invoke(app, ["inspect", str(FIX / "tiny_spe.rds")])
    assert r.exit_code == 0, r.output
    assert "SpatialExperiment" in r.output and "A (20)" in r.output and "lowres" in r.output and "convert" in r.output
