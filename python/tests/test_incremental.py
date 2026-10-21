"""`build` is incremental: unchanged samples are kept, changed ones rebuilt, dropped ones deleted."""
from __future__ import annotations

import json
import os
import time

import pytest
import yaml
import zarr

from spatialscape.build import build_bundle
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic


def quiet(*_):
    pass


def reasons(res) -> dict[str, str]:
    return {a.spec.id: a.reason for a in res.plan.actions}


@pytest.fixture
def project(tmp_path):
    return make_synthetic(tmp_path / "src", n_cells=150, n_genes=8)


def test_first_build_writes_sidecars_and_a_rebuild_changes_nothing(project):
    r1 = build_bundle(load_config(project), log=quiet)
    assert r1.problems == [] and set(reasons(r1).values()) == {"new"}
    assert r1.out == project.parent / "bundles" / "synthetic"  # default output: next to the yaml
    assert (r1.out / "samples" / "sampleA" / "build.json").exists()
    m1 = json.loads((r1.out / "manifest.json").read_text())
    r2 = build_bundle(load_config(project), log=quiet)
    assert set(reasons(r2).values()) == {"unchanged"}
    assert json.loads((r1.out / "manifest.json").read_text()) == m1


def test_touched_source_rebuilds_only_that_sample(project):
    build_bundle(load_config(project), log=quiet)
    later = time.time() + 10
    os.utime(project.parent / "sampleB.h5ad", (later, later))
    r = build_bundle(load_config(project), log=quiet)
    assert reasons(r) == {"sampleA": "unchanged", "sampleB": "source changed", "umapA": "unchanged"}
    assert r.problems == []


def test_changed_mapping_rebuilds_that_sample_and_keeps_codes(project):
    r1 = build_bundle(load_config(project), log=quiet)
    cats = list(r1.manifest.vocabularies["cluster"].categories)
    codes_a = zarr.open_group(str(r1.out / "samples/sampleA/obs.zarr"), mode="r")["cat"]["cluster"][:]
    doc = yaml.safe_load(project.read_text())
    doc["samples"][1]["fields"] = {"cluster": "cluster"}  # sampleB drops total_counts
    project.write_text(yaml.safe_dump(doc))
    r2 = build_bundle(load_config(project), log=quiet)
    assert reasons(r2) == {"sampleA": "unchanged", "sampleB": "settings changed", "umapA": "unchanged"}
    assert list(r2.manifest.vocabularies["cluster"].categories) == cats
    assert next(s for s in r2.manifest.samples if s.id == "sampleB").fields == ["cluster"]
    assert (zarr.open_group(str(r2.out / "samples/sampleA/obs.zarr"), mode="r")["cat"]["cluster"][:] == codes_a).all()
    assert r2.problems == []


def test_names_palette_and_defaults_apply_without_rebuilding(project, tmp_path):
    r1 = build_bundle(load_config(project), log=quiet)
    v1 = r1.manifest.vocabularies["cluster"]
    pal = tmp_path / "palette.json"
    pal.write_text(json.dumps({"cluster": {"Astro": "#123456", "Oligo": "#abcdef"}}))
    doc = yaml.safe_load(project.read_text())
    doc.update({"palette": str(pal), "name": "Renamed", "default_gene": "G003"})
    doc["samples"][0]["name"] = "First section"
    doc["fields"][0]["name"] = "Cluster label"
    project.write_text(yaml.safe_dump(doc))
    r2 = build_bundle(load_config(project), log=quiet)
    assert set(reasons(r2).values()) == {"unchanged"}
    v2 = r2.manifest.vocabularies["cluster"]
    assert v2.categories == v1.categories
    assert v2.colors[v2.categories.index("Astro")] == "#123456" and v2.colors[v2.categories.index("Oligo")] == "#abcdef"
    other = next(c for c in v1.categories if c not in ("Astro", "Oligo", "NA"))
    assert v2.colors[v2.categories.index(other)] == v1.colors[v1.categories.index(other)]
    assert r2.manifest.name == "Renamed" and r2.manifest.defaultGene == "G003"
    assert r2.manifest.samples[0].name == "First section" and r2.manifest.field_by_id("cluster").name == "Cluster label"


def test_declaration_change_rebuilds_the_samples_that_carry_the_field(project):
    build_bundle(load_config(project), log=quiet)
    doc = yaml.safe_load(project.read_text())
    doc["fields"][0]["aliases"] = {"Astro": "Astrocyte"}
    project.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(project), log=quiet)
    assert set(reasons(r).values()) == {"field declarations changed"}  # every sample carries `cluster`
    assert "Astrocyte" in r.manifest.vocabularies["cluster"].categories and r.problems == []


def test_removed_sample_is_deleted(project):
    r1 = build_bundle(load_config(project), log=quiet)
    doc = yaml.safe_load(project.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] != "umapA"]
    project.write_text(yaml.safe_dump(doc))
    r2 = build_bundle(load_config(project), log=quiet)
    assert r2.plan.removed == ["umapA"] and not (r1.out / "samples" / "umapA").exists()
    assert [s.id for s in r2.manifest.samples] == ["sampleA", "sampleB"] and r2.problems == []


def test_force_and_shard_settings(project):
    build_bundle(load_config(project), log=quiet)
    r = build_bundle(load_config(project), force=True, log=quiet)
    assert set(reasons(r).values()) == {"forced"}
    r = build_bundle(load_config(project), sharded=False, log=quiet)
    assert set(reasons(r).values()) == {"sharding changed"}
    assert all(not s.expr.sharded for s in r.manifest.samples)


def test_dry_run_writes_nothing(project):
    r = build_bundle(load_config(project), dry_run=True, log=quiet)
    assert r.manifest is None and not r.out.exists() and set(reasons(r).values()) == {"new"}


def test_bundle_without_sidecars_is_rebuilt_once(project):
    r1 = build_bundle(load_config(project), log=quiet)
    for a in r1.plan.actions:
        (r1.out / "samples" / a.spec.id / "build.json").unlink()
    r2 = build_bundle(load_config(project), log=quiet)
    assert set(reasons(r2).values()) == {"new"}
    r3 = build_bundle(load_config(project), log=quiet)
    assert set(reasons(r3).values()) == {"unchanged"}
