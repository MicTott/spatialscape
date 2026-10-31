"""spatialproteomics objects as samples: the per-cell intensities become the expression layer kept as it is, label
numbers become names with the object's colours, the label mask becomes cell outlines, and the image's channels take
their names from the object."""
from __future__ import annotations

import numpy as np
import pytest
import yaml
import zarr

from spatialscape import proteomics
from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.polygons import read_polygon_labels
from spatialscape.readers import peek, read_anndata
from spatialscape.validate import validate_local


def make_object(path, n=12, size=64, channels=("DAPI", "CD3", "CD20")):
    """A tiny object in the layout `ds.drop_encoding().to_zarr()` writes: xarray dimension names on every array."""
    rng = np.random.default_rng(0)
    g = zarr.open_group(str(path), mode="w", zarr_format=2)

    def arr(name, data, dims):
        a = g.create_array(name, shape=data.shape, dtype=data.dtype if data.dtype.kind != "O" else "U32", chunks=data.shape)
        a[:] = data.astype("U32") if data.dtype.kind == "O" else data
        a.attrs["_ARRAY_DIMENSIONS"] = list(dims)

    # cells on a grid, each a filled square in the mask
    seg = np.zeros((size, size), dtype=np.int64)
    cx, cy = [], []
    for i in range(n):
        r, c = 8 + 16 * (i // 4), 8 + 16 * (i % 4)
        seg[r - 4 : r + 4, c - 4 : c + 4] = i + 1
        cy.append(r - 0.5)
        cx.append(c - 0.5)
    arr("_segmentation", seg, ("y", "x"))
    image = rng.integers(0, 200, (len(channels), size, size)).astype(np.uint8)
    arr("_image_raw", image, ("channels", "y", "x"))
    arr("channels", np.array(channels, dtype=object), ("channels",))
    arr("cells", np.arange(1, n + 1), ("cells",))
    arr("x", np.arange(size), ("x",))
    arr("y", np.arange(size), ("y",))
    features = ["CD3_binarized", "_labels", "_neighborhoods", "centroid-0", "centroid-1", "degree"]
    labels = np.array([1, 2, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1])
    obs = np.column_stack([(labels == 1).astype(float), labels, np.where(labels == 3, 2, 1), cy, cx, rng.integers(3, 9, n)]).astype(np.float64)
    arr("_obs", obs, ("cells", "features"))
    arr("features", np.array(features, dtype=object), ("features",))
    arr("_intensity", rng.random((n, len(channels))).astype(np.float64) * 3, ("cells", "channels"))
    arr("_la_properties", np.array([["#ff0000", "T cell"], ["#00ff00", "B cell"], ["#0000ff", "Macrophage"]], dtype=object), ("labels", "la_props"))
    arr("labels", np.array([1, 2, 3]), ("labels",))
    arr("la_props", np.array(["_color", "_name"], dtype=object), ("la_props",))
    arr("_nh_properties", np.array([["#aaaaaa", "Neighborhood 1"], ["#bbbbbb", "Neighborhood 2"]], dtype=object), ("neighborhoods", "nh_props"))
    arr("neighborhoods", np.array([1, 2]), ("neighborhoods",))
    arr("nh_props", np.array(["_color", "_name"], dtype=object), ("nh_props",))
    arr("_la_layers", np.array([["Lymphocyte" if lab < 3 else "Myeloid", ["T cell", "B cell", "Macrophage"][lab - 1]] for lab in labels], dtype=object), ("cells", "la_features"))
    arr("la_features", np.array(["labels_0", "labels_1"], dtype=object), ("la_features",))
    return path


def test_the_object_reads_as_an_anndata_with_names_colours_and_centroids(tmp_path):
    obj = make_object(tmp_path / "core.zarr")
    assert proteomics.is_spatialproteomics(obj) and proteomics.image_key(obj) == "_image_raw"
    a = read_anndata(obj)
    assert a.shape == (12, 3) and list(a.var_names) == ["DAPI", "CD3", "CD20"] and a.X.dtype == np.float32
    assert list(a.obs["labels"].cat.categories) == ["T cell", "B cell", "Macrophage"]
    assert a.obs["labels"].iloc[4] == "Macrophage" and a.uns["labels_colors"] == ["#ff0000", "#00ff00", "#0000ff"]
    assert list(a.obs["neighborhoods"].cat.categories) == ["Neighborhood 1", "Neighborhood 2"]
    assert list(a.obs["CD3_binarized"].cat.categories) == ["negative", "positive"] and a.obs["CD3_binarized"].iloc[0] == "positive"
    assert list(a.obs["labels_0"].cat.categories) == ["Lymphocyte", "Myeloid"]
    assert a.obsm["spatial"].shape == (12, 2) and a.obsm["spatial"][0].tolist() == [7.5, 7.5]  # x = centroid-1, y = centroid-0
    assert "_labels" not in a.obs and "_neighborhoods" not in a.obs
    pk = peek(obj)
    assert pk.n_vars == 3 and "labels" in pk.obs and pk.obsm == ["spatial"]


def test_label_masks_trace_to_one_ring_per_cell(tmp_path):
    obj = make_object(tmp_path / "core.zarr")
    ids, x, y = read_polygon_labels(obj / "_segmentation", max_vertices=16)
    assert sorted(set(ids), key=int) == [str(i) for i in range(1, 13)]
    first = ids == "1"
    assert first.sum() <= 16 and x[first].min() == pytest.approx(3.5, abs=0.6) and x[first].max() == pytest.approx(11.5, abs=0.6)  # an 8 px square around (7.5, 7.5)
    assert y[first].min() == pytest.approx(3.5, abs=0.6) and y[first].max() == pytest.approx(11.5, abs=0.6)


def test_a_core_builds_with_its_colours_outlines_and_channel_names(tmp_path):
    make_object(tmp_path / "data" / "LN_1.zarr")
    doc = {
        "id": "cores",
        "name": "Cores",
        "default_gene": "CD3",
        "default_color": {"field": "cell_type"},
        "fields": [{"id": "cell_type", "name": "Cell type", "type": "categorical"}, {"id": "nh", "name": "Neighbourhood", "type": "categorical"}, {"id": "degree", "name": "Degree", "type": "continuous"}],
        "samples": [
            {
                "id": "LN_1",
                "name": "Core 1",
                "platform": "codex",
                "path": "data/LN_1.zarr",
                "microns": {"microns_per_unit": 0.5},
                "expression": {"normalized": "raw"},
                "fields": {"cell_type": "labels", "nh": "neighborhoods", "degree": "degree"},
                "polygons": {"labels": "data/LN_1.zarr/_segmentation"},
                "images": [{"id": "stains", "name": "Stains", "path": "data/LN_1.zarr/_image_raw", "kind": "multichannel", "pixels_per_unit": 1.0, "crop": False}],
            }
        ],
    }
    cfg_path = tmp_path / "cores.yaml"
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), tmp_path / "out", log=logs.append)
    s = m.samples[0]
    assert s.platform == "codex" and s.expr.normalized == "raw" and s.nGenes == 3
    assert any("kept as it is" in line for line in logs)
    voc = m.vocabularies[next(f for f in m.fields if f.id == "cell_type").vocabulary]
    assert dict(zip(voc.categories, voc.colors, strict=True)) == {"T cell": "#ff0000", "B cell": "#00ff00", "Macrophage": "#0000ff"}
    assert s.shapes is not None and s.shapes.cells == 12
    assert [c.name for c in s.images[0].channels] == ["DAPI", "CD3", "CD20"] and tuple(s.images[0].size) == (64, 64)
    assert s.images[0].pixelSize == pytest.approx(0.5) and s.bbox[2] == pytest.approx((55.5 - 7.5) * 0.5)
    assert validate_local(tmp_path / "out") == []


def test_codex_coordinates_need_a_pixel_size(tmp_path):
    make_object(tmp_path / "data" / "LN_1.zarr")
    doc = {"id": "cores", "name": "Cores", "samples": [{"id": "LN_1", "platform": "codex", "path": "data/LN_1.zarr"}]}
    cfg_path = tmp_path / "cores.yaml"
    cfg_path.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="microns_per_unit"):
        build_dataset(load_config(cfg_path), tmp_path / "out", log=lambda *_: None)
