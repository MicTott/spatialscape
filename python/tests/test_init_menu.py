"""`init` writes a menu: mapped fields, commented columns, and a yaml that builds as written."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from typer.testing import CliRunner

from spatialscape.build import build_bundle
from spatialscape.cli import app
from spatialscape.config import load_config
from spatialscape.init import default_id, describe_columns, suggest_fields

FIX = Path(__file__).parent / "fixtures"
runner = CliRunner()


def quiet(*_):
    pass


def test_suggest_fields_heuristics():
    n, rng = 200, np.random.default_rng(0)
    obs = pd.DataFrame(
        {
            "sample_id": "s1",
            "BS_k8": pd.Categorical(rng.choice([str(i) for i in range(1, 9)], n)),  # bare cluster numbers
            "BS_k16_relabel": pd.Categorical(rng.choice(["CeA", "MeA", "BLA", "WM"], n)),
            "BS_k16_Semisupervised_wAI": pd.Categorical(rng.choice(["CeA", "MeA", "BLA"], n)),  # the last named one wins
            "sum_umi": rng.integers(100, 5000, n),
            "sum_gene": rng.integers(50, 2000, n),
            "expr_chrM_ratio": rng.random(n) * 0.2,
            "subject": pd.Categorical(rng.choice(["Br1", "Br2"], n)),
            "barcode": [f"b{i}" for i in range(n)],
            "in_tissue": 1,
            "random_score": rng.random(n),
        }
    )
    m = suggest_fields(describe_columns(obs), skip={"sample_id"})
    assert m.mapped == {
        "domain": "BS_k16_Semisupervised_wAI",
        "total_counts": "sum_umi",
        "detected_genes": "sum_gene",
        "mito_percent": {"column": "expr_chrM_ratio", "scale": 100},
    }
    assert [(f, c.name) for f, c in m.alternatives] == [("domain", "BS_k8"), ("domain", "BS_k16_relabel")]
    assert [c.name for c in m.unmapped] == ["subject", "random_score"]
    assert m.skipped == ["sample_id", "barcode", "in_tissue"]
    assert m.notes["domain"].startswith("3 levels:") and "percent" in m.notes["mito_percent"]


def test_fallback_maps_small_categoricals_when_nothing_looks_like_a_domain():
    obs = pd.DataFrame({"group": pd.Categorical(["a", "b"] * 50), "n_genes": range(100), "flag": [True, False] * 50})
    m = suggest_fields(describe_columns(obs))
    assert m.mapped == {"group": "group", "detected_genes": "n_genes"}
    assert [c.name for c in m.unmapped] == ["flag"]


def test_numeric_clusterings_lose_to_named_labels_and_id_columns_are_summarised():
    n = 300
    obs = pd.DataFrame(
        {
            "leiden": pd.Categorical([str(i % 7) for i in range(n)]),
            "cell_type": pd.Categorical(["Astro", "Oligo", "Micro"][i % 3] for i in range(n)),
            "key": [f"cell-{i}" for i in range(n)],
            "neighbourhood": pd.Categorical([f"nb{i % 100}" for i in range(n)]),
        }
    )
    cols = describe_columns(obs)
    assert not next(c for c in cols if c.name == "leiden").named and next(c for c in cols if c.name == "cell_type").named
    m = suggest_fields(cols)
    assert m.mapped == {"domain": "leiden", "celltype": "cell_type"}  # the only domain-like column is still used
    big = next(c for c in m.unmapped if c.name == "neighbourhood")
    assert big.note == "100 levels (too many for a legend)" and m.skipped == ["key"]


def test_default_id_from_the_first_path():
    assert default_id("data/visium/*/adata.h5ad") == "visium"
    assert default_id("Vitessce_app/spe_amy_shinyapp.rds") == "spe_amy_shinyapp"
    assert default_id("samples/foo.h5ad") == "foo"


def test_init_on_an_r_object_writes_a_menu_that_builds(tmp_path):
    out = tmp_path / "proj" / "demo.yaml"
    r = runner.invoke(app, ["init", str(FIX / "tiny_spe.rds"), "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "2 samples: A, B" in r.output and "annotations mapped: celltype" in r.output
    text = out.read_text()
    doc = yaml.safe_load(text)
    s = doc["samples"][0]
    assert s["path"] == "../../fixtures/tiny_spe.rds" or s["path"].endswith("tiny_spe.rds")
    assert s["platform"] == "visium" and s["assay"] == "logcounts" and s["id"] == "vis_{name}"
    assert s["fields"] == {"celltype": "label"}
    assert doc["default_color"] == {"field": "celltype"}
    assert doc["fields"] == [{"id": "celltype", "name": "Cell type", "type": "categorical"}]
    for line in ("# score: score", "# flag: flag", "# note: note", "also in the object: counts", "# sample_col: sample_id", "2 samples: A, B"):
        assert line in text, line
    res = build_bundle(load_config(out), log=quiet)  # builds as written
    assert res.problems == [] and [x.id for x in res.manifest.samples] == ["vis_A", "vis_B"]
    assert res.manifest.defaultColor.field == "celltype" and res.out == tmp_path / "proj" / "bundles" / "demo"


def test_init_on_an_embedding_object(tmp_path):
    out = tmp_path / "sn.yaml"
    r = runner.invoke(app, ["init", str(FIX / "tiny_sce.rds"), "-o", str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    s = yaml.safe_load(text)["samples"][0]
    assert s["platform"] == "snrnaseq" and s["kind"] == "embedding" and s["id"] == "sn_tiny_sce"
    assert "# embedding: UMAP" in text and "also: PCA" in text
    res = build_bundle(load_config(out), log=quiet)
    assert res.problems == [] and res.manifest.samples[0].kind == "embedding"
