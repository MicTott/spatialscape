"""Fidelity: what the bundle stores equals the source, within the format's stated precision. The synthetic dataset
has a flipped and rotated section, an H&E image that sets the frame, polygons, molecules and a counts section the
build log-normalises, so every transform the real datasets go through is exercised here."""

import json

import anndata as ad
import numpy as np
import pyarrow.parquet as pq
import pytest
import zarr
from scipy.stats import mannwhitneyu

from spatialscape import fidelity
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from spatialscape.build import build_dataset

    root = tmp_path_factory.mktemp("fid")
    cfg_path = make_synthetic(root / "src", n_cells=600, n_genes=30)
    out = root / "bundle"
    build_dataset(load_config(cfg_path), out)
    return cfg_path, out


def test_bundle_matches_its_source(built):
    cfg_path, out = built
    report = fidelity.check_bundle(cfg_path, out, n_genes=30, n_rows=200, molecule_genes=10)
    assert fidelity.verdict(report) == [], json.dumps(report, indent=1, default=str)[:3000]
    by_id = {s["sample"]: s for s in report["samples"]}
    # the stated bounds, not just "no problem": half a code step, zeros exact, positions to float32
    for s in report["samples"]:
        assert s["expression"]["max_error_steps_unbumped"] <= 0.5
        assert s["expression"]["zeros_preserved"] and s["expression"]["nonzero_preserved"]
        assert s["expression"]["min_pearson"] > 0.9999
        assert (
            s["expression"]["min_spearman"] > 0.98
        )  # values under half a step tie at code 1: ranks move, values do not
        assert s["positions"]["max_error_um"] < 1e-3
    a, b = by_id["sampleA"], by_id["sampleB"]
    assert a["normalized"] == "lognorm" and b["normalized"] == "log1p_cp10k"
    assert a["rows"]["codes_match_gene_major"] and b["rows"]["codes_match_gene_major"]
    for s in (a, b):
        assert s["shapes"]["missing"] == 0 and s["shapes"]["vertex_count_mismatch"] == 0
        assert s["shapes"]["max_vertex_error_um"] <= fidelity.SHAPE_GRID / 2
        assert s["molecules"]["counts_match"]
        assert s["molecules"]["max_nn_distance_um"] <= fidelity.MOLECULE_GRID * 0.71
        assert s["molecules"]["controls_in_store"] == []
    assert by_id["umapA"]["rows"] == {"present": False}  # embeddings carry no row store


def test_positions_against_the_raw_file_not_the_readers(built):
    """sampleB is flipped in x and rotated 90 degrees with the image setting the frame: recompute its positions from
    the h5ad and the PNG alone and compare with obs.zarr."""
    cfg_path, out = built
    cfg = load_config(cfg_path)
    spec = next(s for s in cfg.samples if s.id == "sampleB")
    a = ad.read_h5ad(spec.path)
    xy = np.asarray(a.obsm["spatial"], dtype=np.float64)
    upu = 100.0 / float(a.uns["spot_nn_spacing_level0_px"])  # Visium: 100 um between spot centres
    import imageio.v3 as iio

    _h, w = iio.imread(spec.images[0].path).shape[:2]
    x, y = w - xy[:, 0], xy[:, 1]  # flip x in a frame of width w ...
    x, y = y, w - x  # ... then rotate 90 counter-clockwise
    expected = np.column_stack([x, y]) * upu
    expected -= expected.min(axis=0)
    perm = np.random.default_rng(spec.seed).permutation(a.n_obs)
    stored = np.asarray(zarr.open_group(str(out / "samples/sampleB/obs.zarr"), mode="r")["xy"][:])
    assert np.abs(stored - expected[perm]).max() < 1e-3


def test_expression_against_the_raw_file(built):
    """sampleA stores lognorm values as they are: code * gmax / 255 is within half a step of the h5ad."""
    _cfg_path, out = built
    a = ad.read_h5ad(out.parent / "src" / "sampleA.h5ad")
    d = out / "samples" / "sampleA"
    genes = json.loads((d / "genes.json").read_text())
    g = zarr.open_group(str(d / "expr.zarr"), mode="r")
    perm = np.random.default_rng(7).permutation(a.n_obs)
    X = a.X.toarray()
    for name in genes[:5]:
        i = genes.index(name)
        j = list(a.var_names).index(name)
        vals = np.asarray(g["u8"][i, :]) / 255 * float(g["gmax"][i])
        src = X[perm, j]
        step = float(g["gmax"][i]) / 255
        small = (src > 0) & (src < step / 2)  # rounded up to code 1 on purpose
        assert np.abs(vals - src)[~small].max() <= step / 2 + 1e-6
        assert np.array_equal(vals == 0, src == 0)


def test_molecule_counts_against_the_parquet_file(built):
    _cfg_path, out = built
    t = pq.read_table(out.parent / "src" / "sampleA.transcripts.parquet", columns=["feature_name", "qv"]).to_pandas()
    kept = t[(t.qv >= 20) & ~t.feature_name.str.startswith("NegControl")]
    names, gene, _xy, _flags = fidelity.read_molecules(out / "samples" / "sampleA")
    stored = {names[i]: int(n) for i, n in enumerate(np.bincount(gene, minlength=len(names)))}
    assert stored == kept.feature_name.value_counts().to_dict()


def test_lasso_oracle_matches_the_viewer_rule():
    poly = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    pts = np.array([[5, 5], [10, 5], [0, 5], [5, 0], [5, 10], [-1, 5], [11, 5], [9.999, 9.999]])
    # the viewer's ray cast: left and bottom edges are inside, right and top edges are outside
    assert fidelity.point_in_polygon(pts, poly).tolist() == [True, False, True, True, False, False, False, True]


def test_reference_test_is_scipy_on_the_dequantised_rows(built):
    """The reference the browser is compared against: a region pair on sampleA and sampleB, p from scipy on exactly
    the cells and values the row store holds, and the quantisation's effect on p measured against the source."""
    cfg_path, out = built
    genes = json.loads((out / "features.json").read_text())["genes"]
    sides = {}
    for sid in ("sampleA", "sampleB"):
        xy = np.asarray(zarr.open_group(str(out / "samples" / sid / "obs.zarr"), mode="r")["xy"][:])
        xmid = np.median(xy[:, 0])
        left = np.array([[-1, -1], [xmid, -1], [xmid, 1e5], [-1, 1e5]])
        right = np.array([[xmid, -1], [1e5, -1], [1e5, 1e5], [xmid, 1e5]])
        a = np.flatnonzero(fidelity.point_in_polygon(xy, left))
        b = np.flatnonzero(fidelity.point_in_polygon(xy, right))
        sides[sid] = (a, b)
    ref = fidelity.reference_level(out, genes, sides)
    tested = np.isfinite(ref["p"])
    assert tested.sum() > 10 and ref["n_sections"] == 2
    assert np.all((ref["agree"][tested] >= 0) & (ref["agree"][tested] <= 2))
    assert np.all(ref["padj"][tested] >= ref["p"][tested])
    # against the source floats: the same test on the un-quantised values of the same cells, section by section
    cfg = load_config(cfg_path)
    worst = {}
    flips = []
    for sid in sides:
        spec = next(s for s in cfg.samples if s.id == sid)
        a = ad.read_h5ad(spec.path)
        X = a.X.toarray()
        if sid == "sampleB":  # counts: the build applied log1p(CP10k)
            X = np.log1p(X / X.sum(1, keepdims=True) * 1e4)
        perm = np.random.default_rng(spec.seed).permutation(a.n_obs)
        ra, rb = (perm[rows] for rows in sides[sid])
        one = fidelity.reference_level(out, genes, {sid: sides[sid]})
        worst[sid] = 0.0
        for g, name in enumerate(genes):
            if not np.isfinite(one["p"][g]):
                continue
            j = list(a.var_names).index(name)
            p_src = mannwhitneyu(
                X[ra, j], X[rb, j], alternative="two-sided", method="asymptotic", use_continuity=True
            ).pvalue
            worst[sid] = max(worst[sid], abs(np.log10(p_src) - np.log10(one["p"][g])))
            if (p_src < 0.05) != (one["p"][g] < 0.05):
                flips.append((sid, name, p_src, one["p"][g]))
    assert flips == []
    # sampleB is log1p(CP10k) of counts, the shape of real data: the codes move log10 p by a few hundredths.
    # sampleA's synthetic Gaussians put about 15% of expressing cells under half a code step; those tie at code 1
    # and the test turns slightly conservative (p up to about 3x larger). Real log-normalised data has a floor
    # at log1p(1e4 / total counts), so this case is rarer there; the bound is recorded, not hidden.
    assert worst["sampleB"] < 0.1, worst
    assert worst["sampleA"] < 1.0, worst
