"""An OME-Zarr image source is copied into the bundle as it is: no decode, no re-encode, no size limit, and the
pyramid's own channel metadata is used. A setting that moves pixels falls back to reading and writing it."""
from __future__ import annotations

import numpy as np
import yaml
import zarr

from spatialscape import images
from spatialscape.build import build_dataset
from spatialscape.config import load_config
from spatialscape.synthetic import make_synthetic
from spatialscape.validate import validate_local


def _synthetic_with_pyramid(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=200, n_genes=5)
    src = tmp_path / "src"
    png = images.read_image(src / "sampleA.png", rgb=True)
    images.write_ome_zarr(png, src / "sampleA.ome.zarr", rgb=True)  # the pyramid bioformats2raw or an earlier build would hand over
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"][0]["images"][0]["path"] = "sampleA.ome.zarr"
    return cfg_path, doc, png


def test_an_ome_zarr_source_is_copied_as_is(tmp_path):
    cfg_path, doc, png = _synthetic_with_pyramid(tmp_path)
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), tmp_path / "out", log=logs.append)
    img = m.samples[0].images[0]
    out = tmp_path / "out" / "samples" / m.samples[0].id / img.path
    assert any("copied as is" in line and "not cropped" in line for line in logs)
    assert tuple(img.size) == (png.shape[1], png.shape[2])  # the whole pyramid, not the crop around the points
    src = tmp_path / "src" / "sampleA.ome.zarr"
    assert (out / "0" / "0.0.0").read_bytes() == (src / "0" / "0.0.0").read_bytes()
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == sorted(p.relative_to(src) for p in src.rglob("*"))
    assert img.channels is None and img.kind == "rgb"
    assert validate_local(tmp_path / "out") == []


def test_a_setting_that_moves_pixels_reads_and_writes_the_pyramid_instead(tmp_path):
    cfg_path, doc, png = _synthetic_with_pyramid(tmp_path)
    doc["samples"][0]["images"][0]["flip"] = "x"
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), tmp_path / "out", log=logs.append)
    assert any("moves its pixels" in line and "flip x" in line for line in logs)
    assert not any("copied as is" in line for line in logs)
    assert tuple(m.samples[0].images[0].size) != (png.shape[1], png.shape[2])  # cropped to the points as usual


def test_a_five_dimensional_pyramid_passes_through_with_its_channel_metadata(tmp_path):
    cfg_path = make_synthetic(tmp_path / "src", n_cells=200, n_genes=5)
    src = tmp_path / "src"
    rng = np.random.default_rng(0)
    data = np.zeros((1, 2, 1, 256, 256), dtype=np.uint16)
    data[0, 0, 0, 64:192, 64:192] = rng.integers(2000, 3000, size=(128, 128), dtype=np.uint16)  # DAPI signal in the low thousands
    data[0, 1, 0, 32:96, 32:96] = rng.integers(300, 800, size=(64, 64), dtype=np.uint16)
    g = zarr.open_group(str(src / "fluo.ome.zarr"), mode="w", zarr_format=2)
    g.create_array("0", shape=data.shape, chunks=(1, 1, 1, 128, 128), dtype="uint16")[:] = data
    g.create_array("1", shape=(1, 2, 1, 128, 128), chunks=(1, 1, 1, 128, 128), dtype="uint16")[:] = data[..., ::2, ::2]
    g.attrs["multiscales"] = [{"version": "0.4", "axes": [{"name": n} for n in "tczyx"], "datasets": [{"path": "0"}, {"path": "1"}]}]
    g.attrs["omero"] = {
        "channels": [
            {"label": "DAPI", "color": "0000ff", "window": {"start": 0, "end": 65535}},  # the dtype's whole range: fitted instead
            {"label": "CD3", "color": "00ff00", "window": {"start": 100, "end": 900}},
        ]
    }
    doc = yaml.safe_load(cfg_path.read_text())
    doc["samples"][0]["images"] = [{"id": "fluo", "name": "Fluorescence", "path": "fluo.ome.zarr", "kind": "multichannel"}]
    cfg_path.write_text(yaml.safe_dump(doc))
    logs: list[str] = []
    m = build_dataset(load_config(cfg_path), tmp_path / "out", log=logs.append)
    img = m.samples[0].images[0]
    assert tuple(img.size) == (256, 256) and img.kind == "multichannel"
    assert [c.name for c in img.channels] == ["DAPI", "CD3"]
    assert [c.color for c in img.channels] == ["#0000ff", "#00ff00"]
    assert tuple(img.channels[1].window) == (100.0, 900.0)  # a narrow window from the pyramid is kept
    lo, hi = img.channels[0].window
    assert 1500 < lo < hi <= 3000  # the full-range window was replaced by one fitted to the signal
    assert any("copied as is" in line and "2 channels" in line for line in logs)
    assert validate_local(tmp_path / "out") == []  # the size check reads y and x by axis name
    info = images.ome_zarr_info(src / "fluo.ome.zarr")
    assert info is not None and info.axes == "tczyx" and info.channels == 2 and len(info.levels) == 2
    assert images.ome_zarr_info(src / "sampleA.png") is None
