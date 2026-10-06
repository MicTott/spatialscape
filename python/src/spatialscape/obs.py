"""Per-observation arrays: positions, shuffle order, ids, categorical codes, continuous values."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr
from zarr.codecs import ZstdCodec

MAX_CHUNK = 1 << 20


def _chunk(n: int) -> int:
    return max(1, min(n, MAX_CHUNK))


def write_obs(
    out_dir: Path,
    *,
    xy: np.ndarray,
    order: np.ndarray,
    ids: list[str],
    cats: dict[str, np.ndarray],
    nums: dict[str, np.ndarray],
    id_block: int = 65536,
) -> None:
    n = xy.shape[0]
    store = zarr.storage.LocalStore(str(out_dir / "obs.zarr"))
    root = zarr.open_group(store, mode="w", zarr_format=3)
    z = ZstdCodec(level=5)
    a = root.create_array("xy", shape=(n, 2), chunks=(_chunk(n), 2), dtype="float32", compressors=[z])
    a[:] = xy.astype(np.float32)
    o = root.create_array("order", shape=(n,), chunks=(_chunk(n),), dtype="uint32", compressors=[z])
    o[:] = order.astype(np.uint32)
    cg = root.create_group("cat")
    for fid, codes in cats.items():
        arr = cg.create_array(fid, shape=(n,), chunks=(_chunk(n),), dtype="uint16", compressors=[z])
        arr[:] = codes.astype(np.uint16)
    ng = root.create_group("num")
    for fid, vals in nums.items():
        arr = ng.create_array(fid, shape=(n,), chunks=(_chunk(n),), dtype="float32", compressors=[z])
        arr[:] = vals.astype(np.float32)
    ids_dir = out_dir / "ids"
    ids_dir.mkdir(parents=True, exist_ok=True)
    for b, start in enumerate(range(0, n, id_block)):
        with open(ids_dir / f"{b}.json", "w") as fh:
            json.dump(ids[start : start + id_block], fh, separators=(",", ":"))
