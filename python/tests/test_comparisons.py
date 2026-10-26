"""Comparisons: tables in, bundle files out; column recognition, replicate linking, the incremental rule, init."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
import zarr
from typer.testing import CliRunner

from spatialscape.build import build_bundle
from spatialscape.cli import app
from spatialscape.comparisons import (
    RESULT_ROLES,
    find_split_key,
    link_replicates,
    load_tables,
    map_columns,
    read_table,
    resolve_comparison,
)
from spatialscape.config import ComparisonSpec, load_config
from spatialscape.manifest import MetaKey, Sample
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local

runner = CliRunner()


def quiet(*_):
    pass


def creasons(res) -> dict[str, str]:
    return {a.spec.id: a.reason for a in res.plan.comparisons}


def sreasons(res) -> set[str]:
    return {a.reason for a in res.plan.actions}


@pytest.fixture
def experiment(tmp_path):
    return make_synthetic(tmp_path / "src", n_cells=150, n_genes=12, comparisons=True)


def test_synthetic_comparison_builds_and_validates(experiment):
    r = build_bundle(load_config(experiment), log=quiet)
    assert r.problems == [] and validate_local(r.out) == []
    c = next(x for x in r.manifest.comparisons if x.id == "stress_vs_control")
    assert (c.kind, c.groups, c.split, c.link, c.units, c.facet) == ("contrast", ["control", "stress"], "condition", "mouse", "log2 mean+1", None)
    assert (c.nGenes, c.nReplicates, c.nUnmatched, c.hasEffect, c.hasP, c.hasPadj, c.hasMean, c.hasPseudobulk) == (12, 4, 0, True, True, True, True, True)
    [lv] = c.levels
    assert (lv.id, lv.name, lv.path, lv.nGenes, lv.nReplicates, lv.hasPseudobulk, lv.population) == ("all", "all", "levels/all", 12, 4, True, None)
    d = r.out / "comparisons" / "stress_vs_control"
    doc = json.loads((d / "comparison.json").read_text())
    assert {rep["id"]: (rep["group"], rep["samples"]) for rep in doc["replicates"]["all"]} == {"m1": ("control", ["sampleA"]), "m2": ("control", ["sampleB"]), "m3": ("stress", ["sampleC"]), "m4": ("stress", ["sampleD"])}
    assert doc["columns"] == {"gene": "gene", "effect": "log2FoldChange", "p": "pvalue", "padj": "padj", "mean": "baseMean", "replicate_id": "mouse", "replicate_group": "condition"}
    res = json.loads((d / "levels" / "all" / "results.json").read_text())
    assert len(res["genes"]) == 12 and res["unmeasured"] == []
    padj = [v if v is not None else np.inf for v in res["padj"]]
    assert padj == sorted(padj)  # rows sorted by padj
    by_effect = sorted(zip(res["effect"], res["genes"], strict=True), reverse=True)
    assert {g for _, g in by_effect[:3]} == {"G000", "G001", "G002"} and by_effect[2][0] > 0  # the planted genes have the largest effects, higher in stress
    pb = zarr.open_array(str(d / "levels" / "all" / "pseudobulk.zarr"), mode="r")
    assert pb.shape == (12, 4) and np.isfinite(pb[:]).all()
    assert (d / "build.json").exists()


def test_comparisons_rebuild_only_when_their_inputs_or_the_samples_change(experiment):
    build_bundle(load_config(experiment), log=quiet)
    r = build_bundle(load_config(experiment), log=quiet)
    assert set(creasons(r).values()) == {"unchanged"} and sreasons(r) == {"unchanged"}
    later = time.time() + 10
    os.utime(experiment.parent / "de" / "stress_vs_control.csv", (later, later))
    r = build_bundle(load_config(experiment), log=quiet)
    assert creasons(r)["stress_vs_control"] == "table changed" and creasons(r)["markers"] == "unchanged" and sreasons(r) == {"unchanged"}
    os.utime(experiment.parent / "de" / "by_cluster" / "pb_Astro.csv", (later, later))  # one file of a {level} template
    r = build_bundle(load_config(experiment), log=quiet)
    assert creasons(r)["stress_by_cluster"] == "table changed" and creasons(r)["stress_vs_control"] == "unchanged"
    doc = yaml.safe_load(experiment.read_text())
    doc["comparisons"][0]["groups"] = ["stress", "control"]  # a setting: rebuilt, samples untouched
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    assert creasons(r)["stress_vs_control"] == "settings changed" and r.manifest.comparisons[0].groups == ["stress", "control"]
    doc["comparisons"][0]["name"] = "Renamed"  # a label: applied without a rebuild
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    assert creasons(r)["stress_vs_control"] == "unchanged" and r.manifest.comparisons[0].name == "Renamed"
    os.utime(experiment.parent / "sampleA.h5ad", (later, later))  # a sample: the comparison follows, its genes and links may have moved
    r = build_bundle(load_config(experiment), log=quiet)
    assert set(creasons(r).values()) == {"samples changed"}
    doc["comparisons"] = []
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    assert sorted(r.plan.removed_comparisons) == ["markers", "stress_by_cluster", "stress_vs_control"] and not (r.out / "comparisons" / "stress_vs_control").exists() and r.manifest.comparisons == []


def test_dry_run_lists_comparison_actions(experiment):
    lines: list[str] = []
    build_bundle(load_config(experiment), dry_run=True, log=lines.append)
    assert any(line.strip().startswith("comparison stress_vs_control") and "new" in line for line in lines)


@pytest.mark.parametrize(
    "frame, expect",
    [
        (pd.DataFrame({"gene": ["A"], "baseMean": [1.0], "log2FoldChange": [0.5], "pvalue": [0.1], "padj": [0.2]}), {"gene": "gene", "effect": "log2FoldChange", "p": "pvalue", "padj": "padj", "mean": "baseMean"}),  # DESeq2 / pyDESeq2
        (pd.DataFrame({"Unnamed: 0": ["A"], "logFC": [0.5], "AveExpr": [1.0], "t": [2.0], "P.Value": [0.1], "adj.P.Val": [0.2], "B": [0.3]}), {"gene": "Unnamed: 0", "effect": "logFC", "p": "P.Value", "padj": "adj.P.Val", "mean": "AveExpr"}),  # limma topTable through write.csv
        (pd.DataFrame({"genes": ["A"], "logFC": [0.5], "logCPM": [1.0], "PValue": [0.1], "FDR": [0.2]}), {"gene": "genes", "effect": "logFC", "p": "PValue", "padj": "FDR", "mean": "logCPM"}),  # edgeR topTags
        (pd.DataFrame({"X": ["A"], "p_val": [0.1], "avg_log2FC": [0.5], "pct.1": [0.3], "pct.2": [0.1], "p_val_adj": [0.2]}), {"gene": "X", "effect": "avg_log2FC", "p": "p_val", "padj": "p_val_adj"}),  # Seurat FindMarkers
        (pd.DataFrame({"names": ["A"], "scores": [2.0], "logfoldchanges": [0.5], "pvals": [0.1], "pvals_adj": [0.2]}), {"gene": "names", "effect": "logfoldchanges", "p": "pvals", "padj": "pvals_adj", "score": "scores"}),  # scanpy rank_genes_groups
        (pd.DataFrame({"p.value": [0.1, 0.3], "FDR": [0.2, 0.4], "summary.logFC": [1.0, -0.5], "mean_logFC": [0.9, -0.4], "gene": ["A", "A"], "group": ["ITC_1", "ITC_2"]}), {"gene": "gene", "effect": "summary.logFC", "p": "p.value", "padj": "FDR", "facet": "group"}),  # scran findMarkers as a data frame
        (pd.DataFrame({"feature": ["A", "A"], "group": ["c1", "c2"], "avgExpr": [1.0, 0.2], "logFC": [0.5, -0.5], "statistic": [3.0, -3.0], "auc": [0.7, 0.3], "pval": [0.1, 0.1], "padj": [0.2, 0.2], "pct_in": [50.0, 10.0], "pct_out": [10.0, 50.0]}), {"gene": "feature", "effect": "logFC", "p": "pval", "padj": "padj", "mean": "avgExpr", "score": "statistic", "pct_in": "pct_in", "pct_out": "pct_out", "facet": "group"}),  # presto wilcoxauc
    ],
)
def test_result_columns_are_recognised_per_tool(tmp_path, frame, expect):
    p = tmp_path / "res.csv"
    frame.to_csv(p, index=False)
    loaded = load_tables(ComparisonSpec(id="c", results=p))
    assert {k: v for k, v in loaded.columns.items() if k in expect} == expect
    assert list(loaded.results.columns)[:2] == ["gene", "effect"] and list(loaded.results.columns)[-1] == "level"


def test_column_overrides_and_clear_errors(tmp_path):
    p = tmp_path / "res.tsv"
    pd.DataFrame({"id": ["A", "B"], "lfc": [1.0, -1.0], "q": [0.01, 0.5]}).to_csv(p, sep="\t", index=False)
    with pytest.raises(ValueError, match="no effect column"):
        load_tables(ComparisonSpec(id="c", results=p))
    loaded = load_tables(ComparisonSpec(id="c", results=p, columns={"results": {"effect": "lfc", "padj": "q", "gene": "id"}}))
    assert loaded.results["gene"].tolist() == ["A", "B"] and loaded.columns["padj"] == "q" and "p" not in loaded.results
    with pytest.raises(KeyError, match="column 'nope' \\(for effect\\)"):
        load_tables(ComparisonSpec(id="c", results=p, columns={"results": {"effect": "nope"}}))
    with pytest.raises(Exception, match="unknown role"):
        ComparisonSpec(id="c", results=p, columns={"results": {"fold": "lfc"}})
    assert read_table(p).shape == (2, 3)  # a .tsv is read as tab-separated


def test_the_gene_column_that_matches_the_bundle_wins(tmp_path):
    p = tmp_path / "res.csv"
    pd.DataFrame({"gene_id": ["ENSG1", "ENSG2"], "symbol": ["GAD1", "GAD2"], "log2FoldChange": [1.0, 2.0], "pvalue": [0.1, 0.2], "padj": [0.2, 0.3]}).to_csv(p, index=False)
    by_default = load_tables(ComparisonSpec(id="c", results=p))
    assert by_default.columns["gene"] == "symbol"  # the recognised order: gene, gene_name, symbol, ... before gene_id
    ids = load_tables(ComparisonSpec(id="c", results=p), union={"ENSG1", "ENSG2"})
    assert ids.columns["gene"] == "gene_id" and ids.notes and "match the bundle" in ids.notes[0]
    forced = load_tables(ComparisonSpec(id="c", results=p, columns={"results": {"gene": "symbol"}}), union={"ENSG1"})
    assert forced.columns["gene"] == "symbol"


def _sample(sid: str, meta: dict[str, str]) -> Sample:
    return Sample(id=sid, name=sid, platform="visium", nObs=1, nGenes=1, bbox=(0, 0, 1, 1), pointRadius=1, meta=meta)


def test_replicates_link_through_meta_and_groups_come_from_the_split_key(tmp_path):
    samples = [_sample("s1", {"mouse": "m1", "condition": "ctl"}), _sample("s1b", {"mouse": "m1", "condition": "ctl"}), _sample("s2", {"mouse": "m2", "condition": "stress"}), _sample("m3", {"condition": "stress"})]
    meta = [MetaKey(id="mouse", name="Mouse", levels=["m1", "m2"]), MetaKey(id="condition", name="Condition", levels=["ctl", "stress"])]
    key, linked = link_replicates(["m1", "m2", "m3", "m9"], samples, None, meta)
    assert key == "mouse" and linked == {"m1": ["s1", "s1b"], "m2": ["s2"], "m3": ["m3"], "m9": []}  # two sections of one mouse; a sample id as last resort
    assert find_split_key(["ctl", "stress"], meta) == "condition" and find_split_key(["a"], meta) is None
    res = tmp_path / "res.csv"
    pd.DataFrame({"gene": ["A"], "log2FoldChange": [1.0], "pvalue": [0.1], "padj": [0.2]}).to_csv(res, index=False)
    pb = tmp_path / "pb.csv"
    pd.DataFrame({"gene": ["A"], "m1": [1.0], "m2": [2.0]}).to_csv(pb, index=False)
    spec = ComparisonSpec(id="c", results=res, pseudobulk=pb)  # no replicate sheet, no groups, no split: all inferred
    rc = resolve_comparison(spec, load_tables(spec), samples, meta)
    assert rc.groups == ["ctl", "stress"] and rc.split == "condition" and rc.link == "mouse"
    assert [(r["id"], r["group"], r["samples"]) for r in rc.replicates] == [("m1", "ctl", ["s1", "s1b"]), ("m2", "stress", ["s2"])]
    pd.DataFrame({"gene": ["A"], "m1": [1.0], "m2": [2.0], "m9": [3.0]}).to_csv(pb, index=False)
    with pytest.raises(ValueError, match="cannot tell which group replicate 'm9' belongs to"):
        resolve_comparison(spec, load_tables(spec), samples, meta)
    with pytest.raises(ValueError, match="not in `groups"):
        spec2 = ComparisonSpec(id="c", results=res, pseudobulk=tmp_path / "pb.csv", groups=["ctl"])
        pd.DataFrame({"gene": ["A"], "m1": [1.0], "m2": [2.0]}).to_csv(pb, index=False)
        resolve_comparison(spec2, load_tables(spec2), samples, meta)


def test_map_columns_is_case_insensitive_and_never_reuses_a_column():
    df = pd.DataFrame({"Gene": ["A"], "LOGFC": [1.0], "PVALUE": [0.1]})
    cols = map_columns(df, RESULT_ROLES, {}, what="t")
    assert cols == {"gene": "Gene", "effect": "LOGFC", "p": "PVALUE"}


def test_init_writes_a_comparison_entry_from_a_results_table(experiment, tmp_path):
    src = experiment.parent
    out = tmp_path / "demo.yaml"
    r = runner.invoke(app, ["init", str(src / "*.h5ad"), str(src / "de" / "stress_vs_control.csv"), "--platform", "visium", "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "comparison stress_vs_control: gene <- gene, effect <- log2FoldChange, p <- pvalue, padj <- padj, mean <- baseMean; 12 rows" in r.output
    assert "groups: control, stress (from the file name" in r.output
    text = out.read_text()
    doc = yaml.safe_load(text)
    [c] = doc["comparisons"]
    assert c == {"id": "stress_vs_control", "name": "Stress vs control", "results": str(Path(os.path.relpath(src / "de" / "stress_vs_control.csv", tmp_path))), "groups": ["control", "stress"]}
    assert "facet:" not in text and "kind:" not in text  # a plain two-group table
    assert "# pseudobulk:" in text and "# split: condition" in text
    res = build_bundle(load_config(out), log=quiet)  # builds as written: a table and groups, no replicate values yet
    assert res.problems == [] and res.manifest.comparisons[0].nReplicates == 0 and not res.manifest.comparisons[0].hasPseudobulk
    r = runner.invoke(app, ["init", str(src / "de" / "mice.csv"), "--id", "x", "-o", str(tmp_path / "x.yaml")])
    assert r.exit_code != 0 and "does not look like a results table" in str(r.exception)


def test_marker_table_becomes_one_level_per_cluster(experiment):
    r = build_bundle(load_config(experiment), log=quiet)
    assert r.problems == [] and validate_local(r.out) == []
    c = next(x for x in r.manifest.comparisons if x.id == "markers")
    assert c.kind == "markers" and c.groups == [] and c.split is None and c.nReplicates == 0 and not c.hasPseudobulk
    assert c.facet is not None and c.facet.column == "cluster" and c.facet.field == "cluster"  # the levels are the categories of the `cluster` annotation
    assert (c.hasEffect, c.hasP, c.hasPadj, c.hasPct) == (True, True, True, True)
    names = [lv.name for lv in c.levels]
    assert len(names) >= 3 and all(n in ("Astro", "Excit_L2", "Excit_L5", "Inhib_PV", "Oligo", "Micro") for n in names)
    for lv in c.levels:
        assert lv.population is not None and lv.population.field == "cluster" and lv.population.value == lv.name
        res = json.loads((r.out / c.path / lv.path / "results.json").read_text())
        assert len(res["genes"]) == lv.nGenes == 5 and len(res["pct_in"]) == 5 and res["effect"][0] >= res["effect"][-1]  # sorted: the strongest first
    assert c.nGenes == sum(lv.nGenes for lv in c.levels)
    doc = json.loads((r.out / c.path / "comparison.json").read_text())
    assert doc["columns"]["facet"] == "cluster" and doc["columns"]["pct_in"] == "pct.1" and doc["replicates"] == {lv.id: [] for lv in c.levels}


def test_one_file_per_level_with_its_own_pseudobulk(experiment):
    r = build_bundle(load_config(experiment), log=quiet)
    c = next(x for x in r.manifest.comparisons if x.id == "stress_by_cluster")
    assert c.kind == "contrast" and c.groups == ["control", "stress"] and c.split == "condition" and c.facet.column == "{level}" and c.facet.field == "cluster"
    assert [lv.name for lv in c.levels] == ["Astro", "Excit_L2"] and all(lv.hasPseudobulk and lv.nReplicates == 4 for lv in c.levels)
    for lv in c.levels:
        pb = zarr.open_array(str(r.out / c.path / lv.path / "pseudobulk.zarr"), mode="r")
        assert pb.shape == (lv.nGenes, 4) and lv.population.value == lv.name
    assert c.nReplicates == 4  # the same four mice in every level


def test_a_ranked_list_without_statistics_keeps_its_order(experiment, tmp_path):
    p = tmp_path / "Supplementary_markers.csv"
    pd.DataFrame({"cluster": ["BM", "BM", "BM", "AI", "AI"], "gene": ["G005", "G001", "G009", "G002", "G003"]}).to_csv(p, index=False)
    spec = ComparisonSpec(id="paper", kind="markers", results=p)
    loaded = load_tables(spec)
    assert "effect" not in loaded.results and loaded.levels == ["BM", "AI"] and loaded.columns == {"gene": "gene", "facet": "cluster"}
    assert loaded.results["gene"].tolist() == ["G005", "G001", "G009", "G002", "G003"]  # the file's own order is the rank
    doc = yaml.safe_load(experiment.read_text())
    doc["comparisons"] = [{"id": "paper", "kind": "markers", "results": str(p)}]
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    c = r.manifest.comparisons[0]
    assert not c.hasEffect and not c.hasP and c.facet.field is None and [lv.name for lv in c.levels] == ["BM", "AI"]  # BM / AI are no categories of the data
    assert validate_local(r.out) == []
    with pytest.raises(ValueError, match="needs a column that says which cluster"):
        q = tmp_path / "flat.csv"
        pd.DataFrame({"gene": ["G001"], "avg_log2FC": [1.0], "p_val_adj": [0.1]}).to_csv(q, index=False)
        load_tables(ComparisonSpec(id="x", kind="markers", results=q))


def test_init_recognises_marker_tables(experiment, tmp_path):
    src = experiment.parent
    out = tmp_path / "m.yaml"
    r = runner.invoke(app, ["init", str(src / "*.h5ad"), str(src / "de" / "markers.csv"), "--platform", "visium", "--id", "m", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "markers markers: gene <- gene, effect <- avg_log2FC, p <- p_val, padj <- p_val_adj, pct_in <- pct.1, pct_out <- pct.2" in r.output
    assert "levels: " in r.output and "of 'cluster', each against the rest" in r.output
    text = out.read_text()
    [c] = yaml.safe_load(text)["comparisons"]
    assert c["kind"] == "markers" and c["facet"] == {"column": "cluster"} and "groups" not in c
    res = build_bundle(load_config(out), log=quiet)
    assert res.problems == [] and res.manifest.comparisons[0].kind == "markers" and len(res.manifest.comparisons[0].levels) >= 3
    lst = tmp_path / "paper_markers.csv"
    pd.DataFrame({"cluster": ["BM", "AI"], "gene": ["G005", "G002"]}).to_csv(lst, index=False)
    r = runner.invoke(app, ["init", str(src / "*.h5ad"), str(lst), "--platform", "visium", "--id", "m2", "-o", str(tmp_path / "m2.yaml")])
    assert r.exit_code == 0 and "a ranked list" in r.output and "kind: markers" in (tmp_path / "m2.yaml").read_text(), r.output
