"""Molecules (transcripts) cut into square spatial tiles, so the viewer loads only the tiles in view.

Input: a long-format table, one row per transcript: 10x's transcripts.parquet (feature_name, x_location,
y_location, qv, cell_id, overlaps_nucleus; the default column names), or any Parquet / CSV / TSV table with the
columns named in the yaml (MERSCOPE's detected_transcripts.csv, CosMx's tx_file.csv). It is read one row group or
text block at a time, so a 137 M-row section needs about 7 bytes per kept row of memory and never the table whole.
Rows below `min_qv` and control features (negative probes, blanks, system controls) are dropped.

Files in the sample folder:
  molecules.json  the index: grid (um per stored unit), tile (um), origin, nx, ny, genes (feature names, the
                  gene id of a molecule is an index into it), counts (molecules per gene, whole sample), count,
                  layout, and one entry per non-empty tile, row-major: [ix, iy, offset, bytes, molecules]
  molecules.bin   the tiles' zstd frames back to back (layout "packed"), or molecules/<ix>_<iy>.bin ("files")

One tile, decompressed. Little endian; multi-byte streams are split into byte planes, low byte first:
  u32 n, u32 runs
  run gene    u16[runs], 2 planes   gene ids ascending
  run count   u32[runs], 4 planes   molecules of that gene, in order
  dx, dy      i16[n] each, 2 planes each   steps between consecutive molecules on the grid (the first from the
                                           tile origin); within a gene the order is a Morton curve, so steps are short
  flags       u8[n]                 bit 0 assigned to a cell, bit 1 overlaps the nucleus
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numcodecs import Zstd

from .images import read_limit_bytes
from .tables import iter_batches, table_columns

GRID = 1 / 64  # um per stored unit, 10x's own transcript precision
TILE_SIZES = (512, 256, 128, 64)  # um, largest first; 512 um is 32,768 units, the int16 step range
TILE_TARGET = 50_000  # molecules in the densest tile
MOLECULES_RECIPE = 1
# 10x: NegControlProbe, NegControlCodeword, UnassignedCodeword, Deprecated, Intergenic, Genomic; Vizgen: Blank-<n>;
# NanoString: NegPrb<n>, SystemControl<n>, FalseCode<n>
CONTROL_RE = re.compile(r"^(NegControlProbe|NegControlCodeword|UnassignedCodeword|BLANK|Deprecated|Intergenic|Genomic|NegPrb|SystemControl|FalseCode)", re.I)
_ZSTD = Zstd(level=7)
ROW_BYTES = 7  # gene u16 + x u16 + y u16 + flags u8 per kept row while collecting


@dataclass
class MoleculeStats:
    count: int  # molecules written
    read: int  # rows in the table
    low_quality: int  # rows below min_qv
    controls: int  # control-feature rows (after the quality filter)
    genes: int
    tile: int
    tiles: int
    bytes: int
    seconds: float


def _planes(a: np.ndarray, dtype: str) -> bytes:
    b = np.ascontiguousarray(a, dtype=dtype).view(np.uint8).reshape(-1, np.dtype(dtype).itemsize)
    return b.T.tobytes()


def _unplanes(buf: memoryview, n: int, dtype: str) -> np.ndarray:
    k = np.dtype(dtype).itemsize
    raw = np.frombuffer(buf, dtype=np.uint8, count=n * k).reshape(k, n)
    return np.ascontiguousarray(raw.T).view(dtype).ravel()


def morton(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Interleave the bits of two uint16 arrays into one uint32 key: a Z-order curve."""

    def spread(v: np.ndarray) -> np.ndarray:
        v = v.astype(np.uint32)
        v = (v | (v << 8)) & 0x00FF00FF
        v = (v | (v << 4)) & 0x0F0F0F0F
        v = (v | (v << 2)) & 0x33333333
        v = (v | (v << 1)) & 0x55555555
        return v

    return spread(x) | (spread(y) << 1)


def encode_tile(gene: np.ndarray, qx: np.ndarray, qy: np.ndarray, flags: np.ndarray) -> bytes:
    """One tile from its molecules (grid units from the tile origin), sorted by gene then Morton order."""
    order = np.lexsort((morton(qx, qy), gene))
    gene, qx, qy, flags = gene[order], qx[order], qy[order], flags[order]
    genes, counts = np.unique(gene, return_counts=True)
    dx = np.diff(qx.astype(np.int32), prepend=0).astype(np.int16)
    dy = np.diff(qy.astype(np.int32), prepend=0).astype(np.int16)
    parts = [
        np.array([len(gene), len(genes)], dtype="<u4").tobytes(),
        _planes(genes, "<u2"),
        _planes(counts, "<u4"),
        _planes(dx, "<i2"),
        _planes(dy, "<i2"),
        flags.astype(np.uint8).tobytes(),
    ]
    return _ZSTD.encode(b"".join(parts))


def decode_tile(frame: bytes, origin: tuple[float, float], grid: float = GRID) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(gene ids, xy um, flags) of one tile: the reference decoder the viewer's worker mirrors."""
    buf = memoryview(_ZSTD.decode(frame))
    n, runs = (int(v) for v in np.frombuffer(buf[:8], dtype="<u4"))
    o = 8
    genes = _unplanes(buf[o:], runs, "<u2")
    o += 2 * runs
    counts = _unplanes(buf[o:], runs, "<u4")
    o += 4 * runs
    dx = _unplanes(buf[o:], n, "<i2")
    o += 2 * n
    dy = _unplanes(buf[o:], n, "<i2")
    o += 2 * n
    flags = np.frombuffer(buf[o : o + n], dtype=np.uint8)
    gene = np.repeat(genes.astype(np.uint16), counts.astype(np.int64))
    xy = np.column_stack([np.cumsum(dx.astype(np.int64)), np.cumsum(dy.astype(np.int64))]) * grid + np.asarray(origin, dtype=np.float64)
    return gene, xy, flags


def _tile_size(counts: np.ndarray, cell_um: int) -> int:
    """The largest tile size whose densest tile holds at most TILE_TARGET molecules, from a histogram at cell_um."""
    for t in TILE_SIZES:
        k = t // cell_um
        h, w = counts.shape
        ph, pw = (-h) % k, (-w) % k
        c = np.pad(counts, ((0, ph), (0, pw))).reshape((h + ph) // k, k, (w + pw) // k, k).sum(axis=(1, 3))
        if c.max(initial=0) <= TILE_TARGET:
            return t
    return TILE_SIZES[-1]


def _assigned(cell: pa.ChunkedArray) -> np.ndarray:
    """Whether each molecule sits in a cell: a cell id that is not null, not "UNASSIGNED" (10x), not "-1" (Vizgen)
    and not 0 (NanoString, where 0 means outside every cell)."""
    if pa.types.is_integer(cell.type) or pa.types.is_floating(cell.type):
        v = cell.to_numpy(zero_copy_only=False).astype(np.float64)
        return np.isfinite(v) & (v > 0)
    s = cell.cast(pa.string())
    out = pc.invert(pc.or_kleene(pc.is_null(s), pc.is_in(s, pa.array(["UNASSIGNED", "-1", "0", ""]))))
    return np.asarray(out.to_numpy(zero_copy_only=False), dtype=bool)


def _in_nucleus(nuc: pa.ChunkedArray) -> np.ndarray:
    """Whether each molecule overlaps the nucleus: a number above 0 (10x's overlaps_nucleus), a boolean, or a
    compartment label (NanoString's CellComp: Nuclear / Cytoplasm / Membrane / 0)."""
    if pa.types.is_boolean(nuc.type):
        return np.asarray(nuc.to_numpy(zero_copy_only=False), dtype=bool)
    if pa.types.is_integer(nuc.type) or pa.types.is_floating(nuc.type):
        v = nuc.to_numpy(zero_copy_only=False).astype(np.float64)
        return np.isfinite(v) & (v > 0)
    s = pc.utf8_lower(nuc.cast(pa.string()))
    out = pc.is_in(s, pa.array(["nuclear", "nucleus", "true", "1", "yes"]))
    return np.asarray(pc.fill_null(out, False).to_numpy(zero_copy_only=False), dtype=bool)


class _Reader:
    """The table's row groups, mapped into the sample frame, with the quality and control filters applied."""

    def __init__(self, path: Path, cols: dict[str, str], min_qv: float, to_frame: Callable[[np.ndarray], np.ndarray]):
        self.path = Path(path)
        self.cols = cols
        self.min_qv = min_qv
        self.to_frame = to_frame
        self.genes: dict[str, int] = {}
        self.read = self.passed = self.controls = 0  # rows read, rows past the quality filter, control rows among those

    def chunks(self, *, light: bool):
        c = self.cols
        names = [c["x"], c["y"]] + ([c["qv"]] if c.get("qv") else []) + ([] if light else [c["feature"]] + ([c["cell"]] if c.get("cell") else []) + ([c["nucleus"]] if c.get("nucleus") else []))
        for t in iter_batches(self.path, names):
            keep = None
            if c.get("qv"):
                keep = pc.greater_equal(t.column(c["qv"]), self.min_qv)
            if light:
                if keep is not None:
                    t = t.filter(keep)
                xy = self.to_frame(np.column_stack([t.column(c["x"]).to_numpy(), t.column(c["y"]).to_numpy()]).astype(np.float64))
                yield xy, None, None
                continue
            self.read += t.num_rows
            if keep is not None:
                t = t.filter(keep)
            self.passed += t.num_rows
            feat = t.column(c["feature"])
            feat = feat.dictionary_encode() if not pa.types.is_dictionary(feat.type) else feat
            feat = feat.combine_chunks() if feat.num_chunks != 1 else feat.chunk(0)
            dictionary = feat.dictionary.to_pylist()
            codes = feat.indices.to_numpy(zero_copy_only=False).astype(np.int64)
            local = np.empty(len(dictionary), dtype=np.int64)
            for j, name in enumerate(dictionary):
                name = str(name)
                if CONTROL_RE.match(name):
                    local[j] = -1
                else:
                    local[j] = self.genes.setdefault(name, len(self.genes))
            gene = local[codes]
            ok = gene >= 0
            self.controls += int((~ok).sum())
            xy = self.to_frame(np.column_stack([t.column(c["x"]).to_numpy(), t.column(c["y"]).to_numpy()]).astype(np.float64))[ok]
            flags = np.zeros(int(ok.sum()), dtype=np.uint8)
            if c.get("cell"):
                flags |= _assigned(t.column(c["cell"]))[ok].astype(np.uint8)
            if c.get("nucleus"):
                flags |= _in_nucleus(t.column(c["nucleus"]))[ok].astype(np.uint8) << 1
            if len(self.genes) > 65535:
                raise ValueError(f"more than 65,535 features in {self.path.name}; the molecule format holds gene ids as uint16")
            yield xy, gene[ok].astype(np.uint16), flags


def write_molecules(
    out_dir: Path,
    path: Path,
    *,
    to_frame: Callable[[np.ndarray], np.ndarray],
    columns: dict[str, str] | None = None,
    min_qv: float = 20.0,
    packed: bool = True,
    log: Callable[[str], None] = lambda *_: None,
) -> MoleculeStats:
    """Tile the molecules of one sample. `to_frame` maps raw (x, y) to sample microns, the same map the cells and
    their shapes went through. Two passes over the table: a coarse histogram to choose the tile size, then the
    tiles themselves, collected per tile in memory (about 7 bytes per kept molecule)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = {"feature": "feature_name", "x": "x_location", "y": "y_location", "qv": "qv", "cell": "cell_id", "nucleus": "overlaps_nucleus"}
    cols.update({k: v for k, v in (columns or {}).items() if v})
    present = set(table_columns(path))
    for k in ("feature", "x", "y"):
        if cols[k] not in present:
            raise KeyError(f"{path}: column {cols[k]!r} ({k}) not found; columns are {sorted(present)}")
    for k in ("qv", "cell", "nucleus"):
        if cols.get(k) and cols[k] not in present:
            log(f"molecules: column {cols[k]!r} ({k}) not in {path.name}; {'no quality filter' if k == 'qv' else 'flag left unset'}")
            cols[k] = ""
    rd = _Reader(path, cols, min_qv, to_frame)

    # pass 1: extent and a 64 um histogram -> tile size and origin
    cell = TILE_SIZES[-1]
    lo = np.array([np.inf, np.inf])
    hi = np.array([-np.inf, -np.inf])
    hist: dict[int, int] = {}
    total = 0
    K = 1 << 20  # histogram cells are keyed as (i + K) * 2K + (j + K): coordinates within +-67 m of the origin
    for xy, _g, _f in rd.chunks(light=True):
        if not len(xy):
            continue
        total += len(xy)
        lo = np.minimum(lo, xy.min(axis=0))
        hi = np.maximum(hi, xy.max(axis=0))
        ij = np.floor(xy / cell).astype(np.int64)
        if np.abs(ij).max() >= K:
            raise ValueError(f"{path}: molecule coordinates reach {np.abs(xy).max():,.0f} um; check the table's units and the frame transform")
        keys, n = np.unique((ij[:, 0] + K) * (2 * K) + (ij[:, 1] + K), return_counts=True)
        for k, v in zip(keys.tolist(), n.tolist(), strict=True):
            hist[k] = hist.get(k, 0) + v
    if total == 0:
        tile = TILE_SIZES[0]
        origin = np.zeros(2)
        counts = np.zeros((1, 1), dtype=np.int64)
    else:
        i0 = math.floor(lo[0] / cell)
        j0 = math.floor(lo[1] / cell)
        w = math.floor(hi[0] / cell) - i0 + 1
        h = math.floor(hi[1] / cell) - j0 + 1
        counts = np.zeros((h, w), dtype=np.int64)
        for k, v in hist.items():
            i, j = k // (2 * K) - K, k % (2 * K) - K
            counts[j - j0, i - i0] += v
        tile = _tile_size(counts, cell)
        origin = np.floor(lo / tile) * tile
    need = total * ROW_BYTES
    limit = read_limit_bytes()
    if need > limit:
        raise MemoryError(f"{path}: {total:,} molecules need about {need / 2**30:.1f} GB to tile, more than this build allows ({limit / 2**30:.1f} GB); raise min_qv or build on a larger machine")
    nx = math.floor((hi[0] - origin[0]) / tile) + 1 if total else 0
    ny = math.floor((hi[1] - origin[1]) / tile) + 1 if total else 0
    log(f"molecules: {total:,} rows at or above Q{min_qv:g} (controls still among them); {tile} um tiles over a {nx} x {ny} grid")

    # pass 2: collect per tile
    buckets: dict[int, list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]] = {}
    units_per_tile = round(tile / GRID)
    for xy, gene, flags in rd.chunks(light=False):
        if not len(xy):
            continue
        rel = xy - origin
        ij = np.floor(rel / tile).astype(np.int64)
        tid = ij[:, 1] * nx + ij[:, 0]
        q = np.rint((rel - ij * tile) / GRID).astype(np.int64)
        q = np.clip(q, 0, units_per_tile - 1).astype(np.uint16)
        order = np.argsort(tid, kind="stable")
        tid_s = tid[order]
        bounds = np.flatnonzero(np.diff(tid_s)) + 1
        for grp in np.split(order, bounds):
            t = int(tid[grp[0]])
            buckets.setdefault(t, []).append((gene[grp], q[grp, 0], q[grp, 1], flags[grp]))
    # encode
    tiles: list[list[int]] = []
    blob = bytearray()
    files_dir = out_dir / "molecules"
    if not packed:
        files_dir.mkdir(parents=True, exist_ok=True)
    genes = sorted(rd.genes)  # ids were handed out in the order the table mentioned the names; store them sorted
    position = {name: i for i, name in enumerate(genes)}
    remap = np.empty(max(1, len(rd.genes)), dtype=np.uint16)
    for name, old in rd.genes.items():
        remap[old] = position[name]
    gene_counts = np.zeros(max(1, len(genes)), dtype=np.int64)
    written = 0
    for t in sorted(buckets):
        parts = buckets.pop(t)
        gene = remap[np.concatenate([p[0] for p in parts])]
        qx = np.concatenate([p[1] for p in parts])
        qy = np.concatenate([p[2] for p in parts])
        fl = np.concatenate([p[3] for p in parts])
        np.add.at(gene_counts, gene, 1)
        frame = encode_tile(gene, qx, qy, fl)
        ix, iy = t % nx, t // nx
        if packed:
            tiles.append([ix, iy, len(blob), len(frame), len(gene)])
            blob += frame
        else:
            (files_dir / f"{ix}_{iy}.bin").write_bytes(frame)
            tiles.append([ix, iy, 0, len(frame), len(gene)])
        written += len(gene)
    if packed:
        (out_dir / "molecules.bin").write_bytes(bytes(blob))
    index = {
        "version": 1,
        "grid": GRID,
        "tile": tile,
        "origin": [float(origin[0]), float(origin[1])],
        "nx": nx,
        "ny": ny,
        "genes": genes,
        "counts": gene_counts[: len(genes)].tolist(),
        "count": written,
        "flags": ["assigned", "nucleus"],
        "layout": "packed" if packed else "files",
        "tiles": tiles,
    }
    (out_dir / "molecules.json").write_text(json.dumps(index, separators=(",", ":")))
    nbytes = sum(t[3] for t in tiles)
    return MoleculeStats(
        count=written,
        read=rd.read,
        low_quality=rd.read - rd.passed,
        controls=rd.controls,
        genes=len(genes),
        tile=tile,
        tiles=len(tiles),
        bytes=nbytes,
        seconds=time.time() - t0,
    )


def read_molecules(sample_dir: Path) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Every molecule of a sample, decoded: (gene names, gene ids, xy um, flags). For tests and validate."""
    d = Path(sample_dir)
    index = json.loads((d / "molecules.json").read_text())
    blob = (d / "molecules.bin").read_bytes() if index["layout"] == "packed" else None
    genes, xys, flags = [], [], []
    for ix, iy, off, nbytes, _n in index["tiles"]:
        frame = blob[off : off + nbytes] if blob is not None else (d / "molecules" / f"{ix}_{iy}.bin").read_bytes()
        o = (index["origin"][0] + ix * index["tile"], index["origin"][1] + iy * index["tile"])
        g, xy, f = decode_tile(frame, o, index["grid"])
        genes.append(g)
        xys.append(xy)
        flags.append(f)
    cat = lambda parts, dt: np.concatenate(parts) if parts else np.zeros((0, 2) if dt == "xy" else 0, dtype=np.float64 if dt == "xy" else np.uint16)  # noqa: E731
    return index["genes"], cat(genes, "g"), cat(xys, "xy"), cat(flags, "f")
