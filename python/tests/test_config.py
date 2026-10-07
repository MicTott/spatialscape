from pathlib import Path

import numpy as np
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
