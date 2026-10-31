"""Read H&E / fluorescence images and write OME-Zarr (NGFF 0.4, zarr v2) pyramids Viv can read."""
from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
from numcodecs import Blosc

from .geometry import transform_image

TILE = 512
TIFF_SUFFIXES = (".tif", ".tiff", ".btf")
CHANNEL_AXES = ("c", "s", "i", "q")  # axis letters tifffile uses for planes: channel, sample, image sequence, unlabelled
J2K_CODES = {34712: "JPEG 2000", 33003: "Aperio JPEG 2000", 33005: "Aperio JPEG 2000"}  # Xenium morphology is 34712
DEFAULT_CHANNEL_COLORS = ["#4c8dff", "#3fd14a", "#ff4fd8", "#ffd23f", "#3fe0e0", "#ff6b4f"]  # blue first: the nuclear stain
BAND_BYTES = 256 * 2**20  # source pixels decoded at once when a large image is downsampled while it is read


class ImageReadRefused(ValueError):
    """An image the build will not read as asked: a missing codec ("codec"), more memory than the machine can spare
    ("memory"), or a file stored as one block per plane that is too large ("layout"). The build reads a discovered
    image smaller after a memory refusal, skips it with a note otherwise, and stops on one the yaml lists."""

    def __init__(self, message: str, *, kind: str = "memory"):
        super().__init__(message)
        self.kind = kind


def _memory_bytes() -> int:
    """Physical memory, or the job's allocation when a cgroup or SLURM says it is smaller (a cluster node reports
    the node's memory, not the job's)."""
    sizes: list[int] = []
    with contextlib.suppress(AttributeError, ValueError, OSError):
        sizes.append(int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")))
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = Path(f).read_text().strip()
            if v.isdigit() and int(v) < 2**60:
                sizes.append(int(v))
        except OSError:
            pass
    slurm = os.environ.get("SLURM_MEM_PER_NODE", "")
    if slurm.isdigit():
        sizes.append(int(slurm) * 2**20)
    return min(sizes) if sizes else 16 * 2**30


def read_limit_bytes() -> int:
    """The most one image may take in memory once read: a sixth of the machine's (or the job's) memory, because the
    build holds a few copies of what it reads (crop, flip, the pyramid, a mask) next to the sample's matrix. With
    `max_size`, a larger source is read at a coarser pyramid level, or downsampled band by band as it is read, so
    only the output has to fit."""
    return _memory_bytes() // 6


def _yx(axes: str | list[str], shape: tuple[int, ...]) -> tuple[int, int]:
    ax = [a.lower() for a in axes]
    yi = ax.index("y") if "y" in ax else len(shape) - 2
    xi = ax.index("x") if "x" in ax else len(shape) - 1
    return shape[yi], shape[xi]


def _decode_workers() -> int:
    """Threads for decoding TIFF tiles: every core this process may use (a cluster job's allocation, not the node's),
    where tifffile's default takes half. TIFFFILE_NUM_THREADS still wins when set."""
    env = os.environ.get("TIFFFILE_NUM_THREADS", "")
    if env.isdigit() and int(env) > 0:
        return int(env)
    try:
        n = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]  (Linux; follows cpusets and SLURM)
    except AttributeError:
        n = os.cpu_count() or 1
    return max(1, min(32, n))


def _check_read_size(path: Path, shape: tuple[int, ...], axes: str | list[str], itemsize: int, *, max_size: int | None) -> None:
    """`shape` is the result's shape. Any lower max_size shrinks it, since a level can always be reduced further."""
    need = int(np.prod(shape)) * itemsize
    limit = read_limit_bytes()
    if need <= limit:
        return
    h, w = _yx(axes, shape)
    if not max_size:
        hint = f"set `max_size:` on this image (for example {min(8192, max(h, w) // 2):d}) so a smaller copy is read"
    else:
        hint = "lower `max_size:` on this image"
    raise ImageReadRefused(f"{path}: this image at {w:,} x {h:,} px needs {need / 2**30:.1f} GB of memory, more than this build allows ({limit / 2**30:.1f} GB); {hint}", kind="memory")


def _require_codec(path: Path, compression: int) -> None:
    """JPEG 2000 TIFFs (Xenium morphology, Aperio J2K slides) decode only through imagecodecs, an optional extra."""
    name = J2K_CODES.get(int(compression))
    if name is None:
        return
    try:
        import imagecodecs  # noqa: F401
    except ImportError as e:
        raise ImageReadRefused(
            f"{path}: this image is {name} compressed (Xenium morphology images are), which needs the imagecodecs package: "
            'pip install "spatialscape[images]". To build without it, set `images: []` on the sample.',
            kind="codec",
        ) from e


def ome_channel_names(path: Path) -> list[str] | None:
    """Channel names of the first image in a TIFF's OME-XML (Xenium writes DAPI, ATP1A1/CD45/E-Cadherin, 18S,
    AlphaSMA/Vimentin). None unless every channel of that image has a name."""
    path = Path(path)
    if path.suffix.lower() not in TIFF_SUFFIXES or not path.is_file():
        return None
    import xml.etree.ElementTree as ET

    import tifffile

    try:
        with tifffile.TiffFile(str(path)) as tf:
            xml = tf.ome_metadata
        root = ET.fromstring(xml) if xml else None
    except Exception:
        return None
    if root is None:
        return None
    local = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731  (OME-XML is namespaced)
    image = next((el for el in root.iter() if local(el) == "Image"), None)
    if image is None:
        return None
    chans = [el for el in image.iter() if local(el) == "Channel"]
    names = [el.get("Name") for el in chans]
    return names if names and all(names) else None  # type: ignore[return-value]


def source_channel_names(path: Path) -> list[str] | None:
    """Channel names a source carries: a TIFF's OME-XML, or, for a Zarr array saved by xarray (a spatialproteomics
    `_image`), the coordinate labels of its channel dimension in the parent group."""
    path = Path(path)
    if path.suffix.lower() in TIFF_SUFFIXES:
        return ome_channel_names(path)
    if not is_zarr_array(path):
        return None
    arr = zarr.open_array(str(path), mode="r")
    dims = arr.attrs.get("_ARRAY_DIMENSIONS") or []
    cdim = next((d for d in dims if str(d)[0].lower() in CHANNEL_AXES), None)
    coord = path.parent / str(cdim) if cdim else None
    if coord is None or not coord.is_dir():
        return None
    try:
        names = [str(v) for v in np.asarray(zarr.open_array(str(coord), mode="r")[:]).tolist()]
    except Exception:
        return None
    return names if len(names) == arr.shape[dims.index(cdim)] and all(names) else None


def auto_windows(img: np.ndarray) -> list[tuple[float, float]]:
    """A display window per channel: the 0.5th to 99.9th percentile of the finite, non-zero pixels. Without it a
    16-bit fluorescence channel whose signal sits in the low thousands is drawn against 0..65535 and looks black."""
    out: list[tuple[float, float]] = []
    integer = np.issubdtype(img.dtype, np.integer) or img.dtype == bool
    step = max(1, int(np.sqrt(img.shape[1] * img.shape[2] / 4e6)))  # about 4 M pixels per channel are plenty
    for c in range(img.shape[0]):
        v = img[c, ::step, ::step].ravel()
        v = v.astype(np.uint8) if v.dtype == bool else v
        v = v[np.isfinite(v) & (v > 0)] if not integer else v[v > 0]
        if v.size == 0:
            out.append((0.0, 1.0))
            continue
        lo, hi = (float(x) for x in np.percentile(v, [0.5, 99.9]))
        if integer:  # whole numbers for whole-number data
            lo, hi = float(np.floor(lo)), float(np.ceil(hi))
        if hi <= lo:  # a constant channel: show it rather than draw it black
            lo, hi = 0.0, lo if lo > 0 else 1.0
        elif integer and hi < lo + 1:
            hi = lo + 1
        out.append((lo, hi))
    return out


def _choose_level(shapes: list[tuple[int, ...]], axes: str | list[str], max_size: int | None) -> tuple[int, int]:
    """(pyramid level, downsampling factor) for a read of at most `max_size` px per side: the level that yields the
    largest result, the cheapest one on a tie. A level within the limit is read as is; a larger one is reduced by
    a power of two while it is read (the only way to honour max_size for a file without pyramid levels)."""
    if not max_size:
        return 0, 1
    best: tuple[int, int, int] | None = None  # (-output side, source side, level), smallest wins
    factors: dict[int, int] = {}
    for i, shape in enumerate(shapes):
        side = max(_yx(axes, shape))
        f = 1
        while side // f > max_size:
            f *= 2
        factors[i] = f
        key = (-(side // f), side, i)
        if best is None or key < best:
            best = key
    level = best[2] if best else 0
    return level, factors.get(level, 1)


def _to_cyx_axes(arr: np.ndarray, axes: str) -> np.ndarray:
    """A block read in the source's axis order -> (c, y, x). Singleton t/z/q axes are dropped."""
    ax = [a.lower() for a in axes]
    keep_c = next((a for a in CHANNEL_AXES if a in ax and arr.shape[ax.index(a)] > 1), None)
    for i in sorted(range(arr.ndim), reverse=True):
        if ax[i] not in ("y", "x") and ax[i] != keep_c:
            if arr.shape[i] != 1:
                raise ValueError(f"cannot read axis {ax[i]!r} of length {arr.shape[i]} (only one channel axis is supported)")
            arr = np.take(arr, 0, axis=i)
            ax.pop(i)
    order = ([ax.index(keep_c)] if keep_c else []) + [ax.index("y"), ax.index("x")]
    arr = np.transpose(arr, order)
    return arr if keep_c else arr[None]


def _reduce(block: np.ndarray, f: int) -> np.ndarray:
    """(c, y, x) block whose y and x are multiples of f -> mean over f x f cells, keeping the dtype."""
    if f == 1:
        return block
    c, h, w = block.shape
    if np.issubdtype(block.dtype, np.integer):
        acc = block.reshape(c, h // f, f, w // f, f).sum(axis=(2, 4), dtype=np.int64)
        return ((acc + (f * f) // 2) // (f * f)).astype(block.dtype)
    return block.astype(np.float32).reshape(c, h // f, f, w // f, f).mean(axis=(2, 4)).astype(block.dtype)


def _read_reduced(src, axes: str, f: int, path: Path) -> np.ndarray:
    """Read an array-like (zarr view of a TIFF level, or an OME-Zarr array) reduced by `f` per side, one band of rows
    at a time, so memory is the output plus one band, never the whole source. Files stored as one strip per plane
    are read a channel plane at a time instead."""
    ax = [a.lower() for a in axes]
    shape = tuple(src.shape)
    yi, xi = ax.index("y"), ax.index("x")
    h, w = (shape[yi] // f) * f, (shape[xi] // f) * f
    cax = next((i for i, a in enumerate(ax) if a in CHANNEL_AXES and shape[i] > 1), None)
    nch = shape[cax] if cax is not None else 1
    itemsize = np.dtype(src.dtype).itemsize
    out = np.empty((nch, h // f, w // f), dtype=src.dtype)
    chunk_rows = int(getattr(src, "chunks", shape)[yi]) or shape[yi]
    if chunk_rows >= shape[yi]:  # one strip per plane: every band would decode the whole plane again
        plane = h * w * itemsize
        if plane > read_limit_bytes():
            raise ImageReadRefused(f"{path}: this file stores each {w:,} x {h:,} px plane as one block ({plane / 2**30:.1f} GB), more than this build can read at once; convert it to a tiled or pyramidal OME-TIFF", kind="layout")
        for c in range(nch):
            sel = [0] * len(shape)
            sel[yi], sel[xi] = slice(0, h), slice(0, w)
            if cax is not None:
                sel[cax] = c
            blk = np.asarray(src[tuple(sel)])
            out[c] = _reduce(blk[None], f)[0]
        return out
    step = math.lcm(f, chunk_rows)  # bands end on chunk boundaries, so no chunk is decoded twice
    rows = max(step, BAND_BYTES // max(1, w * nch * itemsize) // step * step)
    for y0 in range(0, h, rows):
        y1 = min(h, y0 + rows)
        # slice(0, 1), not 0, so singleton t/z axes stay in the block and _to_cyx_axes can drop them by name
        sel = [slice(None) if i == cax else slice(0, 1) for i in range(len(shape))]
        sel[yi], sel[xi] = slice(y0, y1), slice(0, w)
        out[:, y0 // f : y1 // f] = _reduce(_to_cyx_axes(np.asarray(src[tuple(sel)]), axes), f)
    return out


def read_image(path: Path, *, rgb: bool = True, max_size: int | None = None) -> np.ndarray:
    """Return (c, y, x). Supports OME-Zarr dirs, TIFF / OME-TIFF / BigTIFF, PNG/JPEG. With `max_size`, the result is
    at most that many px per side and so is the memory it takes: a pyramidal source is read at the level that gives
    the largest result within the limit, and a larger level (or a file without pyramid levels) is reduced band by
    band while it is read, so a 40x scan is never held whole."""
    path = Path(path)
    if path.is_dir():
        return _read_ome_zarr(path, rgb=rgb, max_size=max_size)
    if path.suffix.lower() in TIFF_SUFFIXES:
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            _require_codec(path, series.keyframe.compression)
            shapes = [tuple(lv.shape) for lv in series.levels]
            level, f = _choose_level(shapes, series.axes, max_size)
            lv = series.levels[level]
            out_shape = tuple(n // f if a in "YX" else n for n, a in zip(lv.shape, series.axes, strict=True))
            _check_read_size(path, out_shape, series.axes, series.dtype.itemsize, max_size=max_size)
            if f == 1:  # tifffile decodes with half the cores unless told otherwise; JPEG 2000 is CPU bound
                arr = _to_cyx_axes(np.asarray(lv.asarray(maxworkers=_decode_workers())), series.axes)
            else:  # series.aszarr(level=): level 0 of a pyramid would otherwise open as the whole multiscale group
                arr = _read_reduced(zarr.open(series.aszarr(level=level), mode="r"), series.axes, f, path)
        return _drop_alpha(arr, rgb)
    import imageio.v3 as iio

    return _to_cyx(np.asarray(iio.imread(path)), rgb=rgb)


def _drop_alpha(arr: np.ndarray, rgb: bool) -> np.ndarray:
    """A 4th plane is alpha only for an RGB image; a 4-channel fluorescence stack keeps all four."""
    if rgb and arr.shape[0] == 4:
        arr = arr[:3]
    return np.ascontiguousarray(arr)


def _to_cyx(arr: np.ndarray, *, rgb: bool = True) -> np.ndarray:
    """(c, y, x) for an array without axis labels (PNG/JPEG)."""
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        return arr[None, :, :]
    if arr.ndim == 3:
        if arr.shape[-1] in (3, 4) and arr.shape[0] not in (3, 4):
            arr = np.moveaxis(arr, -1, 0)
        return _drop_alpha(arr, rgb)
    raise ValueError(f"cannot interpret image with shape {arr.shape}")


def _read_ome_zarr(path: Path, *, rgb: bool = True, max_size: int | None = None) -> np.ndarray:
    """An OME-Zarr pyramid, or a bare Zarr array with `_ARRAY_DIMENSIONS` (one level)."""
    if is_zarr_array(path):
        arr = zarr.open_array(str(path), mode="r")
        axes = _zarr_array_axes(arr)
        _level, f = _choose_level([tuple(arr.shape)], axes, max_size)
        out_shape = tuple(n // f if a.lower() in "yx" else n for n, a in zip(arr.shape, axes, strict=True))
        _check_read_size(path, out_shape, axes, arr.dtype.itemsize, max_size=max_size)
        img = _to_cyx_axes(np.asarray(arr[:]), axes) if f == 1 else _read_reduced(arr, axes, f, path)
        return _drop_alpha(img, rgb)
    g = zarr.open_group(str(path), mode="r")
    attrs = dict(g.attrs)
    ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
    if not ms:
        raise ValueError(f"{path}: no multiscales metadata")
    paths = [d["path"] for d in ms[0]["datasets"]]
    ndim = len(g[paths[0]].shape)
    axes = "".join((a["name"] if isinstance(a, dict) else a)[0] for a in ms[0].get("axes", [])) or "cyx"[-ndim:]
    level, f = _choose_level([tuple(g[p].shape) for p in paths], axes, max_size)
    arr = g[paths[level]]
    out_shape = tuple(n // f if a.lower() in "yx" else n for n, a in zip(arr.shape, axes, strict=True))
    _check_read_size(path, out_shape, axes, arr.dtype.itemsize, max_size=max_size)
    img = _to_cyx_axes(np.asarray(arr[:]), axes) if f == 1 else _read_reduced(arr, axes, f, path)
    return _drop_alpha(img, rgb)


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
            # every chunk exists: a static host answers a missing one with 403 (S3 without list access), which the
            # viewer's zarr reader treats as an error, and Viv then drops the whole tile, every channel of it
            config={"write_empty_chunks": True},
        )
        arr[:] = lv
        datasets.append({"path": str(i), "coordinateTransformations": [{"type": "scale", "scale": [1, 2**i, 2**i]}]})
    root.attrs.update(_ome_attrs(out_path.stem, c, img.dtype, rgb, channel_names, channel_colors, windows, datasets))
    return [tuple(lv.shape) for lv in levels]


def _ome_attrs(name: str, c: int, dtype, rgb: bool, channel_names, channel_colors, windows, datasets: list[dict]) -> dict:
    """NGFF 0.4 `multiscales` and `omero` attributes for a (c, y, x) pyramid."""
    names = channel_names or ([f"{k}" for k in ("R", "G", "B")] if rgb else [f"ch{k}" for k in range(c)])
    colors = channel_colors or (["ff0000", "00ff00", "0000ff"] if rgb else ["ffffff"] * c)
    maxv = 255 if dtype == np.uint8 else int(np.iinfo(dtype).max) if np.issubdtype(dtype, np.integer) else 1
    wins = windows or [(0, maxv)] * c
    return {
        "multiscales": [
            {
                "version": "0.4",
                "name": name,
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
            "name": name,
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


def _zarr_array_axes(arr) -> str:
    dims = arr.attrs.get("_ARRAY_DIMENSIONS") or []
    return "".join(str(d)[0].lower() for d in dims) if len(dims) == arr.ndim else "cyx"[-arr.ndim :]


def is_zarr_array(path: Path) -> bool:
    path = Path(path)
    return path.is_dir() and ((path / ".zarray").exists() or (path / "zarr.json").exists()) and ome_zarr_info(path) is None


def streamable(path: Path) -> bool:
    """Sources the band-by-band writer reads: TIFF (tiled or striped, pyramidal or not), an OME-Zarr pyramid, a Zarr array."""
    path = Path(path)
    return path.suffix.lower() in TIFF_SUFFIXES or ome_zarr_info(path) is not None or is_zarr_array(path)


def source_levels(path: Path) -> tuple[list[tuple[int, ...]], str]:
    """Level shapes (finest first) and the axes letters of a TIFF, an OME-Zarr pyramid or a single Zarr array, from
    headers alone."""
    path = Path(path)
    if path.suffix.lower() in TIFF_SUFFIXES:
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            _require_codec(path, series.keyframe.compression)
            return [tuple(lv.shape) for lv in series.levels], str(series.axes).lower()
    info = ome_zarr_info(path)
    if info is not None:
        return info.levels, info.axes
    arr = zarr.open_array(str(path), mode="r")
    return [tuple(arr.shape)], _zarr_array_axes(arr)


@contextlib.contextmanager
def open_level(path: Path, level: int):
    """One pyramid level of a source as a chunked array to slice from, with its axes letters; a TIFF stays open
    while it is read and its tiles are decoded on demand."""
    path = Path(path)
    if path.suffix.lower() in TIFF_SUFFIXES:
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            _require_codec(path, series.keyframe.compression)
            yield zarr.open(series.aszarr(level=level, maxworkers=_decode_workers()), mode="r"), str(series.axes).lower()
        return
    info = ome_zarr_info(path)
    if info is not None:
        g = zarr.open_group(str(path), mode="r")
        ms = _multiscales(dict(g.attrs))
        assert ms is not None
        yield g[ms["datasets"][level]["path"]], info.axes
        return
    arr = zarr.open_array(str(path), mode="r")
    yield arr, _zarr_array_axes(arr)


def crop_window(
    shape_hw: tuple[int, int], pixel_size: float, translate: tuple[float, float], bbox: tuple[float, float, float, float], margin: float = 0.03
) -> tuple[tuple[int, int, int, int], tuple[float, float]]:
    """The pixel window (y0, y1, x0, x1) of an image of `shape_hw` placed at `translate` (um) with `pixel_size` um/px
    that covers the points' bounding box plus a margin (a fraction of its longer side), with the window's translate.
    The whole image when the points lie outside it or already fill it."""
    x0, y0, x1, y1 = bbox
    pad = margin * max(x1 - x0, y1 - y0)
    h, w = shape_hw
    px0 = int(np.clip(np.floor((x0 - pad - translate[0]) / pixel_size), 0, w))
    px1 = int(np.clip(np.ceil((x1 + pad - translate[0]) / pixel_size), 0, w))
    py0 = int(np.clip(np.floor((y0 - pad - translate[1]) / pixel_size), 0, h))
    py1 = int(np.clip(np.ceil((y1 + pad - translate[1]) / pixel_size), 0, h))
    if px1 - px0 < 2 or py1 - py0 < 2:
        return (0, h, 0, w), translate
    return (py0, py1, px0, px1), (translate[0] + px0 * pixel_size, translate[1] + py0 * pixel_size)


def stream_ome_zarr(
    path: Path,
    out_path: Path,
    *,
    rgb: bool,
    level: int = 0,
    factor: int = 1,
    window: tuple[int, int, int, int] | None = None,
    channel_names: list[str] | None = None,
    channel_colors: list[str] | None = None,
    windows: list[tuple[float, float] | None] | None = None,
    min_level_px: int = 256,
) -> tuple[list[tuple[int, int, int]], list[tuple[float, float]]]:
    """Write an NGFF 0.4 pyramid from one level of a TIFF, OME-Zarr or Zarr-array source, reduced by `factor` and cut
    to `window` (y0, y1, x0, x1 in reduced pixels), one band of rows at a time: memory is one band, never the image.
    Coarser levels are made from the written level below them, band by band too. Display windows that are None are
    fitted on a coarse level once it exists. Returns the level shapes and the windows used."""
    out_path = Path(out_path)
    store = zarr.storage.LocalStore(str(out_path))
    root = zarr.open_group(store, mode="w", zarr_format=2)
    comp = Blosc(cname="zstd", clevel=5, shuffle=Blosc.SHUFFLE)

    def new_level(i: int, c: int, h: int, w: int, dtype):
        return root.create_array(str(i), shape=(c, h, w), chunks=(1, min(TILE, h), min(TILE, w)), dtype=dtype, compressors=comp, fill_value=0, config={"write_empty_chunks": True})

    with open_level(path, level) as (src, axes):
        shape = tuple(src.shape)
        ax = list(axes)
        yi, xi = ax.index("y"), ax.index("x")
        cax = next((i for i, a in enumerate(ax) if a in CHANNEL_AXES and shape[i] > 1), None)
        nch_src = shape[cax] if cax is not None else 1
        drop_alpha = rgb and nch_src == 4
        nch = 3 if drop_alpha else nch_src
        f = factor
        full_h, full_w = shape[yi] // f, shape[xi] // f
        y0, y1, x0, x1 = window or (0, full_h, 0, full_w)
        h, w = y1 - y0, x1 - x0
        dtype = np.dtype(src.dtype)
        itemsize = dtype.itemsize
        out0 = new_level(0, nch, h, w, dtype)
        chunk_rows = int(getattr(src, "chunks", shape)[yi]) or shape[yi]
        if chunk_rows >= shape[yi]:  # one strip per plane: a band would decode the plane again, so read it once per channel
            plane = shape[yi] * shape[xi] * itemsize
            if plane > read_limit_bytes():
                raise ImageReadRefused(
                    f"{path}: this file stores each {shape[xi]:,} x {shape[yi]:,} px plane as one block ({plane / 2**30:.1f} GB), more than this build can read at once; convert it to a tiled or pyramidal OME-TIFF",
                    kind="layout",
                )
            for c in range(nch):
                sel: list = [slice(0, 1)] * len(shape)
                sel[yi], sel[xi] = slice(y0 * f, y1 * f), slice(x0 * f, x1 * f)
                if cax is not None:
                    sel[cax] = slice(c, c + 1)
                out0[c] = _reduce(_to_cyx_axes(np.asarray(src[tuple(sel)]), axes), f)[0]
        else:
            step = math.lcm(f * TILE, chunk_rows)  # output bands end on tile rows, source reads on chunk rows
            rows = max(step, BAND_BYTES // max(1, w * f * nch_src * itemsize) // step * step)
            for sy in range(y0 * f, y1 * f, rows):
                sy1 = min(y1 * f, sy + rows)
                sel = [slice(None) if i == cax else slice(0, 1) for i in range(len(shape))]
                sel[yi], sel[xi] = slice(sy, sy1), slice(x0 * f, x1 * f)
                blk = _to_cyx_axes(np.asarray(src[tuple(sel)]), axes)
                if drop_alpha:
                    blk = blk[:3]
                out0[:, (sy - y0 * f) // f : (sy1 - y0 * f) // f, :] = _reduce(np.ascontiguousarray(blk), f)
    levels = [(nch, h, w)]
    i = 0
    while max(levels[-1][1], levels[-1][2]) > min_level_px:
        _c, ph, pw = levels[-1]
        nh, nw = ph // 2, pw // 2
        if nh == 0 or nw == 0:
            break
        prev = root[str(i)]
        nxt = new_level(i + 1, nch, nh, nw, dtype)
        band = 2 * TILE * max(1, BAND_BYTES // max(1, pw * nch * itemsize * 2 * TILE))  # even, tile-aligned source rows
        for py in range(0, 2 * nh, band):
            py1 = min(2 * nh, py + band)
            nxt[:, py // 2 : py1 // 2, :] = downsample2(np.asarray(prev[:, py:py1, : 2 * nw]))
        levels.append((nch, nh, nw))
        i += 1
    wins: list[tuple[float, float] | None] = list(windows) if windows else [None] * nch
    if any(wn is None for wn in wins):
        coarse = next((j for j, lv in enumerate(levels) if max(lv[1], lv[2]) <= 2048), len(levels) - 1)
        fitted = auto_windows(np.asarray(root[str(coarse)][:]))
        wins = [wn if wn is not None else fitted[k] for k, wn in enumerate(wins)]
    datasets = [{"path": str(j), "coordinateTransformations": [{"type": "scale", "scale": [1, 2**j, 2**j]}]} for j in range(len(levels))]
    root.attrs.update(_ome_attrs(out_path.stem, nch, dtype, rgb, channel_names, channel_colors, wins, datasets))
    return levels, [tuple(wn) for wn in wins]  # type: ignore[misc]


def prepare_image(path: Path, flip: str, rotate: int, max_size: int | None, *, rgb: bool = True, transpose: bool = False, image_flip: str = "") -> np.ndarray:
    """Read, then put the image into the coordinates' frame: the image's own transpose and flips first (an export
    whose coordinates were transposed), then the sample's flip and rotation, which points and polygons share."""
    img = read_image(path, rgb=rgb, max_size=max_size)
    img = limit_size(img, max_size)
    if transpose:
        img = np.swapaxes(img, 1, 2)
    if "x" in image_flip:
        img = img[:, :, ::-1]
    if "y" in image_flip:
        img = img[:, ::-1, :]
    return transform_image(np.ascontiguousarray(img), flip, rotate)


def read_image_shape(path: Path, *, rgb: bool = True) -> tuple[int, int, int]:
    """(c, y, x) at level 0 from the file header only: TIFF series metadata, PNG/JPEG headers, OME-Zarr attributes."""
    path = Path(path)
    suffix = path.suffix.lower()

    def from_shape(shape: tuple[int, ...], axes: str | None) -> tuple[int, int, int]:
        ax = (axes or "").lower()
        if {"y", "x"} <= set(ax):
            cax = next((a for a in CHANNEL_AXES if a in ax), None)
            c = shape[ax.index(cax)] if cax else 1
            return (3 if c == 4 and rgb else c, shape[ax.index("y")], shape[ax.index("x")])
        dims = [n for n in shape if n != 1] or [1, 1]
        if len(dims) == 2:
            return (1, dims[0], dims[1])
        c, h, w = (dims[2], dims[0], dims[1]) if dims[-1] in (3, 4) and dims[0] not in (3, 4) else (dims[0], dims[-2], dims[-1])
        return (3 if c == 4 and rgb else c, h, w)

    if suffix in TIFF_SUFFIXES:
        import tifffile

        with tifffile.TiffFile(str(path)) as tf:
            series = tf.series[0]
            return from_shape(tuple(series.shape), str(series.axes))
    if path.is_dir():  # an OME-Zarr pyramid or a bare Zarr array
        shapes, axes = source_levels(path)
        return from_shape(shapes[0], axes or None)
    from PIL import Image

    try:
        with Image.open(path) as im:
            w, h = im.size
            c = len(im.getbands())
        return (3 if c == 4 and rgb else c, h, w)
    except Exception:
        return read_image(path, rgb=rgb).shape


@dataclass
class OmeZarrInfo:
    """What the build needs to know about an OME-Zarr pyramid it will copy as is."""

    axes: str  # e.g. "cyx" or "tczyx", one letter per dimension of every level
    levels: list[tuple[int, ...]]  # level shapes, finest first
    dtype: np.dtype
    channels: int
    size: tuple[int, int]  # level-0 (height, width)
    channel_names: list[str] | None  # omero labels, when every channel has one
    channel_colors: list[str] | None  # omero colours as #rrggbb
    channel_windows: list[tuple[float, float] | None] | None  # omero windows narrower than the dtype's range
    zarr_format: int


def _multiscales(attrs: dict) -> dict | None:
    ms = attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales")
    return ms[0] if ms else None


def ome_zarr_info(path: Path) -> OmeZarrInfo | None:
    """The pyramid's layout and channel metadata, from its attributes alone; None when `path` is not an OME-Zarr."""
    path = Path(path)
    if not path.is_dir():
        return None
    try:
        g = zarr.open_group(str(path), mode="r")
    except Exception:
        return None
    attrs = dict(g.attrs)
    ms = _multiscales(attrs)
    if not ms:
        return None
    levels = [tuple(g[d["path"]].shape) for d in ms["datasets"]]
    lv0 = g[ms["datasets"][0]["path"]]
    axes = "".join((a["name"] if isinstance(a, dict) else a)[0].lower() for a in ms.get("axes", [])) or "tczyx"[-len(levels[0]) :]
    channels = levels[0][axes.index("c")] if "c" in axes else 1
    size = (levels[0][axes.index("y")], levels[0][axes.index("x")])
    omero = attrs.get("omero") or attrs.get("ome", {}).get("omero") or {}
    chans = omero.get("channels") or []
    names = colors = windows = None
    if len(chans) == channels:
        labels = [c.get("label") for c in chans]
        names = [str(label) for label in labels] if all(labels) else None
        colors = [f"#{str(c.get('color', 'ffffff')).lstrip('#').lower()}" for c in chans]
        maxv = float(np.iinfo(lv0.dtype).max) if np.issubdtype(lv0.dtype, np.integer) else 1.0
        windows = []
        for c in chans:
            w = c.get("window") or {}
            start, end = w.get("start"), w.get("end")
            full = start in (None, 0) and (end is None or float(end) >= maxv)
            windows.append(None if full or start is None or end is None or float(end) <= float(start) else (float(start), float(end)))
    return OmeZarrInfo(axes, levels, lv0.dtype, int(channels), (int(size[0]), int(size[1])), names, colors, windows, int((getattr(g, "metadata", None) and g.metadata.zarr_format) or 2))


def ome_zarr_coarse(path: Path, info: OmeZarrInfo, max_px: int = 2048) -> np.ndarray:
    """One coarse level as (c, y, x), the finest level within `max_px` per side: enough pixels to fit windows on."""
    g = zarr.open_group(str(path), mode="r")
    ms = _multiscales(dict(g.attrs))
    assert ms is not None
    yi, xi = info.axes.index("y"), info.axes.index("x")
    pick = len(info.levels) - 1
    for i, shape in enumerate(info.levels):
        if max(shape[yi], shape[xi]) <= max_px:
            pick = i
            break
    arr = g[ms["datasets"][pick]["path"]]
    index = tuple(slice(None) if a in "cyx" else 0 for a in info.axes)  # t and z: the first plane
    sub = np.asarray(arr[index])
    axes = "".join(a for a in info.axes if a in "cyx")
    return _to_cyx_axes(sub, axes)


def _link_or_copy(src: str, dst: str) -> None:
    try:
        os.link(src, dst)  # same filesystem: no second copy of the pixels
    except OSError:
        shutil.copy2(src, dst)


def copy_ome_zarr(src: Path, dst: Path) -> None:
    """The pyramid into the bundle as it is, hard-linked where the filesystem allows, copied otherwise."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, copy_function=_link_or_copy)


def json_dump(obj, path: Path) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1)
