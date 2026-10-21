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


def test_platform_is_guessed_from_the_columns():
    from spatialscape.init import guess_platform

    assert guess_platform(["array_row", "array_col", "cluster"], 4_000, spatial=True) == ("visium", "array_col, array_row columns")
    assert guess_platform(["array_row", "array_col"], 300_000, spatial=True)[0] == "visium_hd"
    # the grid decides when it is known: one Visium array is at most 128 x 224 positions, HD bins run to thousands
    assert guess_platform(["array_row", "array_col"], 300_000, spatial=True, array_extent=(77, 127))[0] == "visium"
    assert guess_platform(["array_row", "array_col"], 4_000, spatial=True, array_extent=(830, 830))[0] == "visium_hd"
    # stitched donors: 32k spots in 8 capture areas is Visium, whatever the stitched grid's extent
    plat, why = guess_platform(["array_row", "array_col", "capture_area"], 32_000, spatial=True, array_extent=(243, 480), n_areas=8)
    assert plat == "visium" and why == "array_col, array_row columns; 8 capture areas of 4,000 spots"
    assert guess_platform(["transcript_counts", "cell_area", "nucleus_area"], 120_000, spatial=True)[0] == "xenium"
    assert guess_platform(["cluster"], 120_000, spatial=True)[0] == "xenium"  # cells, not spots
    assert guess_platform(["cluster"], 3_000, spatial=True) == ("visium", None)  # the default, nothing said otherwise
    assert guess_platform(["array_row"], 3_000, spatial=False) == ("snrnaseq", "no spatial coordinates")


def test_describe_columns_counts_missing_values():
    obs = pd.DataFrame({"label": pd.Categorical(["a", "b", None, "a"]), "score": [1.0, np.nan, 2.0, np.nan], "flag": [True, False, True, True]})
    cols = {c.name: c for c in describe_columns(obs)}
    assert cols["label"].na == 1 and cols["label"].note == "2 levels: a, b; 1 NA"
    assert cols["score"].na == 2 and cols["score"].note.endswith("; 2 NA")
    assert cols["flag"].na == 0 and "NA" not in cols["flag"].note


def test_grid_evidence_reads_extent_and_capture_areas():
    from spatialscape.init import grid_evidence

    obs = pd.DataFrame({"array_row": [0, 77, 3], "array_col": [0, 127, 5], "capture_area": ["A1", "B1", "A1"]})
    assert grid_evidence(obs) == {"array_extent": (77.0, 127.0), "n_areas": 2}
    assert grid_evidence(pd.DataFrame({"x": [1]})) == {}


def test_init_says_what_it_assumed_and_marks_the_guess_in_the_yaml(tmp_path):
    import anndata as ad

    from spatialscape.synthetic import make_synthetic

    make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    a = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    a.obs["array_row"] = np.arange(a.n_obs) % 7
    a.obs["array_col"] = np.arange(a.n_obs) // 7
    a.write_h5ad(tmp_path / "src" / "sampleA.h5ad")
    out = tmp_path / "demo.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "*.h5ad"), "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "assumed for" in r.output and "platform: visium (guessed from array_col, array_row columns, array 6 x 7 fits one Visium array)" in r.output
    assert "coordinates: full-resolution pixels; microns from the spot spacing" in r.output
    assert "expression: X; counts are log-normalized by build" in r.output
    assert "annotations: domain <- cluster (6 levels, 7 NA), total_counts <- total_counts" in r.output
    text = out.read_text()
    assert "platform: visium" in text and "guessed from array_col, array_row columns, array 6 x 7 fits one Visium array; or visium_hd, xenium, merfish" in text
    assert "6 levels: " in text and "; 7 NA" in text  # the NA count sits in the column's note
    assert yaml.safe_load(text)["samples"][0]["platform"] == "visium"
    # given on the command line: the yaml says so, and nothing is guessed
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "*.h5ad"), "--platform", "visium_hd", "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0 and "platform: visium_hd (given)" in r.output and "set `microns: { microns_per_unit:" in r.output
    assert "platform: visium_hd" in out.read_text() and "given; or visium, xenium, merfish" in out.read_text()


def test_init_warns_when_one_file_holds_several_sections(tmp_path):
    import anndata as ad

    from spatialscape.synthetic import make_synthetic

    make_synthetic(tmp_path / "src", n_cells=60, n_genes=5)
    a = ad.read_h5ad(tmp_path / "src" / "sampleA.h5ad")
    a.obs["sample_id"] = pd.Categorical(["Br1", "Br2", "Br3"] * (a.n_obs // 3))
    a.write_h5ad(tmp_path / "src" / "pooled.h5ad")
    out = tmp_path / "demo.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "pooled.h5ad"), "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "pooled.h5ad holds 3 sections (sample_id: Br1, Br2, Br3)" in r.output and "subset: { column: sample_id, values: [Br1] }" in r.output
    assert "sections: 3 in one file (sample_id: Br1, Br2, Br3), drawn as one sample" in r.output
    text = out.read_text()
    assert "# subset: { column: sample_id, values: [Br1] }" in text and "this file holds 3 sections" in text
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "sampleB.h5ad"), "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0 and "holds" not in r.output and "subset:" not in out.read_text()  # one section: no hint
