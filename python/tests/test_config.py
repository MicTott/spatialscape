from pathlib import Path

import numpy as np
import pytest
import yaml

from spatialscape.config import load_config
from spatialscape.discover import auto_fields, field_id, infer_field_spec
from spatialscape.synthetic import make_synthetic


def test_glob_templates_and_platform_defaults(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=60, n_genes=5)
    (tmp_path / "src" / "d1").mkdir()
    (tmp_path / "src" / "d2").mkdir()
    (tmp_path / "src" / "sampleA.h5ad").rename(tmp_path / "src" / "d1" / "adata.h5ad")
    (tmp_path / "src" / "sampleB.h5ad").rename(tmp_path / "src" / "d2" / "adata.h5ad")
    doc = {
        "id": "t",
        "name": "t",
        "defaults": {"expression": {"normalized": "lognorm"}},
        "platforms": {"visium": {"fields": {"cluster": "cluster"}, "images": []}},
        "samples": [{"glob": "*/adata.h5ad", "platform": "visium", "id": "vis_{name}", "name": "{name} (Visium)", "group": "{name}"}],
    }
    p = tmp_path / "src" / "dataset.yaml"
    p.write_text(yaml.safe_dump(doc))
    cfg = load_config(p)
    assert [s.id for s in cfg.samples] == ["vis_d1", "vis_d2"]
    assert cfg.samples[0].name == "d1 (Visium)" and cfg.samples[0].group == "d1"
    assert cfg.samples[0].fields == {"cluster": "cluster"}  # from the platform block
    assert cfg.samples[1].expression.normalized == "lognorm"  # from defaults
    assert cfg.samples[0].path == (tmp_path / "src" / "d1" / "adata.h5ad").resolve()
    # undeclared field is allowed: it is declared automatically at build time
    assert cfg.field_spec("cluster") is None


def test_auto_fields_and_inference(small_adata, tmp_path):
    from spatialscape.config import SampleSpec

    spec = SampleSpec(id="s", platform="visium", path=tmp_path, fields="auto")
    small_adata.obs["sample_id"] = "x"
    small_adata.obs["total_counts"] = np.arange(small_adata.n_obs)
    small_adata.obs["random_float"] = np.random.default_rng(0).random(small_adata.n_obs)
    f = auto_fields(small_adata, spec)
    assert f == {"cluster": "cluster", "score": "score", "total_counts": "total_counts"}  # sample_id and random_float are skipped
    assert infer_field_spec("cluster", small_adata, "cluster").type == "categorical"
    assert infer_field_spec("total_counts", small_adata, "total_counts").type == "continuous"
    assert field_id("RCTD: Astro_1 FGFR3") == "rctd_astro_1_fgfr3"


def test_build_with_auto_fields_declares_them(tmp_path):
    from spatialscape.build import build_dataset
    from spatialscape.validate import validate_local

    cfg_path = make_synthetic(tmp_path / "src", n_cells=80, n_genes=5)
    raw = yaml.safe_load(Path(cfg_path).read_text())
    raw["fields"] = []
    for s in raw["samples"]:
        s["fields"] = "auto"
    p = tmp_path / "src" / "auto.yaml"
    p.write_text(yaml.safe_dump(raw))
    m = build_dataset(load_config(p), tmp_path / "bundle", log=lambda *_: None)
    assert {f.id for f in m.fields} >= {"cluster", "total_counts"}
    assert m.field_by_id("cluster").type == "categorical"
    assert validate_local(tmp_path / "bundle") == []


def test_field_map_long_form_sets_scale(tmp_path):
    from spatialscape.config import SampleSpec

    s = SampleSpec.model_validate(
        {"id": "a", "platform": "visium", "path": str(tmp_path), "fields": {"mito": {"column": "chrM_ratio", "scale": 100}, "dom": "domain"}}
    )
    assert s.fields == {"mito": "chrM_ratio", "dom": "domain"}
    assert s.field_scales == {"mito": 100.0}


def test_overrides_change_single_samples_of_a_glob(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=60, n_genes=5)
    for d, f in (("d1", "sampleA"), ("d2", "sampleB")):
        (tmp_path / "src" / d).mkdir()
        (tmp_path / "src" / f"{f}.h5ad").rename(tmp_path / "src" / d / "adata.h5ad")
    entry = {"glob": "*/adata.h5ad", "platform": "visium", "id": "vis_{name}", "name": "{name} (Visium)", "fields": {"cluster": "cluster"}}
    p = tmp_path / "src" / "dataset.yaml"
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{**entry, "overrides": {"d2": {"name": "Second section", "images": [], "fields": {"counts": "total_counts"}}}}]}))
    cfg = load_config(p)
    a, b = cfg.samples
    assert a.name == "d1 (Visium)" and a.images == "auto" and a.fields == {"cluster": "cluster"}
    assert b.name == "Second section" and b.images == [] and b.fields == {"cluster": "cluster", "counts": "total_counts"}  # fields merge, lists replace
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{**entry, "overrides": {"vis_d1": {"group": "first"}}}]}))
    assert load_config(p).samples[0].group == "first"  # the rendered id works as a key too
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{**entry, "overrides": {"d3": {"group": "x"}}}]}))
    with pytest.raises(ValueError, match=r"overrides name no sample: d3 \(samples of \*/adata.h5ad: d1, d2\)"):
        load_config(p)
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{**entry, "overrides": {"d1": {"glob": "x"}}}]}))
    with pytest.raises(ValueError, match="cannot be overridden"):
        load_config(p)
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{**entry, "overrides": {"d1": {"nope": 1}}}]}))
    with pytest.raises(Exception, match="nope"):
        load_config(p)
    p.write_text(yaml.safe_dump({"id": "t", "name": "t", "samples": [{"path": "d1/adata.h5ad", "platform": "visium", "overrides": {"d1": {"group": "x"}}}]}))
    with pytest.raises(ValueError, match="`overrides` goes with `glob`"):
        load_config(p)
