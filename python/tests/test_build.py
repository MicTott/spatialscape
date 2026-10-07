import json
from pathlib import Path

import numpy as np
import pytest
import yaml
import zarr

from spatialscape.build import add_sample, build_dataset
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local


def test_synthetic_build_validates(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=400, n_genes=20)
    cfg = load_config(cfg_path)
    out = tmp_path / "bundle"
    m = build_dataset(cfg, out, log=lambda *_: None)
    assert validate_local(out) == []
    assert {s.id for s in m.samples} == {"sampleA", "sampleB", "umapA"}
    vocab = m.vocabularies["cluster"]
    assert vocab.categories[:6] == ["Astro", "Excit_L2", "Excit_L5", "Inhib_PV", "Oligo", "Micro"]
    assert "NA" in vocab.categories
    # the embedding sample shares the vocabulary and the genes
    assert m.samples[2].kind == "embedding"
    genes = json.loads((out / "genes.json").read_text())
    assert "G001" in genes
    # hover truth: obs/order maps bundle rows back to source rows
    og = zarr.open_group(str(out / "samples/sampleA/obs.zarr"), mode="r")
    order = og["order"][:]
    assert sorted(order.tolist()) == list(range(m.samples[0].nObs))
    ids = json.loads((out / "samples/sampleA/ids/0.json").read_text())
    assert ids[0] == f"cell_{order[0]}"
    # image placed in microns: 512 px * 10 um
    img = m.samples[0].images[0]
    assert img.pixelSize == pytest.approx(10.0)
    assert img.size == (384, 512)


def test_add_sample_keeps_codes_stable(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=300, n_genes=10)
    cfg = load_config(cfg_path)
    out = tmp_path / "bundle"
    m1 = build_dataset(cfg, out, log=lambda *_: None)
    before = list(m1.vocabularies["cluster"].categories)
    m2 = add_sample(cfg, out, "sampleB", log=lambda *_: None)
    assert list(m2.vocabularies["cluster"].categories) == before
    assert validate_local(out) == []


def test_config_rejects_duplicate_sample_ids(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    raw = yaml.safe_load(Path(cfg_path).read_text())
    raw["samples"][1]["id"] = raw["samples"][0]["id"]
    bad = tmp_path / "src" / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="unique"):
        load_config(bad)


def test_microns_from_uns_and_overrides(small_adata, tmp_path):
    from spatialscape.config import SampleSpec
    from spatialscape.geometry import microns_per_unit
    from spatialscape.readers import SampleInput

    si = SampleInput(adata=small_adata, coords=np.asarray(small_adata.obsm["spatial"]), gene_names=np.array(small_adata.var_names), uns=dict(small_adata.uns))
    spec = SampleSpec(id="s", platform="visium", path=tmp_path)
    assert microns_per_unit(spec, si) == pytest.approx(100 / 20)
    spec = SampleSpec(id="s", platform="visium", path=tmp_path, microns={"spot_diameter_fullres": 110})
    assert microns_per_unit(spec, si) == pytest.approx(0.5)
    spec = SampleSpec(id="s", platform="xenium", path=tmp_path)
    assert microns_per_unit(spec, si) == 1.0


def test_refresh_applies_palette_changes_without_changing_codes(tmp_path):
    from spatialscape.build import refresh

    cfg_path = make_synthetic(tmp_path / "src", n_cells=200, n_genes=5)
    out = tmp_path / "bundle"
    m1 = build_dataset(load_config(cfg_path), out, log=lambda *_: None)
    v1 = m1.vocabularies["cluster"]
    pal = tmp_path / "palette.json"
    pal.write_text(json.dumps({"cluster": {"Astro": "#123456", "Oligo": "#abcdef"}}))
    doc = yaml.safe_load(cfg_path.read_text())
    doc["palette"] = str(pal)
    cfg_path.write_text(yaml.safe_dump(doc))
    m2 = refresh(load_config(cfg_path), out)
    v2 = m2.vocabularies["cluster"]
    assert v2.categories == v1.categories
    assert v2.colors[v2.categories.index("Astro")] == "#123456"
    assert v2.colors[v2.categories.index("Oligo")] == "#abcdef"
    other = next(c for c in v1.categories if c not in ("Astro", "Oligo"))
    assert v2.colors[v2.categories.index(other)] == v1.colors[v1.categories.index(other)]
