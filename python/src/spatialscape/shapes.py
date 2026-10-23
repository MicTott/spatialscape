"""Cell boundary shapes cut into square spatial tiles, so the viewer loads only the tiles in view.

A ring belongs to the tile that holds its centroid (it is never clipped); a reader widens its view by `reach`, the
largest distance from a ring's centroid to one of its vertices. Every ring records the bundle row of its cell, so
the viewer colours shapes from the per-cell data it already holds (gene, annotation, filter) without per-tile colours.

Files in the sample folder:
  shapes.json   the index: grid (um per stored unit), tile (um), origin (um), nx, ny, reach (um), layout, and one
                entry per non-empty tile, in row-major order: [ix, iy, offset, bytes, rings, vertices]
  shapes.bin    the tiles' zstd frames back to back (layout "packed", read with byte ranges), or
  shapes/<ix>_<iy>.bin   one file per tile (layout "files", for hosts without range requests)

One tile, decompressed. Little endian; each multi-byte stream is split into byte planes, low byte first, so zstd
sees runs of similar bytes:
  u32 rings, u32 vertices
  row steps   u32[rings], 4 planes   rows ascending; the first step is the first row itself
  counts      u8[rings]              vertices per ring, the closing vertex not repeated
  start x, y  i16[rings] each, 2 planes each       first vertex, grid units from the tile origin
  step x, y   i16[vertices - rings] each, 2 planes each   steps between consecutive vertices of a ring
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numcodecs import Zstd

GRID = 0.1  # um per stored unit: finer than a Xenium pixel (0.2125 um) and any Visium HD vertex
TILE_SIZES = (1024, 512, 256, 128, 64)  # um, largest first
TILE_TARGET = 2048  # at most this many rings in the densest tile, so one tile decodes in well under a frame
SHAPES_RECIPE = 1  # bump when the shape files change for the same inputs
_ZSTD = Zstd(level=9)


@dataclass
class ShapeStats:
    cells: int  # rings written (cells that have a shape)
    vertices: int
    unmatched: int  # rings whose id is not a cell of the sample (dropped)
    degenerate: int  # rings with fewer than 3 vertices (dropped)
    centroid_offset: float  # median distance between a ring's centroid and its cell's position, um
    tile: int
    tiles: int
    bytes: int


def _ranges(starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Concatenated aranges [s, s + c) for every (s, c): the vertex indices of a list of rings."""
    counts = counts.astype(np.int64)
    total = int(counts.sum())
    if total == 0:
        return np.zeros(0, dtype=np.int64)
    ends = np.cumsum(counts)
    base = np.repeat(starts.astype(np.int64) - (ends - counts), counts)
    return base + np.arange(total, dtype=np.int64)


def _planes(a: np.ndarray, dtype: str) -> bytes:
    b = np.ascontiguousarray(a, dtype=dtype).view(np.uint8).reshape(-1, np.dtype(dtype).itemsize)
    return b.T.tobytes()


def _unplanes(buf: memoryview, n: int, dtype: str) -> np.ndarray:
    k = np.dtype(dtype).itemsize
    raw = np.frombuffer(buf, dtype=np.uint8, count=n * k).reshape(k, n)
    return np.ascontiguousarray(raw.T).view(dtype).ravel()


def _row_lookup(obs_ids, poly_ids) -> np.ndarray:
    """Bundle row of each vertex's cell id, -1 for ids that are not cells of the sample."""
    idx = pd.Index(np.asarray(obs_ids, dtype=str))
    if not idx.is_unique:  # keep the first row of a repeated id
        keep = ~idx.duplicated()
        rows = np.flatnonzero(keep)
        found = idx[keep].get_indexer(np.asarray(poly_ids, dtype=str))
        return np.where(found >= 0, rows[np.maximum(found, 0)], -1)
    return idx.get_indexer(np.asarray(poly_ids, dtype=str))


def rings_from_vertices(
    obs_ids: list[str] | np.ndarray, poly_ids: np.ndarray, poly_xy: np.ndarray, *, max_vertices: int = 24
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """Group long-format vertices (one row per vertex, a ring's vertices consecutive and in order) into rings of
    known cells. Returns (rows, starts, counts, unmatched, degenerate) over a vertex array `poly_xy` reordered so
    each ring is contiguous; the closing vertex is dropped and rings longer than `max_vertices` are thinned."""
    rows_v = _row_lookup(obs_ids, poly_ids)
    n_v = len(rows_v)
    if n_v == 0:
        z = np.zeros(0, dtype=np.int64)
        return z, z, z, 0, 0
    # ring boundaries in file order: where the cell changes (unknown ids are dropped below, so merging two
    # consecutive unknown rings is harmless)
    change = np.flatnonzero(rows_v[1:] != rows_v[:-1]) + 1
    starts = np.concatenate([[0], change]).astype(np.int64)
    counts = np.diff(np.concatenate([starts, [n_v]])).astype(np.int64)
    rows = rows_v[starts].astype(np.int64)
    unmatched = int((rows < 0).sum())
    keep = rows >= 0
    starts, counts, rows = starts[keep], counts[keep], rows[keep]
    # a cell listed twice keeps its first ring
    _, first = np.unique(rows, return_index=True)
    starts, counts, rows = starts[np.sort(first)], counts[np.sort(first)], rows[np.sort(first)]
    # drop the repeated closing vertex
    last = starts + counts - 1
    closed = (counts > 1) & np.all(np.isclose(poly_xy[starts], poly_xy[last]), axis=1)
    counts = counts - closed
    degenerate = int((counts < 3).sum())
    ok = counts >= 3
    return rows[ok], starts[ok], counts[ok], unmatched, degenerate


def thin(starts: np.ndarray, counts: np.ndarray, max_vertices: int) -> tuple[np.ndarray, np.ndarray]:
    """Vertex indices of each ring, evenly thinned to at most `max_vertices`; returns (index, new counts)."""
    over = counts > max_vertices
    if not over.any():
        return _ranges(starts, counts), counts
    m = max_vertices
    pick = np.rint(np.arange(m)[None, :] * (counts[over, None] - 1) / (m - 1)).astype(np.int64) + starts[over, None]
    new_counts = counts.copy()
    new_counts[over] = m
    # assemble ring by ring order without a Python loop: under-cap rings keep all their vertices
    idx_under = _ranges(starts, np.where(over, 0, counts))
    pos = np.cumsum(np.concatenate([[0], new_counts[:-1]]))
    out = np.empty(int(new_counts.sum()), dtype=np.int64)
    under_pos = _ranges(pos, np.where(over, 0, counts))
    out[under_pos] = idx_under
    over_pos = (pos[over, None] + np.arange(m)[None, :]).ravel()
    out[over_pos] = pick.ravel()
    return out, new_counts


def choose_tile(centroids: np.ndarray) -> int:
    """The largest tile size whose densest tile holds at most TILE_TARGET rings."""
    for t in TILE_SIZES:
        ij = np.floor(centroids / t).astype(np.int64)
        if len(ij) == 0:
            return t
        _, n = np.unique(ij[:, 0] * 1_000_003 + ij[:, 1], return_counts=True)
        if n.max() <= TILE_TARGET:
            return t
    return TILE_SIZES[-1]


def encode_tile(rows: np.ndarray, counts: np.ndarray, first: np.ndarray, steps: np.ndarray) -> bytes:
    rings = len(rows)
    nv = int(counts.sum())
    row_steps = np.diff(np.concatenate([[0], rows])).astype(np.uint32)
    parts = [
        np.array([rings, nv], dtype="<u4").tobytes(),
        _planes(row_steps, "<u4"),
        counts.astype(np.uint8).tobytes(),
        _planes(first[:, 0], "<i2"),
        _planes(first[:, 1], "<i2"),
        _planes(steps[:, 0], "<i2"),
        _planes(steps[:, 1], "<i2"),
    ]
    return _ZSTD.encode(b"".join(parts))


def decode_tile(frame: bytes, origin: tuple[float, float], grid: float = GRID) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(rows, counts, xy um) of one tile: the reference decoder the viewer's worker mirrors."""
    buf = memoryview(_ZSTD.decode(frame))
    rings, nv = (int(v) for v in np.frombuffer(buf[:8], dtype="<u4"))
    o = 8
    row_steps = _unplanes(buf[o:], rings, "<u4")
    o += 4 * rings
    counts = np.frombuffer(buf[o : o + rings], dtype=np.uint8).astype(np.int64)
    o += rings
    fx = _unplanes(buf[o:], rings, "<i2")
    o += 2 * rings
    fy = _unplanes(buf[o:], rings, "<i2")
    o += 2 * rings
    ns = nv - rings
    sx = _unplanes(buf[o:], ns, "<i2")
    o += 2 * ns
    sy = _unplanes(buf[o:], ns, "<i2")
    rows = np.cumsum(row_steps.astype(np.int64))
    q = np.zeros((nv, 2), dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    step_at = np.setdiff1d(np.arange(nv), starts)
    q[starts, 0], q[starts, 1] = fx, fy
    q[step_at, 0], q[step_at, 1] = sx, sy
    # running sum restarted at every ring start
    cs = np.cumsum(q, axis=0)
    base = np.repeat(cs[starts] - q[starts], counts, axis=0)
    xy = (cs - base) * grid + np.asarray(origin, dtype=np.float64)
    return rows, counts, xy


def write_shapes(
    out_dir: Path,
    obs_ids: list[str] | np.ndarray,
    cell_xy: np.ndarray,
    poly_ids: np.ndarray,
    poly_xy: np.ndarray,
    *,
    max_vertices: int = 24,
    packed: bool = True,
) -> ShapeStats:
    """Tile the rings of known cells and write shapes.json plus shapes.bin (or shapes/<ix>_<iy>.bin)."""
    out_dir = Path(out_dir)
    max_vertices = max(3, min(int(max_vertices), 255))  # a ring's vertex count is one byte
    poly_xy = np.asarray(poly_xy, dtype=np.float64)
    rows, starts, counts, unmatched, degenerate = rings_from_vertices(obs_ids, poly_ids, poly_xy, max_vertices=max_vertices)
    vidx, counts = thin(starts, counts, max_vertices)
    q = np.rint(poly_xy[vidx] / GRID).astype(np.int64)
    if np.abs(q).max(initial=0) > 2**31 - 1:
        raise ValueError("shape coordinates out of range")
    verts = q * GRID  # what the viewer decodes: centroids, tiles and reach are measured on these
    rstart = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.int64)
    n = len(rows)
    if n:
        centroids = np.add.reduceat(verts, rstart, axis=0) / counts[:, None]
        reach = float(np.sqrt(((verts - np.repeat(centroids, counts, axis=0)) ** 2).sum(axis=1)).max())
        dev = float(np.median(np.hypot(*(centroids - np.asarray(cell_xy, dtype=np.float64)[rows]).T)))
    else:
        centroids = np.zeros((0, 2))
        reach, dev = 0.0, 0.0
    tile = choose_tile(centroids)
    origin = np.floor(centroids.min(axis=0) / tile) * tile if n else np.zeros(2)
    ij = np.floor((centroids - origin) / tile).astype(np.int64) if n else np.zeros((0, 2), dtype=np.int64)
    nx = int(ij[:, 0].max()) + 1 if n else 0
    ny = int(ij[:, 1].max()) + 1 if n else 0
    tid = ij[:, 1] * max(nx, 1) + ij[:, 0]
    order = np.lexsort((rows, tid))
    tiles: list[list[int]] = []
    blob = bytearray()
    files_dir = out_dir / "shapes"
    if not packed:
        files_dir.mkdir(parents=True, exist_ok=True)
    bounds = np.flatnonzero(np.diff(tid[order])) + 1
    for group in np.split(order, bounds) if n else []:
        t = int(tid[group[0]])
        ix, iy = t % nx, t // nx
        o_q = np.rint((origin + np.array([ix, iy]) * tile) / GRID).astype(np.int64)
        c = counts[group]
        vi = _ranges(rstart[group], c)
        qt = q[vi]
        st = np.concatenate([[0], np.cumsum(c)[:-1]])
        first = qt[st] - o_q
        step_mask = np.ones(len(qt), dtype=bool)
        step_mask[st] = False
        steps = np.diff(qt, axis=0, prepend=qt[:1])[step_mask]
        if np.abs(first).max(initial=0) > 32767 or np.abs(steps).max(initial=0) > 32767:
            raise ValueError(f"a cell shape spans more than {32767 * GRID:.0f} um; check the boundary file's units and frame")
        frame = encode_tile(rows[group], c, first, steps)
        if packed:
            tiles.append([ix, iy, len(blob), len(frame), len(group), int(c.sum())])
            blob += frame
        else:
            (files_dir / f"{ix}_{iy}.bin").write_bytes(frame)
            tiles.append([ix, iy, 0, len(frame), len(group), int(c.sum())])
    if packed:
        (out_dir / "shapes.bin").write_bytes(bytes(blob))
    index = {
        "version": 1,
        "grid": GRID,
        "tile": tile,
        "origin": [float(origin[0]), float(origin[1])],
        "nx": nx,
        "ny": ny,
        "reach": math.ceil(reach * 100) / 100,
        "layout": "packed" if packed else "files",
        "tiles": tiles,
    }
    (out_dir / "shapes.json").write_text(json.dumps(index, separators=(",", ":")))
    nbytes = sum(t[3] for t in tiles)
    return ShapeStats(
        cells=n,
        vertices=int(counts.sum()),
        unmatched=unmatched,
        degenerate=degenerate,
        centroid_offset=dev,
        tile=tile,
        tiles=len(tiles),
        bytes=nbytes,
    )


def read_shapes(sample_dir: Path) -> dict[int, np.ndarray]:
    """Every ring of a sample, decoded: {row: (k, 2) vertices in um}. For tests and validate."""
    d = Path(sample_dir)
    index = json.loads((d / "shapes.json").read_text())
    blob = (d / "shapes.bin").read_bytes() if index["layout"] == "packed" else None
    out: dict[int, np.ndarray] = {}
    for ix, iy, off, nbytes, _rings, _nv in index["tiles"]:
        frame = blob[off : off + nbytes] if blob is not None else (d / "shapes" / f"{ix}_{iy}.bin").read_bytes()
        o = (index["origin"][0] + ix * index["tile"], index["origin"][1] + iy * index["tile"])
        rows, counts, xy = decode_tile(frame, o, index["grid"])
        for r, a, b in zip(rows, np.cumsum(counts) - counts, np.cumsum(counts), strict=True):
            out[int(r)] = xy[a:b]
    return out
