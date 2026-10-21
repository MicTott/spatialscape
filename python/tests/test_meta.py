"""Sample metadata: `meta` on samples, the manifest's key declarations, the rebuild rule, and what `init` proposes."""
from __future__ import annotations

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from spatialscape.build import build_bundle
from spatialscape.cli import app
from spatialscape.config import load_config
from spatialscape.init import constant_columns
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local

runner = CliRunner()


def quiet(*_):
    pass


def reasons(res) -> dict[str, str]:
    return {a.spec.id: a.reason for a in res.plan.actions}


@pytest.fixture
def experiment(tmp_path):
    return make_synthetic(tmp_path / "src", n_cells=120, n_genes=6, comparisons=True)


def test_synthetic_experiment_builds_with_metadata(experiment):
    r = build_bundle(load_config(experiment), log=quiet)
    assert r.problems == [] and validate_local(r.out) == []
    m = r.manifest
    assert [(k.id, k.name, k.levels) for k in m.meta] == [("condition", "Condition", ["control", "stress"]), ("mouse", "Mouse", ["m1", "m2", "m3", "m4"])]
    by = {s.id: s.meta for s in m.samples}
    assert by["sampleA"] == {"condition": "control", "mouse": "m1"} and by["sampleD"] == {"condition": "stress", "mouse": "m4"}
    assert by["umapA"] == {}  # the pooled embedding carries no group
    assert [s.id for s in m.samples][:4] == ["sampleA", "sampleB", "sampleC", "sampleD"]


def test_yaml_values_apply_without_a_rebuild_and_column_values_rebuild(experiment):
    build_bundle(load_config(experiment), log=quiet)
    doc = yaml.safe_load(experiment.read_text())
    a = next(s for s in doc["samples"] if s["id"] == "sampleA")
    a["meta"]["mouse"] = "m9"  # typed in the yaml: manifest only
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    assert set(reasons(r).values()) == {"unchanged"}
    assert next(s for s in r.manifest.samples if s.id == "sampleA").meta == {"condition": "control", "mouse": "m9"}
    assert next(k for k in r.manifest.meta if k.id == "mouse").levels == ["m9", "m2", "m3", "m4"]
    a["meta"]["condition"] = {"column": "sample_id"}  # read from a column: that sample is rebuilt
    experiment.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(experiment), log=quiet)
    assert reasons(r)["sampleA"] == "settings changed" and reasons(r)["sampleB"] == "unchanged"
    assert next(s for s in r.manifest.samples if s.id == "sampleA").meta["condition"] == "sampleA"
    assert next(k for k in r.manifest.meta if k.id == "condition").levels == ["control", "stress", "sampleA"]  # declared order first, new values appended


def test_a_meta_column_with_several_values_is_refused(experiment):
    doc = yaml.safe_load(experiment.read_text())
    doc["samples"][0]["meta"] = {"cl": {"column": "cluster"}}
    experiment.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match=r"meta column 'cluster' \(key cl\) holds \d+ values .*subset: \{ column: cluster"):
        build_bundle(load_config(experiment), log=quiet)
    doc["samples"][0]["meta"] = {"1x": "a"}
    experiment.write_text(yaml.safe_dump(doc))
    with pytest.raises(Exception, match="meta key '1x'"):
        load_config(experiment)
    doc["samples"][0]["meta"] = {}
    doc["meta"] = [{"id": "condition"}, {"id": "condition"}]
    experiment.write_text(yaml.safe_dump(doc))
    with pytest.raises(Exception, match="meta key ids must be unique"):
        load_config(experiment)


def test_init_proposes_meta_for_columns_constant_within_a_sample(experiment, tmp_path):
    out = tmp_path / "demo.yaml"
    r = runner.invoke(app, ["init", str(experiment.parent / "*.h5ad"), "--platform", "visium", "--id", "demo", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert "sample metadata: condition look constant within each sample; listed as a `# meta:` line" in r.output
    text = out.read_text()
    assert "# meta: { condition: { column: condition } }" in text and "#   condition: one value in this file: control" in text
    assert "# meta:\n#   - { id: condition, name: Condition }" in text
    assert yaml.safe_load(text)["samples"][0]["fields"] == {"domain": "cluster", "total_counts": "total_counts"}  # a sample property is not an annotation


def test_constant_columns_in_a_pooled_object():
    obs = pd.DataFrame(
        {
            "sample_id": ["a", "a", "b", "b", "c", "c"],
            "condition": ["ctl", "ctl", "stress", "stress", "ctl", "ctl"],
            "sex": pd.Categorical(["F", "F", "M", "M", "F", "F"]),
            "label": ["x", "y", "x", "y", "x", "y"],  # varies within a sample: an annotation
            "batch": ["1", "1", "1", "1", "1", "1"],  # one value everywhere: nothing to split by
            "in_tissue": [1, 1, 1, 1, 1, 1],
        }
    )
    assert constant_columns(obs, "sample_id") == [("condition", "constant within each sample: ctl, stress"), ("sex", "constant within each sample: F, M")]
    assert constant_columns(obs.iloc[:2], None) == [("condition", "one value in this file: ctl"), ("sex", "one value in this file: F"), ("batch", "one value in this file: 1")]
