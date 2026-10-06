"""Read H&E / fluorescence images and write OME-Zarr (NGFF 0.4, zarr v2) pyramids Viv can read."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

from .geometry import transform_image

TILE = 512


def read_image(path: Path) -> np.ndarray:
    """Return (c, y, x). Supports OME-Zarr dirs, tiff, png/jpg."""
    path = Path(path)
    if path.is_dir():
        return _read_ome_zarr(path)
    suf = path.suffix.lower()
    if suf in (".tif", ".tiff", ".btf"):
        import tifffile

        arr = np.asarray(tifffile.imread(path))
    else:
        import imageio.v3 as iio

        arr = np.asarray(iio.imread(path))
    return _to_cyx(arr)


def _to_cyx(arr: np.ndarray) -> np.ndarray:
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr[None, :, :]
    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4) and arr.shape[0] not in (3, 4):
            arr = np.moveaxis(arr, -1, 0)
        if arr.shape[0] == 4:
            arr = arr[:3]
        return np.ascontiguousarray(arr)
    raise ValueError(f"cannot interpret image with shape {arr.shape}")


def _read_ome_zarr(path: Path) -> np.ndarray:
    g = zarr.open_group(str(path), mode="r")
    attrs = dict(g.attrs)
    ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
    if not ms:
        raise ValueError(f"{path}: no multiscales metadata")
    level0 = ms[0]["datasets"][0]["path"]
    axes = [a["name"] if isinstance(a, dict) else a for a in ms[0].get("axes", [])]
    arr = np.asarray(g[level0][:])
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


def downsample2(img: np.ndarray) -> np.ndarray:
    """(c, y, x) -> 2x mean downsample, keeping dtype."""
    c, h, w = img.shape
    h2, w2 = h // 2, w // 2
    if h2 == 0 or w2 == 0:
        return img
    crop = img[:, : h2 * 2, : w2 * 2].astype(np.float32)
    out = crop.reshape(c, h2, 2, w2, 2).mean(axis=(2, 4))
    return np.rint(out).astype(img.dtype)


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


def prepare_image(path: Path, flip: str, rotate: int, max_size: int | None) -> np.ndarray:
    img = read_image(path)
    img = limit_size(img, max_size)
    return transform_image(img, flip, rotate)


def read_image_shape(path: Path) -> tuple[int, int, int]:
    """(c, y, x) at level 0 without loading full data when possible."""
    path = Path(path)
    if path.is_dir():
        g = zarr.open_group(str(path), mode="r")
        attrs = dict(g.attrs)
        ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
        shape = tuple(g[ms[0]["datasets"][0]["path"]].shape)
        axes = [a["name"] if isinstance(a, dict) else a for a in ms[0].get("axes", [])]
        if axes and set(axes) >= {"y", "x"}:
            c = shape[axes.index("c")] if "c" in axes else 1
            return (c, shape[axes.index("y")], shape[axes.index("x")])
        return _to_cyx(np.zeros(shape, dtype=np.uint8)).shape
    return read_image(path).shape


def json_dump(obj, path: Path) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1)
