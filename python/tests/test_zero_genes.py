"""A feature a sample measured and found zero everywhere is not stored, but it is not "unmeasured": the build lists
it in zero_genes.json and the manifest counts it, so the viewer can draw it as zero and a test can count its cells."""

import json

import numpy as np

from spatialscape.config import DatasetConfig, SampleSpec


def test_all_zero_features_are_listed_not_stored(tmp_path, small_adata):
    from spatialscape.build import build_dataset
    from spatialscape.validate import validate_local

    a = small_adata.copy()
    X = a.X.toarray() if hasattr(a.X, "toarray") else np.asarray(a.X)
    X[:, 2] = 0  # G2 (or whatever the third feature is) measured, never detected
    a.X = X
    src = tmp_path / "a.h5ad"
    a.write_h5ad(src)
    out = tmp_path / "bundle"
    build_dataset(DatasetConfig(id="t", name="t", samples=[SampleSpec(id="s", platform="visium", path=src)]), out)
    m = json.loads((out / "manifest.json").read_text())
    s = m["samples"][0]
    zero_name = str(a.var_names[2])
    stored = json.loads((out / "samples" / "s" / "genes.json").read_text())
    zero = json.loads((out / "samples" / "s" / "zero_genes.json").read_text())
    assert zero_name not in stored and zero_name in zero
    assert set(zero).isdisjoint(stored) and len(zero) + len(stored) == a.n_vars  # every feature is in one list or the other
    assert s["nZeroGenes"] == len(zero) and s["nGenes"] == len(stored)
    assert validate_local(out) == []
