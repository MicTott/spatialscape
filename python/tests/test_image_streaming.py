"""Images are written as pyramids band by band, from TIFF (tiled or striped), OME-Zarr or a bare Zarr array, in
memory bounded by one band: the same pixels as reading the image whole, whatever the band size or the source."""
from __future__ import annotations

import numpy as np
import pytest
import tifffile
import zarr

from spatialscape import images
from spatialscape.images import crop_window, stream_ome_zarr


def _tiled(path, data, levels=2, tile=(256, 256)):
    with tifffile.TiffWriter(path, bigtiff=True, ome=True) as tw:
        tw.write(data, tile=tile, metadata={"axes": "CYX"}, subifds=levels - 1)
        lv = data
        for _ in range(levels - 1):
            lv = lv[:, ::2, ::2]
            tw.write(lv, tile=tile, subfiletype=1)


def _levels(path):
    g = zarr.open_group(str(path), mode="r")
    return [np.asarray(g[d["path"]][:]) for d in g.attrs["multiscales"][0]["datasets"]]


def test_streamed_pyramid_matches_the_whole_image_read(tmp_path, monkeypatch):
    rng = np.random.default_rng(1)
    data = rng.integers(0, 4000, (3, 1100, 1300), dtype=np.uint16)
    src = tmp_path / "a.ome.tif"
    _tiled(src, data)
    monkeypatch.setattr(images, "BAND_BYTES", 1 << 18)  # bands of a few tile rows, several seams
    levels, wins = stream_ome_zarr(src, tmp_path / "a.ome.zarr", rgb=False)
    out = _levels(tmp_path / "a.ome.zarr")
    whole = images.read_image(src, rgb=False)
    assert np.array_equal(out[0], whole)
    assert np.array_equal(out[1], images.downsample2(whole))
    assert np.array_equal(out[2], images.downsample2(images.downsample2(whole)))
    assert levels == [(3, 1100, 1300), (3, 550, 650), (3, 275, 325), (3, 137, 162)] and len(wins) == 3  # down to 256 px, as write_ome_zarr
    assert all(0 < lo < hi <= 4000 for lo, hi in wins)  # fitted on a coarse level
    attrs = dict(zarr.open_group(str(tmp_path / "a.ome.zarr"), mode="r").attrs)
    assert [c["label"] for c in attrs["omero"]["channels"]] == ["ch0", "ch1", "ch2"]


def test_a_coarser_level_and_a_window_are_honoured(tmp_path):
    rng = np.random.default_rng(2)
    data = rng.integers(0, 1000, (2, 1024, 1536), dtype=np.uint16)
    src = tmp_path / "b.ome.tif"
    _tiled(src, data, levels=3)
    # max_size 300 from a 1536 px scan with 3 levels: every level lands on 192 px, so the cheapest (level 2, reduced 2x) wins
    shapes, axes = images.source_levels(src)
    level, f = images._choose_level(shapes, axes, 300)
    assert (level, f) == (2, 2)
    window = (10, 100, 20, 150)
    levels, _ = stream_ome_zarr(src, tmp_path / "b.ome.zarr", rgb=False, level=level, factor=f, window=window)
    whole = images.read_image(src, rgb=False, max_size=300)
    assert np.array_equal(_levels(tmp_path / "b.ome.zarr")[0], whole[:, 10:100, 20:150])
    assert levels[0] == (2, 90, 130)


def test_a_zarr_array_with_named_dimensions_streams(tmp_path):
    rng = np.random.default_rng(3)
    data = rng.integers(0, 255, (4, 700, 900), dtype=np.uint8)
    arr = zarr.open_array(str(tmp_path / "ds.zarr" / "_image"), mode="w", shape=data.shape, chunks=(2, 375, 375), dtype="uint8", zarr_format=2)
    arr[:] = data
    arr.attrs["_ARRAY_DIMENSIONS"] = ["channels", "y", "x"]  # a spatialproteomics image
    assert images.streamable(tmp_path / "ds.zarr" / "_image") and images.is_zarr_array(tmp_path / "ds.zarr" / "_image")
    assert images.source_levels(tmp_path / "ds.zarr" / "_image") == ([(4, 700, 900)], "cyx")
    levels, _ = stream_ome_zarr(tmp_path / "ds.zarr" / "_image", tmp_path / "o.ome.zarr", rgb=False, channel_names=["A", "B", "C", "D"])
    assert np.array_equal(_levels(tmp_path / "o.ome.zarr")[0], data) and levels[0] == (4, 700, 900)


def test_rgb_alpha_is_dropped_and_striped_planes_are_read_once_each(tmp_path, monkeypatch):
    rng = np.random.default_rng(4)
    data = rng.integers(0, 255, (4, 300, 400), dtype=np.uint8)
    src = tmp_path / "s.tif"
    tifffile.imwrite(src, data, photometric="minisblack")  # one strip per plane, no tiles
    levels, _ = stream_ome_zarr(src, tmp_path / "s.ome.zarr", rgb=True)
    assert levels[0] == (3, 300, 400) and np.array_equal(_levels(tmp_path / "s.ome.zarr")[0], data[:3])
    monkeypatch.setattr(images, "read_limit_bytes", lambda: 1000)
    with pytest.raises(images.ImageReadRefused, match="tiled or pyramidal"):
        stream_ome_zarr(src, tmp_path / "s2.ome.zarr", rgb=True)


def test_crop_window_is_the_crop_the_old_path_made():
    arr = np.zeros((3, 100, 100), dtype=np.uint8)
    win, tr = crop_window((100, 100), 2.0, (-40.0, -40.0), (0.0, 0.0, 60.0, 60.0))
    assert win == (19, 51, 19, 51) and tr == (-2.0, -2.0)
    from spatialscape.build import crop_to_points

    out, tr2 = crop_to_points(arr, 2.0, (-40.0, -40.0), (0.0, 0.0, 60.0, 60.0))
    assert out.shape[1:] == (32, 32) and tr2 == tr
    assert crop_window((100, 100), 2.0, (0.0, 0.0), (0.0, 0.0, 400.0, 400.0)) == ((0, 100, 0, 100), (0.0, 0.0))
