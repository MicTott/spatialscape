"""SpatialData stores, zarr v3 (spatialdata 0.8) and zarr v2 (spatialdata 0.3), read without the spatialdata
package: tiny_sdata_v3.zarr / tiny_sdata_v2.zarr (python/tests/fixtures/make_tiny_sdata.py) hold an RGB image and a
label mask at 0.5 units per pixel, hexagonal cell polygons, Visium-like circles in the image's pixel frame, 600
molecules, and three tables annotating the polygons, the circles and the labels."""

import json
from pathlib import Path

import numpy as np
import pytest

from spatialscape import sdata as S
from spatialscape.config import DatasetConfig, SampleSpec

FIX = Path(__file__).parent / "fixtures"
STORES = [FIX / "tiny_sdata_v3.zarr", FIX / "tiny_sdata_v2.zarr"]


@pytest.mark.parametrize("store", STORES, ids=["v3", "v2"])
def test_elements_and_transformations(store):
    assert S.is_spatialdata(store)
    assert not S.is_spatialdata(FIX)
    els = S.elements(store)
    assert els["images"] == ["he"] and els["labels"] == ["seg"] and els["points"] == ["transcripts"]
    assert els["shapes"] == ["cells", "spots"] and els["tables"] == ["labels_table", "spots_table", "table"]
    half = np.array([[0.5, 0, 0], [0, 0.5, 0], [0, 0, 1]])
    np.testing.assert_allclose(S.element_affine(store, "images", "he"), half)
    np.testing.assert_allclose(S.element_affine(store, "labels", "seg"), half)
    np.testing.assert_allclose(S.element_affine(store, "shapes", "spots"), half)
    np.testing.assert_allclose(S.element_affine(store, "shapes", "cells"), np.eye(3))
    np.testing.assert_allclose(S.element_affine(store, "points", "transcripts"), np.eye(3))
    assert S.coordinate_systems(store, "images", "he") == ["global"]
    with pytest.raises(KeyError, match="coordinate system 'slide'"):
        S.element_affine(store, "shapes", "cells", "slide")


@pytest.mark.parametrize("store", STORES, ids=["v3", "v2"])
def test_shapes_points_labels_and_table_link(store):
    cells = S.read_shapes(store, "cells")
    assert cells.kind == "polygon" and len(cells.ids) == 40 and cells.ids[0] == "cell_0"
    ids, x, y = cells.polygons
    assert len(ids) == 240 and ids[0] == "cell_0"  # hexagons, the closing vertex dropped
    np.testing.assert_allclose(cells.centroids[0], [x[:6].mean(), y[:6].mean()])
    spots = S.read_shapes(store, "spots")
    assert spots.kind == "circle" and spots.radius is not None and spots.radius[0] == 5.0
    np.testing.assert_allclose(spots.centroids[:3], cells.centroids[:3] * 2)  # the same cells in the pixel frame
    pi = S.points_info(store, "transcripts")
    assert pi.feature_key == "feature_name" and pi.instance_key == "cell_id" and {"x", "y", "feature_name", "cell_id"} <= set(pi.columns)
    lab_ids, lab_xy = S.label_centroids(store, "seg")
    assert list(lab_ids[:3]) == ["1", "2", "3"] and lab_xy.shape == (40, 2)
    import anndata as ad

    a = ad.read_zarr(S.table_dir(store, "table"))
    link = S.table_link(a)
    assert (link.region, link.region_key, link.instance_key) == ("cells", "region", "cell_id")
    assert S.table_link_on_disk(store, "table").region == "cells"
    assert S.table_link_on_disk(store, "labels_table").instance_key == "label"
    with pytest.raises(ValueError, match="set `table:`"):
        S.table_dir(store, None)
    assert list(S.match_instances(a.obs, "cell_id", cells.ids)[:3]) == [0, 1, 2]
    assert S.instance_strings(a)[:2] == ["cell_0", "cell_1"]


def test_rows_without_an_instance_fall_back_or_drop():
    import anndata as ad

    from spatialscape.readers import load_sample

    store = STORES[0]
    a = ad.read_zarr(S.table_dir(store, "table"))
    a.obs.loc[a.obs_names[:3], "cell_id"] = ["nope_a", "nope_b", "nope_c"]
    xy, has = S.region_centroids(store, "shapes/cells", a, "cell_id", "global")
    assert list(has[:4]) == [False, False, False, True] and np.isnan(xy[0, 0]) and np.isfinite(xy[3]).all()
    # through load_sample: a table without obsm/spatial drops the rows and says so; one with it uses them
    a.write_zarr(store.parent / "_tmp_table.zarr")
    try:
        spec = SampleSpec(id="t", path=store.parent / "_tmp_table.zarr", platform="xenium", coords="shapes/cells")
        with pytest.raises(ValueError, match="not a SpatialData store"):
            load_sample(spec)
    finally:
        import shutil

        shutil.rmtree(store.parent / "_tmp_table.zarr", ignore_errors=True)


def test_show_takes_a_spatialdata_object(tmp_path):
    """show(sdata): the store it was read from, or the object written under the cache; checked with a stand-in."""
    from spatialscape.session import _spatialdata_path

    class Backed:
        path = str(STORES[0])
        tables = {"table": None}
        shapes = {"cells": None}

        def write(self, out, overwrite=False):
            raise AssertionError("a backed object is not written again")

    assert _spatialdata_path(Backed(), tmp_path, log=lambda *_: None) == STORES[0]

    class InMemory:
        path = None
        tables = {"table": None}
        shapes = {}
        written: list = []

        def write(self, out, overwrite=False):
            Path(out).mkdir(parents=True)
            (Path(out) / "zarr.json").write_text("{}")
            self.written.append(out)

    obj = InMemory()
    out = _spatialdata_path(obj, tmp_path, log=lambda *_: None)
    assert out.parent == tmp_path and obj.written == [out]
    assert _spatialdata_path(obj, tmp_path, log=lambda *_: None) == out and len(obj.written) == 1  # written once


@pytest.mark.parametrize("store", STORES, ids=["v3", "v2"])
def test_store_image_channel_names(store):
    from spatialscape.images import ome_zarr_info, source_channel_names

    info = ome_zarr_info(store / "images" / "he")
    assert info is not None and info.channels == 3 and info.zarr_format == (3 if store.name.endswith("v3.zarr") else 2)
    assert source_channel_names(store / "images" / "he") == ["r", "g", "b"]


def test_wkb_parser_matches_shapely_or_stands_alone():
    import pyarrow.parquet as pq

    df = pq.read_table(S.shapes_parquet(STORES[0], "cells")).to_pandas()
    blobs = [bytes(b) for b in df.geometry[:5]]
    ours = [S._wkb_one(b) for b in blobs]
    assert all(k == "polygon" and pts.shape == (7, 2) for k, pts in ours)
    via = S._wkb_geometries(blobs)
    for (k1, p1), (k2, p2) in zip(ours, via, strict=True):
        assert k1 == k2
        np.testing.assert_allclose(p1, p2)
    pt = pq.read_table(S.shapes_parquet(STORES[0], "spots")).to_pandas()
    k, p = S._wkb_one(bytes(pt.geometry.iloc[0]))
    assert k == "point" and p.shape == (1, 2)


def test_geoparquet_boundaries_read_as_a_long_table():
    from spatialscape.polygons import read_polygon_table

    ids, _x, _y = read_polygon_table(S.shapes_parquet(STORES[0], "cells"), "cell_id", "vertex_x", "vertex_y")
    assert len(ids) == 240 and ids[6] == "cell_1"


def test_parquet_directories_read_like_one_table():
    from spatialscape.tables import iter_batches, read_columns, table_columns

    d = STORES[0] / "points" / "transcripts" / "points.parquet"
    assert d.is_dir()
    assert "feature_name" in table_columns(d)
    t = read_columns(d, ["x", "y"])
    assert t.num_rows == 600
    assert sum(b.num_rows for b in iter_batches(d, ["x"])) == 600


def _spec(store, table, platform, **kw):
    return SampleSpec(id=table, path=store, table=table, platform=platform, **kw)


@pytest.mark.parametrize("store", STORES, ids=["v3", "v2"])
def test_resolve_sample_fills_region_shapes_points_and_spot_size(store):
    cells = S.resolve_sample(_spec(store, "table", "xenium"))
    assert cells.coords == "shapes/cells"
    assert cells.polygons is not None and cells.polygons.path == S.shapes_parquet(store, "cells") and cells.polygons.affine is None
    assert cells.molecules is not None and cells.molecules.feature_column == "feature_name" and cells.molecules.cell_column == "cell_id" and cells.molecules.qv_column is None
    spots = S.resolve_sample(_spec(store, "spots_table", "visium"))
    assert spots.coords == "shapes/spots" and spots.polygons is None
    assert spots.microns.spot_diameter_fullres == pytest.approx(5.0)  # radius 5 px at 0.5 units per px, doubled
    labs = S.resolve_sample(_spec(store, "labels_table", "xenium"))
    assert labs.coords == "labels/seg" and labs.polygons is not None and labs.polygons.labels == S.labels_array(store, "seg")
    assert labs.polygons.affine == pytest.approx((0.5, 0, 0, 0, 0.5, 0))
    # what the entry sets, it keeps
    kept = S.resolve_sample(_spec(store, "table", "xenium", coords="obsm/none", points=False))
    assert kept.coords == "obsm/none" and kept.molecules is None
    with pytest.raises(KeyError, match="no points element 'nope'"):
        S.resolve_sample(_spec(store, "table", "xenium", points="nope"))
    imgs = S.store_images(_spec(store, "table", "xenium"))
    assert [(i.id, i.kind, i.pixels_per_unit, i.offset) for i in imgs] == [("he", "rgb", 2.0, (0.0, 0.0))]
    assert [g.id for g in S.store_segmentations(_spec(store, "spots_table", "visium"), "spots")] == ["cells"]
    assert S.store_segmentations(_spec(store, "table", "xenium"), "cells") == []


@pytest.mark.parametrize("store", STORES, ids=["v3", "v2"])
def test_build_from_a_store(tmp_path, store):
    from spatialscape.build import build_dataset

    cfg = DatasetConfig(
        id="sd",
        name="sd",
        samples=[
            _spec(store, "table", "xenium", fields={"cluster": "cluster"}),
            _spec(store, "spots_table", "visium", fields={"domain": "domain"}),
            _spec(store, "labels_table", "xenium", fields={"cluster": "cluster"}),
        ],
    )
    out = tmp_path / "bundle"
    build_dataset(cfg, out)
    m = json.loads((out / "manifest.json").read_text())
    by = {s["id"]: s for s in m["samples"]}
    cells, spots, labs = by["table"], by["spots_table"], by["labels_table"]
    # polygons: 40 hexagons as cell shapes, the circles' table gets them as a segmentation to compare with
    assert cells["shapes"]["cells"] == 40 and cells["segmentations"] == []
    assert spots.get("shapes") is None and [g["id"] for g in spots["segmentations"]] == ["cells"]
    assert labs["shapes"]["cells"] == 40  # traced from the mask, matched through the label column
    # molecules from the points element, in every sample's frame
    assert cells["molecules"]["count"] == 600 and spots["molecules"]["count"] == 600
    # the image placed by the store's transformation: 0.5 units per pixel; a Visium unit is 55 / 5 = 11 um
    (img,) = cells["images"]
    assert img["kind"] == "rgb" and img["pixelSize"] == pytest.approx(0.5)
    (img2,) = spots["images"]
    assert img2["pixelSize"] == pytest.approx(5.5) and spots["pointRadius"] == 27.5
    # the same cells, so the same extent in microns up to the unit: 1 um per unit vs 11
    assert cells["bbox"][2] == pytest.approx(spots["bbox"][2] / 11, rel=0.02)
    import zarr

    xy = np.asarray(zarr.open_group(str(out / "samples" / "table" / "obs.zarr"), mode="r")["xy"][:])
    assert xy.shape == (40, 2) and xy.min() == pytest.approx(0, abs=1e-6)
