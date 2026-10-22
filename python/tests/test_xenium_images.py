"""Xenium morphology images: discovered safely (a coarse pyramid level, never a whole slide), named from the
OME metadata, drawn with a window fitted to the signal, and refused with a clear message when they cannot be read."""
from __future__ import annotations

import json

import numpy as np
import pytest
import tifffile
import zarr

from spatialscape import images
from spatialscape.build import build_bundle
from spatialscape.config import SampleSpec, load_config
from spatialscape.discover import auto_images, xenium_morphology, xenium_pixel_size
from spatialscape.synthetic import make_synthetic


def quiet(*_):
    pass


def write_pyramid(path, shape=(2, 1024, 1536), names=("DAPI", "ATP1A1/CD45/E-Cadherin"), levels=4, signal=3000):
    """A small pyramidal OME-TIFF with SubIFD levels, uint16 signal in the low thousands like real morphology."""
    rng = np.random.default_rng(0)
    c, h, w = shape
    base = np.zeros(shape, dtype=np.uint16)
    base[:, h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = rng.integers(signal // 3, signal, size=(c, h // 2, w // 2), dtype=np.uint16)
    with tifffile.TiffWriter(path, bigtiff=True, ome=True) as tw:
        meta = {"axes": "CYX", "Channel": {"Name": list(names)}, "PhysicalSizeX": 0.2125, "PhysicalSizeY": 0.2125}
        tw.write(base, subifds=levels - 1, tile=(256, 256), metadata=meta)
        lv = base
        for _ in range(levels - 1):
            lv = lv[:, ::2, ::2]
            tw.write(lv, subfiletype=1, tile=(256, 256))
    return base


def test_discovery_prefers_the_focus_image_and_never_the_3d_stack(tmp_path):
    d = tmp_path / "outs"
    d.mkdir()
    (d / "morphology.ome.tif").write_bytes(b"3d stack")  # XOA 1 z-stack: never used
    assert xenium_morphology(d) is None
    (d / "morphology_mip.ome.tif").write_bytes(b"mip")
    assert xenium_morphology(d) == d / "morphology_mip.ome.tif"
    (d / "morphology_focus.ome.tif").write_bytes(b"focus")
    assert xenium_morphology(d) == d / "morphology_focus.ome.tif"
    (d / "morphology_focus").mkdir()  # XOA 2+: one file per stain, the first holds the multi-file series
    (d / "morphology_focus" / "morphology_focus_0001.ome.tif").write_bytes(b"x")
    (d / "morphology_focus" / "morphology_focus_0000.ome.tif").write_bytes(b"x")
    assert xenium_morphology(d) == d / "morphology_focus" / "morphology_focus_0000.ome.tif"
    assert xenium_pixel_size(d) == 0.2125
    (d / "experiment.xenium").write_text(json.dumps({"pixel_size": 0.25}))
    assert xenium_pixel_size(d) == 0.25


def test_discovered_morphology_is_read_at_a_coarse_level(tmp_path):
    d = tmp_path / "outs"
    d.mkdir()
    write_pyramid(d / "morphology_focus.ome.tif")
    spec = SampleSpec(id="x", platform="xenium", path=d / "adata.h5ad")
    [im], microns = auto_images(spec)
    assert microns is None and im.kind == "multichannel"
    assert im.max_size == 384  # 1536 px at 0.2125 um/px, read at 0.85 um/px: the level 4x coarser
    assert images.read_image(im.path, rgb=False, max_size=im.max_size).shape == (2, 256, 384)
    assert im.name == "Morphology" and im.pixels_per_unit == pytest.approx(1 / 0.2125)
    (d / "experiment.xenium").write_text(json.dumps({"pixel_size": 0.25}))
    assert auto_images(spec)[0][0].max_size == 452  # the target is a pixel size, so it follows the scan's
    small = images.read_image(d / "morphology_focus.ome.tif", rgb=False, max_size=300)
    assert small.shape == (2, 128, 192)  # at most 300 px: the 192 px level, read as is
    assert images.ome_channel_names(d / "morphology_focus.ome.tif") == ["DAPI", "ATP1A1/CD45/E-Cadherin"]


def test_a_read_too_large_for_memory_is_refused_with_a_way_out(tmp_path, monkeypatch):
    p = tmp_path / "big.ome.tif"
    write_pyramid(p)
    monkeypatch.setattr(images, "read_limit_bytes", lambda: 1_000_000)  # pretend this machine is tiny
    with pytest.raises(images.ImageReadRefused, match=r"1,536 x 1,024 px needs 0\.0 GB of memory.*set `max_size:` on this image \(for example 768\)"):
        images.read_image(p, rgb=False)
    assert images.read_image(p, rgb=False, max_size=300).shape[1] == 128  # a coarser level fits
    with pytest.raises(images.ImageReadRefused, match=r"lower `max_size:` on this image$"):
        images.read_image(p, rgb=False, max_size=5000)


def test_jpeg2000_without_imagecodecs_says_how_to_fix_it(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_imagecodecs(name, *a, **k):
        if name == "imagecodecs":
            raise ImportError("no imagecodecs")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_imagecodecs)
    with pytest.raises(images.ImageReadRefused, match=r'JPEG 2000 compressed.*pip install "spatialscape\[images\]".*images: \[\]'):
        images._require_codec(tmp_path / "m.ome.tif", 34712)
    with pytest.raises(images.ImageReadRefused, match="Aperio JPEG 2000"):
        images._require_codec(tmp_path / "s.svs", 33005)
    images._require_codec(tmp_path / "m.ome.tif", 8)  # deflate and friends need nothing extra


def test_fluorescence_gets_names_colours_and_windows_fitted_to_the_signal(tmp_path):
    p = make_synthetic(tmp_path / "src", n_cells=150, n_genes=6)
    write_pyramid(tmp_path / "src" / "if.ome.tif", shape=(2, 512, 512), levels=2, signal=3000)
    import yaml

    doc = yaml.safe_load(p.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    doc["samples"][0]["images"] = [{"id": "if", "name": "IF", "path": "if.ome.tif", "kind": "multichannel", "pixels_per_unit": 1.0, "crop": False}]
    p.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(p), log=quiet)
    assert r.problems == []
    [img] = r.manifest.samples[0].images
    assert [c.name for c in img.channels] == ["DAPI", "ATP1A1/CD45/E-Cadherin"]
    assert [c.color for c in img.channels] == ["#4c8dff", "#3fd14a"]
    for c in img.channels:
        lo, hi = c.window
        assert 900 <= lo < hi <= 3000  # fitted to the signal, not 0..65535
    omero = zarr.open_group(str(r.out / "samples" / "sampleA" / "if.ome.zarr"), mode="r").attrs["omero"]
    assert omero["channels"][0]["window"]["end"] == pytest.approx(img.channels[0].window[1])
    doc["samples"][0]["images"][0]["channels"] = [{"name": "Nuclei", "window": [0, 5000]}, {"name": "Membrane", "color": "#ff00ff"}]
    p.write_text(yaml.safe_dump(doc))
    r = build_bundle(load_config(p), log=quiet)
    [img] = r.manifest.samples[0].images
    assert [(c.name, c.color) for c in img.channels] == [("Nuclei", "#4c8dff"), ("Membrane", "#ff00ff")]  # unnamed colours get the palette
    assert img.channels[0].window == (0, 5000) and img.channels[1].window[1] <= 3000  # a yaml window wins; the other is fitted


def test_hidden_macos_sidecars_are_never_taken_for_the_image(tmp_path):
    d = tmp_path / "outs"
    (d / "morphology_focus").mkdir(parents=True)
    (d / "morphology_focus" / "._morphology_focus_0000.ome.tif").write_bytes(b"\x00\x05\x16\x07")
    (d / "morphology_focus" / "morphology_focus_0000.ome.tif").write_bytes(b"x")
    assert xenium_morphology(d).name == "morphology_focus_0000.ome.tif"


def test_bigtiff_shape_comes_from_the_header(tmp_path, monkeypatch):
    p = tmp_path / "scan.btf"
    tifffile.imwrite(p, np.zeros((2, 700, 900), dtype=np.uint16), bigtiff=True, ome=True, metadata={"axes": "CYX"})
    monkeypatch.setattr(images, "read_image", lambda *a, **k: pytest.fail("read the pixels"))
    assert images.read_image_shape(p, rgb=False) == (2, 700, 900)


def test_a_file_without_pyramid_is_reduced_band_by_band(tmp_path, monkeypatch):
    import tracemalloc

    rng = np.random.default_rng(1)
    src = rng.integers(0, 4000, size=(3, 2048, 1536), dtype=np.uint16)
    p = tmp_path / "flat.ome.tif"
    tifffile.imwrite(p, src, tile=(256, 256), ome=True, metadata={"axes": "CYX"})
    monkeypatch.setattr(images, "BAND_BYTES", 2 * 2**20)  # bands of a few rows of tiles
    tracemalloc.start()
    out = images.read_image(p, rgb=False, max_size=400)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert out.shape == (3, 256, 192)  # 2048 / 8
    expect = src.reshape(3, 256, 8, 192, 8).astype(np.int64).sum(axis=(2, 4))
    assert np.array_equal(out, ((expect + 32) // 64).astype(np.uint16))  # the mean of each 8 x 8 cell
    assert peak < src.nbytes / 2  # never the whole 18.9 MB source at once
    rgb = rng.integers(0, 255, size=(1024, 768, 3), dtype=np.uint8)  # interleaved RGB, tiled
    tifffile.imwrite(tmp_path / "he.tif", rgb, tile=(256, 256), photometric="rgb")
    he = images.read_image(tmp_path / "he.tif", rgb=True, max_size=300)
    assert he.shape == (3, 256, 192) and he.dtype == np.uint8
    strip = tmp_path / "ij.tif"  # ImageJ hyperstack: one strip per plane, read a plane at a time
    tifffile.imwrite(strip, src[:2], imagej=True, rowsperstrip=2048, metadata={"axes": "CYX"})
    assert images.read_image(strip, rgb=False, max_size=1000).shape == (2, 512, 384)


def test_auto_windows_edge_cases():
    w = images.auto_windows
    assert w(np.zeros((1, 10, 10), np.uint16)) == [(0.0, 1.0)]
    assert w(np.full((1, 10, 10), 100, np.uint16)) == [(0.0, 100.0)]  # constant: shown, not black
    assert w(np.ones((1, 10, 10), bool)) == [(0.0, 1.0)]
    f = np.linspace(0, 0.01, 400, dtype=np.float32).reshape(1, 20, 20)
    _, hi = w(f)[0]
    assert hi < 0.011  # no integer gap forced on floats
    f[0, 0, 0] = np.inf
    assert all(np.isfinite(w(f)[0]))


def test_ome_names_come_from_the_first_image_only(tmp_path, monkeypatch):
    xml = (
        '<?xml version="1.0"?><OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image ID="Image:0"><Pixels><Channel Name="DAPI"/><Channel Name="CD45 &amp; CD3"/></Pixels></Image>'
        '<Image ID="Image:1" Name="macro"><Pixels><Channel Name="R"/></Pixels></Image></OME>'
    )
    p = tmp_path / "x.ome.tif"
    tifffile.imwrite(p, np.zeros((2, 8, 8), np.uint16))

    class FakeTF:
        ome_metadata = xml

        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tifffile, "TiffFile", FakeTF)
    assert images.ome_channel_names(p) == ["DAPI", "CD45 & CD3"]
    FakeTF.ome_metadata = '<OME xmlns="x"><Image><Pixels><Channel Name="DAPI"/><Channel/></Pixels></Image></OME>'
    assert images.ome_channel_names(p) is None  # an unnamed channel would shift every name after it


def test_bad_pixel_sizes_fall_back(tmp_path):
    for raw in ("Infinity", True, -1, 0, 50, "abc"):
        (tmp_path / "experiment.xenium").write_text(json.dumps({"pixel_size": raw}))
        assert xenium_pixel_size(tmp_path) == 0.2125, raw


def test_an_unreadable_discovered_image_is_skipped_but_a_listed_one_stops_the_build(tmp_path, monkeypatch):
    import yaml

    p = make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    write_pyramid(tmp_path / "src" / "morphology_focus.ome.tif", shape=(1, 256, 256), levels=2)
    doc = yaml.safe_load(p.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    doc["samples"][0].pop("images")  # images: auto finds the morphology file next to the data
    doc["samples"][0]["platform"] = "xenium"
    p.write_text(yaml.safe_dump(doc))

    def refuse(*a, **k):
        raise images.ImageReadRefused("needs imagecodecs", kind="codec")

    monkeypatch.setattr("spatialscape.build.prepare_image", refuse)
    lines: list[str] = []
    r = build_bundle(load_config(p), log=lines.append)
    assert r.problems == [] and r.manifest.samples[0].images == []
    assert any("skipping the image found next to the data: needs imagecodecs" in line for line in lines)
    doc["samples"][0]["images"] = [{"id": "m", "path": "morphology_focus.ome.tif", "kind": "multichannel"}]
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(images.ImageReadRefused):
        build_bundle(load_config(p), log=quiet)


def test_a_channels_list_of_the_wrong_length_is_reported(tmp_path):
    import yaml

    p = make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    write_pyramid(tmp_path / "src" / "if.ome.tif", shape=(2, 256, 256), levels=2)
    doc = yaml.safe_load(p.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    doc["samples"][0]["images"] = [{"id": "if", "path": "if.ome.tif", "kind": "multichannel", "crop": False, "channels": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}]
    p.write_text(yaml.safe_dump(doc))
    lines: list[str] = []
    r = build_bundle(load_config(p), log=lines.append)
    assert any("`channels:` lists 3 entries but if.ome.tif has 2 channels" in line for line in lines)
    assert [c.name for c in r.manifest.samples[0].images[0].channels] == ["DAPI", "ATP1A1/CD45/E-Cadherin"]


def test_fingerprint_watches_the_stain_folder_and_the_image_recipe(tmp_path):
    from spatialscape.config import ImageSpec
    from spatialscape.fingerprint import IMAGE_RECIPE, sample_fingerprint

    d = tmp_path / "outs" / "morphology_focus"
    d.mkdir(parents=True)
    first = d / "morphology_focus_0000.ome.tif"
    first.write_bytes(b"x")
    spec = SampleSpec(id="x", platform="xenium", path=tmp_path / "outs" / "adata.h5ad", images=[ImageSpec(id="m", path=first, kind="multichannel")])
    cfg = load_config(make_synthetic(tmp_path / "src", n_cells=50, n_genes=4))
    fp = sample_fingerprint(spec, cfg, sharded=True)
    assert fp["spec"]["image_recipe"] == IMAGE_RECIPE
    rgb = SampleSpec(id="h", platform="visium", path=tmp_path / "outs" / "adata.h5ad", images=[ImageSpec(id="he", path=first, kind="rgb")])
    assert sample_fingerprint(rgb, cfg, sharded=True)["spec"]["image_recipe"] == IMAGE_RECIPE  # how every image is written
    assert str(d) in fp["inputs"]
    assert "image_recipe" not in sample_fingerprint(SampleSpec(id="n", platform="xenium", path=tmp_path / "outs" / "adata.h5ad", images=[]), cfg, sharded=True)["spec"]


def test_decode_threads_follow_the_allocation(monkeypatch):
    monkeypatch.delenv("TIFFFILE_NUM_THREADS", raising=False)
    monkeypatch.setattr(images.os, "sched_getaffinity", lambda _pid: {0, 1, 2}, raising=False)
    assert images._decode_workers() == 3
    monkeypatch.setenv("TIFFFILE_NUM_THREADS", "2")
    assert images._decode_workers() == 2


def test_a_discovered_image_too_large_for_memory_is_read_smaller(tmp_path, monkeypatch):
    import yaml

    import spatialscape.discover as D

    p = make_synthetic(tmp_path / "src", n_cells=120, n_genes=6)
    write_pyramid(tmp_path / "src" / "morphology_focus.ome.tif")
    doc = yaml.safe_load(p.read_text())
    doc["samples"] = [s for s in doc["samples"] if s["id"] == "sampleA"]
    doc["samples"][0].pop("images")
    doc["samples"][0]["platform"] = "xenium"
    p.write_text(yaml.safe_dump(doc))
    monkeypatch.setattr(D, "AUTO_MORPHOLOGY_UM_PER_PX", 0.05)  # asks for 6,528 px per side
    real = images.prepare_image
    asked: list[int] = []

    def small_machine(path, flip, rotate, max_size, *, rgb):
        asked.append(max_size)
        if max_size > 2000:
            raise images.ImageReadRefused("too big", kind="memory")
        return real(path, flip, rotate, max_size, rgb=rgb)

    monkeypatch.setattr("spatialscape.build.prepare_image", small_machine)
    lines: list[str] = []
    r = build_bundle(load_config(p), log=lines.append)
    assert asked == [6528, 3264, 1632]
    assert any("reading it at most 1,632 px per side" in line for line in lines)
    [img] = r.manifest.samples[0].images
    assert img.pixelSize == pytest.approx(0.2125)  # 1,632 px fits the 1,536 px scan, so it is read whole


def test_a_pyramid_with_4x_steps_is_reduced_from_level_0(tmp_path):
    p = tmp_path / "svs_like.ome.tif"
    base = np.random.default_rng(3).integers(0, 4000, (2, 1024, 1024), dtype=np.uint16)
    with tifffile.TiffWriter(p, bigtiff=True, ome=True) as tw:
        tw.write(base, subifds=1, tile=(256, 256), metadata={"axes": "CYX"})
        tw.write(base[:, ::4, ::4], subfiletype=1, tile=(256, 256))
    out = images.read_image(p, rgb=False, max_size=600)  # level 0 halved (512) beats level 1 as is (256)
    expect = base.reshape(2, 512, 2, 512, 2).astype(np.int64).sum(axis=(2, 4))
    assert np.array_equal(out, ((expect + 2) // 4).astype(np.uint16))


def test_every_image_chunk_is_written_even_when_empty(tmp_path):
    img = np.zeros((2, 600, 700), dtype=np.uint16)
    img[0, :100, :100] = 500
    images.write_ome_zarr(img, tmp_path / "i.ome.zarr", rgb=False)
    level0 = tmp_path / "i.ome.zarr" / "0"
    assert sorted(f.name for f in level0.iterdir() if not f.name.startswith(".")) == [f"{c}.{y}.{x}" for c in range(2) for y in range(2) for x in range(2)]
