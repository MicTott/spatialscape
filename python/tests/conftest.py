import anndata as ad
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp


@pytest.fixture
def small_adata():
    rng = np.random.default_rng(0)
    n, g = 300, 12
    X = rng.poisson(0.7, size=(n, g)).astype(np.float32)
    X[:, 5] = 0  # all-zero gene is dropped
    obs = pd.DataFrame(
        {
            "cluster": pd.Categorical(rng.choice(["A", "B", "C"], n)),
            "score": rng.normal(size=n),
        },
        index=[f"c{i}" for i in range(n)],
    )
    obs.loc[obs.index[:3], "cluster"] = np.nan
    a = ad.AnnData(X=sp.csr_matrix(X), obs=obs, var=pd.DataFrame(index=[f"G{i}" for i in range(g)]))
    a.obsm["spatial"] = rng.uniform(0, 1000, size=(n, 2))
    a.uns["spot_nn_spacing_level0_px"] = 20.0
    return a
