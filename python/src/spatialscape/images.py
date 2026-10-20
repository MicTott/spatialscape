"""Read H&E / fluorescence images and write OME-Zarr (NGFF 0.4, zarr v2) pyramids Viv can read."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

from .geometry import transform_image

TILE = 512


def read_image(path: Path, *, rgb: bool = True, max_size: int | None = None) -> np.ndarray:
    """Return (c, y, x). Supports OME-Zarr dirs, tiff, png/jpg. With `max_size`, a pyramidal source (OME-Zarr
    multiscales, pyramidal/OME-TIFF) is read at the smallest level that is still at least that large, so a 40x
    scan is never decoded in full just to be shrunk."""
    path = Path(path)
    if path.is_dir():
        return _read_ome_zarr(path, max_size=max_size)
    suf = path.suffix.lower()
    if suf in (".tif", ".tiff", ".btf"):
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            level = _pick_level([tuple(lv.shape) for lv in series.levels], series.axes, max_size) if max_size and len(series.levels) > 1 else 0
            arr = np.asarray(series.levels[level].asarray()) if level else np.asarray(series.asarray())
    else:
        import imageio.v3 as iio

        arr = np.asarray(iio.imread(path))
    return _to_cyx(arr, rgb=rgb)


def _pick_level(shapes: list[tuple[int, ...]], axes: str | list[str], max_size: int | None) -> int:
    """The last pyramid level whose longer side is still >= max_size (finer levels add nothing after limit_size)."""
    if not max_size:
        return 0
    axes = [a.lower() for a in axes]
    yi = axes.index("y") if "y" in axes else -2
    xi = axes.index("x") if "x" in axes else -1
    pick = 0
    for i, shape in enumerate(shapes):
        if max(shape[yi], shape[xi]) >= max_size:
            pick = i
        else:
            break
    return pick


def _to_cyx(arr: np.ndarray, *, rgb: bool = True) -> np.ndarray:
    """(c, y, x). A 4th plane is alpha only for an RGB image; a 4-channel fluorescence stack keeps all four."""
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr[None, :, :]
    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4) and arr.shape[0] not in (3, 4):
            arr = np.moveaxis(arr, -1, 0)
        if arr.shape[0] == 4 and rgb:
            arr = arr[:3]
        return np.ascontiguousarray(arr)
    raise ValueError(f"cannot interpret image with shape {arr.shape}")


def _read_ome_zarr(path: Path, *, max_size: int | None = None) -> np.ndarray:
    g = zarr.open_group(str(path), mode="r")
    attrs = dict(g.attrs)
    ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
    if not ms:
        raise ValueError(f"{path}: no multiscales metadata")
    axes = [a["name"] if isinstance(a, dict) else a for a in ms[0].get("axes", [])]
    paths = [d["path"] for d in ms[0]["datasets"]]
    level = _pick_level([tuple(g[p].shape) for p in paths], axes or ["c", "y", "x"][-len(g[paths[0]].shape) :], max_size) if max_size else 0
    arr = np.asarray(g[paths[level]][:])
    if axes:
        # drop t/z if singleton, then order to c,y,x
        order = []
        for want in ("c", "y", "x"):
            if want in axes:
                order.append(axes.index(want))
        keep = [i for i, a in enumerate(axes) if a in ("c", "y", "x")]
        drop = [i for i in range(arr.ndim) if i not in keep]
        for i in sorted(drop, reverse=True):
            if arr.shape[i] != 1:
                raise ValueError(f"{path}: non-singleton axis {axes[i]} unsupported")
            arr = np.take(arr, 0, axis=i)
        axes2 = [axes[i] for i in keep]
        arr = np.transpose(arr, [axes2.index(a) for a in ("c", "y", "x") if a in axes2])
    return _to_cyx(arr)


def downsample2(img: np.ndarray, strip: int = 1024) -> np.ndarray:
    """(c, y, x) -> 2x mean downsample, keeping dtype. Integer images are summed in uint32 strip by strip, so the
    working memory is a slice of the output, not a float32 copy of the whole image."""
    c, h, w = img.shape
    h2, w2 = h // 2, w // 2
    if h2 == 0 or w2 == 0:
        return img
    out = np.empty((c, h2, w2), dtype=img.dtype)
    integer = np.issubdtype(img.dtype, np.integer)
    for y in range(0, h2, strip):
        y1 = min(h2, y + strip)
        blk = img[:, 2 * y : 2 * y1, : 2 * w2]
        if integer:
            acc = blk[:, 0::2, 0::2].astype(np.uint32)
            acc += blk[:, 1::2, 0::2]
            acc += blk[:, 0::2, 1::2]
            acc += blk[:, 1::2, 1::2]
            out[:, y:y1] = ((acc + 2) >> 2).astype(img.dtype)
        else:
            out[:, y:y1] = blk.astype(np.float32).reshape(c, y1 - y, 2, w2, 2).mean(axis=(2, 4)).astype(img.dtype)
    return out


def limit_size(img: np.ndarray, max_size: int | None) -> np.ndarray:
    if not max_size:
        return img
    while max(img.shape[1], img.shape[2]) > max_size:
        img = downsample2(img)
    return img


def write_ome_zarr(
    img: np.ndarray,
    out_path: Path,
    *,
    rgb: bool,
    channel_names: list[str] | None = None,
    channel_colors: list[str] | None = None,
    windows: list[tuple[float, float]] | None = None,
    min_level_px: int = 256,
) -> list[tuple[int, int, int]]:
    """Write NGFF 0.4 (zarr v2) with relative pyramid scales; returns level shapes."""
    c = img.shape[0]
    levels = [img]
    while max(levels[-1].shape[1], levels[-1].shape[2]) > min_level_px:
        nxt = downsample2(levels[-1])
        if nxt.shape == levels[-1].shape:
            break
        levels.append(nxt)
    store = zarr.storage.LocalStore(str(out_path))
    root = zarr.open_group(store, mode="w", zarr_format=2)
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)
    datasets = []
    for i, lv in enumerate(levels):
        arr = root.create_array(
            str(i),
            shape=lv.shape,
            chunks=(1, min(TILE, lv.shape[1]), min(TILE, lv.shape[2])),
            dtype=lv.dtype,
            compressors=comp,
            fill_value=0,
        )
        arr[:] = lv
        datasets.append({"path": str(i), "coordinateTransformations": [{"type": "scale", "scale": [1, 2**i, 2**i]}]})
    names = channel_names or ([f"{k}" for k in ("R", "G", "B")] if rgb else [f"ch{k}" for k in range(c)])
    colors = channel_colors or (["ff0000", "00ff00", "0000ff"] if rgb else ["ffffff"] * c)
    maxv = 255 if img.dtype == np.uint8 else int(np.iinfo(img.dtype).max) if np.issubdtype(img.dtype, np.integer) else 1
    wins = windows or [(0, maxv)] * c
    root.attrs.update(
        {
            "multiscales": [
                {
                    "version": "0.4",
                    "name": out_path.stem,
                    "axes": [
                        {"name": "c", "type": "channel"},
                        {"name": "y", "type": "space"},
                        {"name": "x", "type": "space"},
                    ],
                    "datasets": datasets,
                    "type": "mean",
                }
            ],
            "omero": {
                "id": 1,
                "name": out_path.stem,
                "version": "0.4",
                "rdefs": {"model": "color" if rgb else "greyscale", "defaultT": 0, "defaultZ": 0},
                "channels": [
                    {
                        "label": names[k],
                        "color": colors[k].lstrip("#"),
                        "active": True,
                        "window": {"min": 0, "max": maxv, "start": wins[k][0], "end": wins[k][1]},
                    }
                    for k in range(c)
                ],
            },
        }
    )
    return [tuple(lv.shape) for lv in levels]


def prepare_image(path: Path, flip: str, rotate: int, max_size: int | None, *, rgb: bool = True) -> np.ndarray:
    img = read_image(path, rgb=rgb, max_size=max_size)
    img = limit_size(img, max_size)
    return transform_image(img, flip, rotate)


def read_image_shape(path: Path, *, rgb: bool = True) -> tuple[int, int, int]:
    """(c, y, x) at level 0 from the file header: TIFF series metadata, PNG/JPEG headers, OME-Zarr attributes."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".tif", ".tiff"):
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            shape, axes = tuple(series.shape), str(series.axes)
        if {"Y", "X"} <= set(axes):
            c = shape[axes.index("C")] if "C" in axes else shape[axes.index("S")] if "S" in axes else 1
            return (3 if c == 4 and rgb else c, shape[axes.index("Y")], shape[axes.index("X")])
        return _to_cyx(np.zeros(shape, dtype=np.uint8), rgb=rgb).shape
    if suffix in (".png", ".jpg", ".jpeg"):
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            c = len(im.getbands())
        return (3 if c == 4 and rgb else c, h, w)
    if path.is_dir():
        g = zarr.open_group(str(path), mode="r")
        attrs = dict(g.attrs)
        ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
        shape = tuple(g[ms[0]["datasets"][0]["path"]].shape)
        axes = [a["name"] if isinstance(a, dict) else a for a in ms[0].get("axes", [])]
        if axes and set(axes) >= {"y", "x"}:
            c = shape[axes.index("c")] if "c" in axes else 1
            return (c, shape[axes.index("y")], shape[axes.index("x")])
        return _to_cyx(np.zeros(shape, dtype=np.uint8), rgb=rgb).shape
    return read_image(path, rgb=rgb).shape


def json_dump(obj, path: Path) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1)
