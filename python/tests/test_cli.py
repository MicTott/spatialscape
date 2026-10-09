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


def test_init_on_a_folder_of_h5ad_files_gives_unique_ids(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "src" / "*.h5ad"), "--platform", "visium", "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    doc = yaml.safe_load(out.read_text())
    assert doc["samples"][0]["id"] == "vis_{stem}"
    cfg = load_config(out)
    assert sorted(s.id for s in cfg.samples) == ["vis_sampleA", "vis_sampleB"]
    assert cfg.samples[0].name.endswith("(Visium)")


def test_init_keeps_folder_names_for_store_per_folder_layouts(tmp_path):
    for d in ("Br1", "Br2"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "adata.h5ad").write_bytes(b"")
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "*" / "adata.h5ad"), "--platform", "xenium", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert yaml.safe_load(out.read_text())["samples"][0]["id"] == "xen_{name}"


def test_init_for_snrnaseq_sets_embedding_defaults(tmp_path):
    out = tmp_path / "dataset.yaml"
    r = runner.invoke(app, ["init", str(tmp_path / "nothing" / "*.h5ad"), "--platform", "snrnaseq", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "matches nothing" in r.output
    assert yaml.safe_load(out.read_text())["platforms"]["snrnaseq"]["kind"] == "embedding"


def test_inspect_runs_on_synthetic_data(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=40, n_genes=5)
    r = runner.invoke(app, ["inspect", str(tmp_path / "src" / "sampleA.h5ad")])
    assert r.exit_code == 0, r.output
    assert "cluster" in r.output and "layers:" in r.output and "obsm:" in r.output


def test_plan_and_errors_are_one_readable_line(tmp_path, capsys, monkeypatch):
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
        main(["plan", str(cfg)])
    err = capsys.readouterr().err
    assert ex.value.code == 1 and "could not be parsed" in err
    # schema error
    cfg.write_text("id: x\nname: x\nsamples:\n  - id: a\n    platform: nope\n    path: a.h5ad\n")
    with pytest.raises(SystemExit) as ex:
        main(["plan", str(cfg)])
    err = capsys.readouterr().err
    assert ex.value.code == 1 and "not valid" in err and "platform" in err
    # missing file
    with pytest.raises(SystemExit) as ex:
        main(["plan", str(tmp_path / "missing.yaml")])
    assert ex.value.code == 1 and "file not found" in capsys.readouterr().err


def test_help_and_usage_errors_still_work(capsys):
    main(["--help"])  # help prints and returns (exit status 0)
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)  # CI runners force colors
    assert "Usage: spatialscape" in out and "build" in out
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
