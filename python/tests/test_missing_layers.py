"""An optional layer whose file is absent (image, cell shapes, another segmentation, molecules) is left out with a
note, so a sample builds from its processed object alone; the layer arrives on the next build once the file does."""
import json
import shutil

import yaml

from spatialscape.build import build_bundle
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic


def _rename_layer_files(cfg_path, suffix=".elsewhere"):
    """Point sampleA's image, polygons, molecules and segmentation at files that are not there (yet)."""
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    a = doc["samples"][0]
    moved = []
    for part in (a["images"][0], a["polygons"], a["molecules"], a["segmentations"][0]):
        moved.append((cfg_path.parent / part["path"], cfg_path.parent / (part["path"] + suffix)))
        part["path"] = part["path"] + suffix
    cfg_path.write_text(yaml.safe_dump(doc))
    return moved


def test_missing_optional_layers_are_noted_not_fatal_and_arrive_with_their_files(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=150, n_genes=5)
    moved = _rename_layer_files(cfg)
    logs: list[str] = []
    r1 = build_bundle(load_config(cfg), tmp_path / "out", log=logs.append)
    assert r1.problems == []
    notes = [line for line in logs if "is not there; built without it" in line]
    assert len(notes) == 4 and {n.split("] ")[1].split(":")[0] for n in notes} == {"image", "cell shapes", "molecules", "segmentation"}
    m1 = json.loads((r1.out / "manifest.json").read_text())["samples"][0]
    assert m1["images"] == [] and m1.get("molecules") is None and m1.get("segmentations", []) == []
    assert any("auto polygons: obsm/segmentations" in line for line in logs)  # the shapes the object itself carries

    for src, dst in moved:  # the files appear under the names the yaml expects
        shutil.copy(src, dst)
    r2 = build_bundle(load_config(cfg), tmp_path / "out", log=logs.append)
    assert r2.problems == [] and r2.plan.actions[0].reason == "source changed"
    m2 = json.loads((r2.out / "manifest.json").read_text())["samples"][0]
    assert len(m2["images"]) == 1 and m2["molecules"] is not None and len(m2["segmentations"]) == 1
    assert m2["shapes"]["cells"] == 150


def test_the_expression_file_is_never_optional(tmp_path):
    cfg = make_synthetic(tmp_path / "src", n_cells=50, n_genes=5)
    doc = yaml.safe_load(cfg.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    doc["samples"][0]["path"] = "nowhere.h5ad"
    cfg.write_text(yaml.safe_dump(doc))
    try:
        build_bundle(load_config(cfg), tmp_path / "out", log=lambda *_: None)
    except (FileNotFoundError, OSError):
        return
    raise AssertionError("a missing expression file must stop the build")
