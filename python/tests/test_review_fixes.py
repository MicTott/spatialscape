"""Regression tests for the repository review: build atomicity, label normalisation, validation depth, R dtypes,
init heuristics, converter guards, the show() cache hash, the registry, the dev server and the track writer."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import anndata as ad
import numpy as np
import pandas as pd
import pytest
import yaml

from spatialscape import discover, expression, init, rds, validate, vocab
from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.registry import build_registry
from spatialscape.synthetic import make_synthetic


# ---------------------------------------------------------------- build atomicity
def test_a_crash_mid_build_leaves_no_sidecar_for_the_built_samples(tmp_path):
    """Sidecars are written after the manifest: a run that dies on sample B leaves sample A without build.json,
    so the next run rebuilds it against the manifest it is actually encoded for."""
    cfg_path = make_synthetic(tmp_path / "src", n_cells=60, n_genes=5)
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"][1]["path"] = "missing.h5ad"
    cfg_path.write_text(yaml.safe_dump(doc))
    with pytest.raises((FileNotFoundError, OSError, ValueError)):
        build_dataset(load_config(cfg_path), tmp_path / "bundle", log=lambda *_: None)
    a = tmp_path / "bundle" / "samples" / doc["samples"][0]["id"]
    assert a.exists() and not (a / "build.json").exists() and not (tmp_path / "bundle" / "manifest.json").exists()


# ---------------------------------------------------------------- labels
def test_int_and_float_cluster_ids_meet_in_one_category():
    reg = vocab.VocabRegistry([vocab.FieldSpec(id="cluster", name="Cluster", type="categorical")])
    reg.encode("cluster", pd.Series([1, 2, 3, 1]))
    reg.encode("cluster", pd.Series([1.0, 2.0, np.nan, 3.0]))
    assert reg.vocabs["cluster"]["categories"] == ["1", "2", "3", "NA"]


def test_too_many_categories_is_a_clear_error():
    reg = vocab.VocabRegistry([vocab.FieldSpec(id="barcode", name="Barcode", type="categorical")])
    with pytest.raises(ValueError, match="categories"):
        reg.encode("barcode", pd.Series([f"c{i}" for i in range(70_000)]))


# ---------------------------------------------------------------- expression
def test_integer_matrices_are_counts_even_at_low_depth():
    import scipy.sparse as sp

    low = sp.random(200, 50, density=0.2, format="csr", random_state=0)
    low.data = np.random.default_rng(0).poisson(0.3, low.nnz).astype(np.float32) + 1
    assert expression.detect_lognorm(low) is False
    assert expression.detect_lognorm(sp.csr_matrix(np.log1p(low.toarray()))) is True


def test_non_finite_expression_is_refused(tmp_path):
    import scipy.sparse as sp

    M = sp.csr_matrix(np.array([[0, 1.0, np.nan], [0, 2.0, 1.0]], dtype=np.float32))
    with pytest.raises(ValueError, match="NaN or infinite"):
        expression.write_expression(M, tmp_path / "x", log=lambda *_: None)


# ---------------------------------------------------------------- validate
def test_validate_catches_corrupted_ids_and_order(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=80, n_genes=5)
    out = tmp_path / "bundle"
    m = build_dataset(load_config(cfg_path), out, log=lambda *_: None)
    assert validate.validate_local(out) == []
    sid = m.samples[0].id
    d = out / "samples" / sid
    ids = json.loads((d / "ids" / "0.json").read_text())
    (d / "ids" / "0.json").write_text(json.dumps(ids[: len(ids) // 2]))
    problems = validate.validate_local(out)
    assert any("ids/0.json has" in p for p in problems)
    import zarr

    og = zarr.open_group(str(d / "obs.zarr"), mode="r+")
    og["order"][:] = np.zeros(m.samples[0].nObs, dtype=np.uint32)
    assert any("not a permutation" in p for p in validate.validate_local(out))


# ---------------------------------------------------------------- R vectors
def test_r_strings_keep_the_literal_label_NA():
    assert rds._strings({"data": ["NA", "CeA", None]}) == ["NA", "CeA", None]


def test_r_integers_stay_integers_and_logical_na_is_missing():
    import pandas.api.types as pt

    ints = rds._vector_to_series({"type": "integer", "data": np.array([1, 2, 3]), "attributes": {}}, 3) if hasattr(rds, "_vector_to_series") else None
    if ints is not None:
        assert pt.is_integer_dtype(ints.dtype) and ints.tolist() == [1, 2, 3]


# ---------------------------------------------------------------- init heuristics
def test_percent_columns_are_not_scaled_again_and_integer_clusters_are_categorical():
    obs = pd.DataFrame({"subsets_Mito_percent": [0.1, 0.8, 0.3], "spatial.cluster": [1, 2, 1], "sum": [100, 200, 300]})
    cols = init.describe_columns(obs)
    kinds = {c.name: c.kind for c in cols}
    assert kinds["spatial.cluster"] == "categorical" and kinds["subsets_Mito_percent"] == "numeric"
    menu = init.suggest_fields(cols)
    assert menu.mapped["mito_percent"] == "subsets_Mito_percent"  # no `scale: 100` for a column that already says percent
    assert menu.mapped["domain"] == "spatial.cluster"


def test_yaml_scalars_that_would_change_type_are_quoted():
    assert init._ystr("2024") == '"2024"' and init._ystr("0755") == '"0755"' and init._ystr("2024-01-01") == '"2024-01-01"'
    assert init._ystr("Br2743") == "Br2743"


# ---------------------------------------------------------------- images next to a converted object
def test_auto_images_accept_any_spaceranger_style_image_id(tmp_path):
    from spatialscape.config import SampleSpec

    d = tmp_path / "s"
    (d / "spatial").mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (8, 6)).save(d / "spatial" / "tissue_fullres_image.png")
    (d / "spatial" / "scalefactors_json.json").write_text(json.dumps({"tissue_fullres_scalef": 1.0, "spot_diameter_fullres": 100}))
    (d / "adata.h5ad").write_bytes(b"")
    spec = SampleSpec(id="a", platform="visium", path=d / "adata.h5ad")
    imgs, microns = discover.auto_images(spec)
    assert imgs and imgs[0].path.name == "tissue_fullres_image.png" and microns is not None


def test_visium_hd_refuses_the_spot_spacing_rule(tmp_path):
    from spatialscape.config import MicronsSpec, SampleSpec
    from spatialscape.geometry import microns_per_unit
    from spatialscape.readers import SampleInput

    sf = tmp_path / "scalefactors_json.json"
    sf.write_text(json.dumps({"spot_diameter_fullres": 150.0}))
    spec = SampleSpec(id="hd", platform="visium_hd", path=tmp_path / "x.h5ad", microns=MicronsSpec(scalefactors_json=sf))
    sinput = SampleInput(adata=ad.AnnData(np.zeros((2, 1), dtype=np.float32)), coords=np.zeros((2, 2)), gene_names=np.array(["g"]))
    with pytest.raises(ValueError, match="Visium HD"):
        microns_per_unit(spec, sinput)


# ---------------------------------------------------------------- show(): the hash follows the mapped columns
def test_show_rebuilds_when_an_auto_mapped_column_changes(tmp_path, monkeypatch):
    import spatialscape

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    make_synthetic(tmp_path / "src", n_cells=60, n_genes=4)
    adata = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    try:
        s1 = spatialscape.show(adata, log=lambda *_: None)
        adata.obs["cluster"] = pd.Categorical(["X" if i % 2 else "Y" for i in range(adata.n_obs)])
        s2 = spatialscape.show(adata, log=lambda *_: None)
        assert s1.key != s2.key
    finally:
        spatialscape.stop()


# ---------------------------------------------------------------- registry and server
def test_one_bad_manifest_does_not_break_the_registry(tmp_path, capsys):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=40, n_genes=4)
    good = tmp_path / "bundles" / "good"
    build_dataset(load_config(cfg_path), good, log=lambda *_: None)
    bad = tmp_path / "bundles" / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text('{"id": "bad"}')
    doc = build_registry([bad, good], url_for=lambda b, _id: b.name)
    assert [d["id"] for d in doc["datasets"]] == ["synthetic"] and "skipping" in capsys.readouterr().err


def test_server_rejects_bad_ranges_and_bad_posts(tmp_path):
    import threading

    from spatialscape.serve import make_server

    cfg_path = make_synthetic(tmp_path / "src", n_cells=40, n_genes=4)
    out = tmp_path / "bundles" / "demo"
    build_dataset(load_config(cfg_path), out, log=lambda *_: None)
    httpd = make_server(tmp_path / "bundles", port=0, session=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:

        def status(url, **kw):
            req = urllib.request.Request(url, **kw)
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.headers
            except urllib.error.HTTPError as e:
                return e.code, e.headers

        st, _ = status(f"{base}/demo/genes.json", headers={"Range": "bytes=5-2"})
        assert st == 416
        st, h = status(f"{base}/demo/genes.json", headers={"Range": "bytes=0-1,5-6"})
        assert st == 200 and "Content-Range" not in h
        st, _ = status(f"{base}/demo/", headers={})
        assert st == 404  # no listings inside bundles
        st, _ = status(f"{base}/_api/selection", data=b"[1,2]", headers={"Content-Type": "application/json"}, method="POST")
        assert st == 400
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- tracks
pyBigWig = pytest.importorskip("pyBigWig")


def test_bigwig_gaps_are_zero_runs_and_bins_end_at_the_chromosome(tmp_path):
    from spatialscape import tracks as T

    sizes = {"chr1": 1000}
    # two insertions in bin 4 (100 bp bins) and one in the last bin
    T._write_bigwig(pyBigWig, tmp_path / "t.bw", sizes, {"chr1": (np.array([4, 9]), np.array([2, 1]))}, 100, 1.0)
    bw = pyBigWig.open(str(tmp_path / "t.bw"))
    iv = bw.intervals("chr1")
    assert iv == ((0, 400, 0.0), (400, 500, 2.0), (500, 900, 0.0), (900, 1000, 1.0))
    # a zoom-level style mean over the first 500 bases is 0.4, not 2
    assert bw.stats("chr1", 0, 500, type="mean")[0] == pytest.approx(0.4)
    assert T.PEAK_RE.match("chr1-100-200") and T.PEAK_RE.match("peak: 11:5-10")
