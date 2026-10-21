"""CLI behaviour a new user meets in the first ten minutes."""
from __future__ import annotations

import re

import pytest
import yaml
from typer.testing import CliRunner

from spatialscape.cli import app, main
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic

runner = CliRunner()


def test_version_flag():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0 and r.stdout.startswith("spatialscape ")


def test_init_on_a_folder_of_h5ad_files_writes_a_menu_that_builds(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "*.h5ad"), "--platform", "visium", "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    doc = yaml.safe_load(out.read_text())
    s = doc["samples"][0]
    assert s["id"] == "vis_{stem}" and s["platform"] == "visium"
    assert s["fields"] == {"domain": "cluster", "total_counts": "total_counts"}  # the menu maps what looks like a domain and a QC metric
    assert doc["default_color"] == {"field": "domain"}
    assert [f["id"] for f in doc["fields"]] == ["domain", "total_counts"]
    text = out.read_text()
    assert "# default_gene:" in text and "# palette:" in text and "guide/changes" in text  # the yaml explains its own knobs
    assert "# not listed: sample_id" in text
    cfg = load_config(out)
    assert sorted(x.id for x in cfg.samples) == ["vis_sampleA", "vis_sampleB"]
    assert cfg.samples[0].name.endswith("(Visium)")
    r = runner.invoke(app, ["build", str(out), "-q"])  # builds as written, into bundles/<id> next to the yaml
    assert r.exit_code == 0, r.output
    assert (tmp_path / "bundles" / "demo" / "manifest.json").exists()


def test_init_keeps_folder_names_for_store_per_folder_layouts(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=30, n_genes=5)
    for d, f in (("Br1", "sampleA"), ("Br2", "sampleB")):
        (tmp_path / d).mkdir()
        (tmp_path / "src" / f"{f}.h5ad").rename(tmp_path / d / "adata.h5ad")
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "*" / "adata.h5ad"), "--platform", "xenium", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert yaml.safe_load(out.read_text())["samples"][0]["id"] == "xen_{name}"
    assert [s.id for s in load_config(out).samples] == ["xen_Br1", "xen_Br2"]


def test_init_for_snrnaseq_sets_embedding_defaults(tmp_path):
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "nothing" / "*.h5ad"), "--platform", "snrnaseq", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "matches nothing" in r.output
    s = yaml.safe_load(out.read_text())["samples"][0]
    assert s["platform"] == "snrnaseq" and s["kind"] == "embedding" and s["coords"] == "obsm/X_umap"


def test_init_defaults_output_and_id_from_the_first_path(tmp_path, monkeypatch):
    make_synthetic(tmp_path / "data" / "visium", n_cells=30, n_genes=5)
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["init", "data/visium/*.h5ad"])
    assert r.exit_code == 0, r.output
    doc = yaml.safe_load((tmp_path / "visium.yaml").read_text())
    assert doc["id"] == "visium" and doc["name"] == "Visium" and doc["samples"][0]["glob"] == "data/visium/*.h5ad"
    assert "next: edit visium.yaml" in r.output and "spatialscape build visium.yaml" in r.output


def test_inspect_runs_on_synthetic_data(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=40, n_genes=5)
    r = runner.invoke(app, ["inspect", str(tmp_path / "src" / "sampleA.h5ad")])
    assert r.exit_code == 0, r.output
    assert "cluster" in r.output and "layers:" in r.output and "obsm:" in r.output


def test_errors_are_one_readable_line(tmp_path, capsys, monkeypatch):
    cfg = make_synthetic(tmp_path / "src", n_cells=40, n_genes=5)
    doc = yaml.safe_load(cfg.read_text())
    doc["samples"][0]["fields"]["cluster"] = "clustr"
    cfg.write_text(yaml.safe_dump(doc))
    monkeypatch.delenv("SPATIALSCAPE_DEBUG", raising=False)
    with pytest.raises(SystemExit) as ex:
        main(["build", str(cfg), "-o", str(tmp_path / "b")])
    assert ex.value.code == 1
    err = capsys.readouterr().err
    assert "error:" in err and "clustr" in err and "Traceback" not in err
    # yaml syntax error
    cfg.write_text("id: x\nname: [unclosed\n")
    with pytest.raises(SystemExit) as ex:
        main(["build", str(cfg), "--dry-run"])
    err = capsys.readouterr().err
    assert ex.value.code == 1 and "could not be parsed" in err
    # schema error
    cfg.write_text("id: x\nname: x\nsamples:\n  - id: a\n    platform: nope\n    path: a.h5ad\n")
    with pytest.raises(SystemExit) as ex:
        main(["build", str(cfg), "--dry-run"])
    err = capsys.readouterr().err
    assert ex.value.code == 1 and "not valid" in err and "platform" in err
    # missing file
    with pytest.raises(SystemExit) as ex:
        main(["build", str(tmp_path / "missing.yaml"), "--dry-run"])
    assert ex.value.code == 1 and "file not found" in capsys.readouterr().err


def test_help_lists_the_current_commands_only(capsys):
    main(["--help"])  # help prints and returns (exit status 0)
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)  # CI runners force colors
    assert "Usage: spatialscape" in out
    for cmd in ("init", "inspect", "build", "serve", "site", "validate", "outlines", "thumbnails", "synth"):
        assert re.search(rf"\b{cmd}\b", out), cmd
    for gone in ("convert", "refresh", "add-sample", "plan"):
        assert not re.search(rf"\b{gone}\b", out), gone
    with pytest.raises(SystemExit) as ex:
        main(["build", "--no-such-flag"])
    assert ex.value.code == 2


def test_init_stores_paths_relative_to_the_yaml(tmp_path, monkeypatch):
    make_synthetic(tmp_path / "data", n_cells=30, n_genes=5)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "config" / "dataset.yaml"  # a yaml in a subfolder, glob typed relative to the shell
    r = runner.invoke(app, ["init", "data/*.h5ad", "--platform", "visium", "--id", "d", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert yaml.safe_load(out.read_text())["samples"][0]["glob"] == "../data/*.h5ad"
    assert len(load_config(out).samples) == 2


def test_build_dry_run_writes_nothing(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=40, n_genes=5)
    r = runner.invoke(app, ["build", str(cfg), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "dry run: nothing written" in r.output and "build  new" in r.output
    assert not (tmp_path / "src" / "bundles").exists()


def test_build_reports_what_changed_and_the_next_step(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=40, n_genes=5)
    r = runner.invoke(app, ["build", str(cfg), "-q"])
    assert r.exit_code == 0, r.output
    assert "3 samples (3 built)" in r.output and "next: spatialscape serve" in r.output
    r = runner.invoke(app, ["build", str(cfg), "-q"])
    assert r.exit_code == 0, r.output
    assert "(0 built, 3 unchanged)" in r.output


def test_commands_exit_nonzero_when_they_report_problems(tmp_path, capsys):
    """Typer runs outside standalone mode and returns a command's exit status; main() must pass it on."""
    with pytest.raises(SystemExit) as ex:
        main(["validate", str(tmp_path / "not-a-bundle")])
    assert ex.value.code == 1
    assert "manifest.json" in capsys.readouterr().out
    cfg = make_synthetic(tmp_path / "src", n_cells=30, n_genes=4)
    main(["build", str(cfg), "-o", str(tmp_path / "b"), "-q"])  # a clean build and a clean validate return normally
    main(["validate", str(tmp_path / "b")])
    assert "ok" in capsys.readouterr().out
