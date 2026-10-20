"""Genome tracks for ATAC samples: pseudobulk accessibility per annotation category.

For every field listed in `tracks.by`, one bigWig per category (plus one for all cells); the viewer's genome panel
stacks them under the current locus, colored from the shared vocabulary. Two sources:

- Fragment files (Cell Ranger `fragments.tsv.gz`): Tn5 insertions per million, both ends of every fragment,
  binned. One file, or one per run for an object pooled from several 10x runs, whose barcodes collide: each
  observation is matched to the fragments of its own run (`sample_column`), and a category's track sums its cells
  over every run before the per-million scaling. Each file is streamed once (coordinate-sorted, so one chromosome
  is in memory at a time) and never decompressed to disk.
- bigWigs exported elsewhere (ArchR `getGroupBW`, Signac `ExportGroupBW`, bamCoverage per group), copied in as
  they are: their bin size is read from the files and the manifest records the units given.

Needs pyBigWig (`pip install "spatialscape[tracks]"`).

    samples/<id>/tracks/
      all.bw                   every cell (from fragments, or when `bigwigs.all` was given)
      <field>/<category>.bw    one per category label (file names sanitized; the manifest maps labels to paths)
      peaks.bed                the sample's peak features, when their names are chr:start-end
      genes/                   gene models, one JSON per chromosome plus an index of names (see genes.py)
      links.bedpe              copied from the yaml when given
      chrom.sizes
"""
from __future__ import annotations

import gzip
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .config import TracksSpec, is_remote
from .genes import GeneModel, gene_models_for, write_gene_models
from .manifest import TrackSet, TracksInfo

Log = Callable[[str], None]
TRACKS_RECIPE = 4  # bump when write_tracks writes something different for the same inputs and settings
DEFAULT_BIN = 25  # bp per bin for tracks built from fragments
UNITS = {"nfrags": "insertions per million", "tss": "per million TSS insertions", "cells": "insertions per cell"}
PEAK_RE = re.compile(r"^(?:peak: )?(chr[0-9XYM]+|[0-9XYM]+)[:-](\d+)-(\d+)$")  # chr1:100-200 (10x) or chr1-100-200 (Signac)

# GRCh38 primary chromosomes (the 10x references use these names and lengths)
GRCH38 = {
    "chr1": 248956422, "chr2": 242193529, "chr3": 198295559, "chr4": 190214555, "chr5": 181538259,
    "chr6": 170805979, "chr7": 159345973, "chr8": 145138636, "chr9": 138394717, "chr10": 133797422,
    "chr11": 135086622, "chr12": 133275309, "chr13": 114364328, "chr14": 107043718, "chr15": 101991189,
    "chr16": 90338345, "chr17": 83257441, "chr18": 80373285, "chr19": 58617616, "chr20": 64444167,
    "chr21": 46709983, "chr22": 50818468, "chrX": 156040895, "chrY": 57227415, "chrM": 16569,
}
GENOME_SIZES = {"hg38": GRCH38, "GRCh38": GRCH38}

Hits = tuple[np.ndarray, np.ndarray]  # (bin indices, counts) of the non-zero bins of one chromosome


def _pybigwig():
    try:
        import pyBigWig
    except ImportError as e:  # pragma: no cover
        raise ImportError("genome tracks need pyBigWig: pip install 'spatialscape[tracks]'") from e
    return pyBigWig


def chrom_sizes(spec: TracksSpec, default: dict[str, int] | None = None) -> dict[str, int]:
    """`chrom_sizes:` if given, else the genome's table, else `default` (the chromosomes of a bigWig being copied)."""
    if spec.chrom_sizes is not None:
        df = pd.read_csv(spec.chrom_sizes, sep="\t", header=None, usecols=[0, 1], names=["chrom", "size"], dtype={"chrom": str})
        return dict(zip(df["chrom"], df["size"].astype(int), strict=False))
    if spec.genome in GENOME_SIZES:
        return dict(GENOME_SIZES[spec.genome])
    if default:
        return {str(c): int(n) for c, n in default.items()}
    raise ValueError(f"tracks: no chromosome sizes known for genome {spec.genome!r}; set `chrom_sizes:`")


def _slug(label: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    return s or "category"


def _unique_slug(label: str, used: set[str]) -> str:
    slug = _slug(label)
    n = 2
    while slug in used:  # "NK/T cells" and "NK T cells" must not share a file
        slug = f"{_slug(label)}_{n}"
        n += 1
    used.add(slug)
    return slug


def _write_bigwig(pybigwig, path: Path, sizes: dict[str, int], per_chrom: dict[str, Hits], bin_: int, scale: float) -> None:
    """per_chrom: chrom -> (bin indices, counts) for the non-zero bins. Values are counts * scale. The gaps between
    them are written as explicit zero runs: a bigWig's zoom levels average over covered bases only, so without
    them a lone 25 bp bin would be reported at full height for a whole 250 bp zoom bin once zoomed out."""
    bw = pybigwig.open(str(path), "w")
    bw.addHeader(list(sizes.items()))
    for chrom in sizes:
        hit = per_chrom.get(chrom)
        if hit is None or len(hit[0]) == 0:
            continue
        idx, cnt = hit
        size = sizes[chrom]
        starts = idx.astype(np.int64) * bin_
        ends = np.minimum(starts + bin_, size)
        gap_s = np.concatenate([[0], ends])
        gap_e = np.concatenate([starts, [size]])
        keep = gap_e > gap_s
        all_s = np.concatenate([starts, gap_s[keep]])
        all_e = np.concatenate([ends, gap_e[keep]])
        all_v = np.concatenate([cnt.astype(np.float64) * scale, np.zeros(int(keep.sum()))])
        order = np.argsort(all_s, kind="stable")
        all_s, all_e, all_v = all_s[order], all_e[order], all_v[order]
        # the entries tile the chromosome without gaps: merge neighbours with the same value (runs of 1s, long zero
        # stretches) into one interval each, which is what keeps a dense track's file size in check
        first = np.ones(len(all_s), dtype=bool)
        first[1:] = all_v[1:] != all_v[:-1]
        s_ = all_s[first]
        e_ = np.append(s_[1:], all_e[-1])
        v_ = all_v[first]
        bw.addEntries([chrom] * len(s_), s_.tolist(), ends=e_.tolist(), values=v_.tolist())
    bw.close()


def _bare_barcode(name: str, run: str) -> str:
    """The barcode inside an observation name that carries its run: `run#bc` (ArchR), `run_bc`, `run-bc`, `bc_run`, `bc-run`, `bc#run`."""
    for sep in ("#", "_", "-"):
        if name.startswith(run + sep):
            return name[len(run) + 1 :]
        if name.endswith(sep + run):
            return name[: -len(run) - 1]
    return name


def tss_positions(models: dict[str, list[GeneModel]]) -> dict[str, np.ndarray]:
    """Per chromosome, the sorted TSS positions of the gene models (start on +, last base on -, start when unknown)."""
    out = {}
    for chrom, ms in models.items():
        pos = np.fromiter(((m.end - 1) if m.strand < 0 else m.start for m in ms), dtype=np.int64, count=len(ms))
        out[chrom] = np.unique(pos)
    return out


def near_tss(pos: np.ndarray, tss: np.ndarray | None, window: int) -> np.ndarray:
    """Which insertion positions lie within `window` bp of a TSS (sorted positions), as a boolean mask."""
    if tss is None or len(tss) == 0:
        return np.zeros(len(pos), dtype=bool)
    i = np.searchsorted(tss, pos)
    left = tss[np.clip(i - 1, 0, len(tss) - 1)]
    right = tss[np.clip(i, 0, len(tss) - 1)]
    return (np.abs(pos - left) <= window) | (np.abs(right - pos) <= window)


def _merge_hits(store: dict[str, Hits], chrom: str, acc: np.ndarray) -> None:
    """Keep the non-zero bins of `acc` for `chrom`, added to what an earlier fragment file left for it."""
    nz = np.flatnonzero(acc)
    if not len(nz):
        return
    idx, cnt = nz.astype(np.int32), acc[nz].astype(np.int64)
    prev = store.get(chrom)
    if prev is not None:
        both_idx = np.concatenate([prev[0], idx])
        both_cnt = np.concatenate([prev[1], cnt])
        uniq, inv = np.unique(both_idx, return_inverse=True)
        idx, cnt = uniq.astype(np.int32), np.bincount(inv, weights=both_cnt).astype(np.int64)
    store[chrom] = (idx, cnt)


class _Insertions:
    """Insertion counts per bin, per category of each field and for every cell: one chromosome's dense accumulators
    at a time, kept as non-zero bins once the chromosome is done, summed over fragment files. Alongside, what each
    group's track is scaled by: its insertions, its insertions at TSSs, or its number of cells."""

    def __init__(
        self, sizes: dict[str, int], bin_: int, fields: list[str], ncat: dict[str, int], *, tss: dict[str, np.ndarray] | None = None, window: int = 50
    ):
        self.sizes, self.bin, self.fields, self.ncat = sizes, bin_, fields, ncat
        self.tss, self.window = tss, window
        self.by: dict[str, list[dict[str, Hits]]] = {f: [{} for _ in range(ncat[f])] for f in fields}
        self.all: dict[str, Hits] = {}
        self.totals = {f: np.zeros(ncat[f], dtype=np.int64) for f in fields}
        self.tss_totals = {f: np.zeros(ncat[f], dtype=np.int64) for f in fields}
        self.total_all = 0
        self.tss_total_all = 0
        self.cur: str | None = None
        self.cur_tss: np.ndarray | None = None
        self.acc: dict[str, np.ndarray] = {}
        self.acc_all = np.zeros(0, dtype=np.int32)

    def start(self, chrom: str) -> None:
        self.flush()
        self.cur = chrom
        self.cur_tss = self.tss.get(chrom) if self.tss is not None else None
        nbins = -(-self.sizes[chrom] // self.bin)  # the last bin ends at the chromosome end, never past it
        self.acc_all = np.zeros(nbins, dtype=np.int32)
        self.acc = {f: np.zeros((self.ncat[f], nbins), dtype=np.int32) for f in self.fields}

    def add(self, bp: np.ndarray, rows: np.ndarray, codes: dict[str, np.ndarray]) -> None:
        """bp: insertion positions; rows: observation per insertion."""
        nbins = len(self.acc_all)
        pos = np.clip(bp // self.bin, 0, nbins - 1)
        self.acc_all += np.bincount(pos, minlength=nbins).astype(np.int32)  # bincount: ~20x faster than add.at
        self.total_all += len(pos)
        at_tss = near_tss(bp, self.cur_tss, self.window) if self.tss is not None else None
        if at_tss is not None:
            self.tss_total_all += int(at_tss.sum())
        for f in self.fields:
            ck = codes[f][rows]
            counts = np.bincount(ck, minlength=self.ncat[f])
            self.totals[f] += counts
            if at_tss is not None:
                self.tss_totals[f] += np.bincount(ck[at_tss], minlength=self.ncat[f])
            for k in np.flatnonzero(counts):
                self.acc[f][k] += np.bincount(pos[ck == k], minlength=nbins).astype(np.int32)

    def flush(self) -> None:
        if self.cur is None:
            return
        _merge_hits(self.all, self.cur, self.acc_all)
        for f in self.fields:
            for k in range(self.ncat[f]):
                _merge_hits(self.by[f][k], self.cur, self.acc[f][k])
        self.cur, self.acc, self.acc_all = None, {}, np.zeros(0, dtype=np.int32)


def split_ssh_url(url: str) -> tuple[str, str]:
    """`ssh://[user@]host/abs/path` -> (host, /abs/path)."""
    rest = url[len("ssh://") :]
    host, _, path = rest.partition("/")
    if not host or not path:
        raise ValueError(f"tracks: a remote fragment file is ssh://host/absolute/path, got {url!r}")
    return host, "/" + path


def _file_label(path: Path | str) -> str:
    return path.rsplit("/", 1)[-1] if isinstance(path, str) else path.name


def _stream(path: Path | str, ins: _Insertions, bc: pd.Index, rows_of_run: np.ndarray, codes: dict[str, np.ndarray]) -> tuple[int, int]:
    """Add one fragment file's insertions for the observations in `bc` (rows `rows_of_run`); (fragments used,
    chromosomes). An `ssh://host/path` file is read through `ssh host cat path`: one sequential pass, nothing
    written on the remote side or stored locally."""
    proc = None
    if is_remote(path):
        host, remote = split_ssh_url(str(path))
        proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", host, f"cat {shlex.quote(remote)}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        source = proc.stdout
    else:
        source = path
    reader = pd.read_csv(
        source, sep="\t", comment="#", header=None, usecols=[0, 1, 2, 3], names=["chrom", "start", "end", "barcode"],
        dtype={"chrom": str, "start": np.int64, "end": np.int64, "barcode": str}, chunksize=4_000_000,
        compression="gzip" if str(path).endswith(".gz") else None,
    )
    seen: list[str] = []
    n_used = 0
    try:
        n_used = _consume(reader, ins, bc, rows_of_run, codes, path, seen)
    finally:
        if proc is not None:
            err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
            code = proc.wait()
            if code != 0:
                raise ValueError(f"tracks: reading {path} over ssh failed (exit {code}): {err[-500:]}")
    ins.flush()
    return n_used, len(seen)


def _consume(reader, ins: _Insertions, bc: pd.Index, rows_of_run: np.ndarray, codes: dict[str, np.ndarray], path: Path | str, seen: list[str]) -> int:
    n_used = 0
    for chunk in reader:
        idx = bc.get_indexer(chunk["barcode"].to_numpy())
        keep = idx >= 0
        if not keep.any():
            continue
        chunk = chunk[keep].reset_index(drop=True)
        rows = rows_of_run[idx[keep]]
        for chrom, grp in chunk.groupby("chrom", sort=False):
            chrom = str(chrom)
            if chrom not in ins.sizes:
                continue
            if chrom != ins.cur:
                if chrom in seen:
                    raise ValueError(f"tracks: {path} is not sorted by chromosome ({chrom} appears twice)")
                ins.start(chrom)
                seen.append(chrom)
            r = rows[grp.index.to_numpy()]
            bp = np.concatenate([grp["start"].to_numpy(), grp["end"].to_numpy() - 1])  # both Tn5 insertion sites
            ins.add(bp, np.concatenate([r, r]), codes)
            n_used += len(grp)
    return n_used


def _tracks_from_fragments(
    pybigwig,
    spec: TracksSpec,
    tdir: Path,
    sizes: dict[str, int],
    bin_: int,
    *,
    ids: list[str],
    barcodes: list[str] | None,
    runs: list[str] | None,
    cats: dict[str, np.ndarray],
    categories: dict[str, list[str]],
    fields: list[str],
    tss: dict[str, np.ndarray] | None,
    log: Log,
) -> tuple[str, list[TrackSet]]:
    codes = {f: np.asarray(cats[f], dtype=np.int64) for f in fields}
    ncat = {f: len(categories[f]) for f in fields}
    ins = _Insertions(sizes, bin_, fields, ncat, tss=tss if spec.normalize == "tss" else None, window=spec.tss_window)
    given = np.asarray([str(b) for b in barcodes], dtype=object) if barcodes is not None else None
    run_of = np.asarray([str(r) for r in runs], dtype=object) if runs is not None else None
    covered = np.zeros(len(ids), dtype=bool)  # observations whose run has a fragment file (what `cells` divides by)
    for run, path in spec.fragment_files:
        if run is None:
            rows_of_run = np.arange(len(ids))
            names = given if given is not None else np.asarray([str(i) for i in ids], dtype=object)
        else:
            rows_of_run = np.flatnonzero(run_of == run) if run_of is not None else np.zeros(0, dtype=np.int64)
            if not len(rows_of_run):
                have = sorted(set(run_of.tolist())) if run_of is not None else []
                raise ValueError(f"tracks: no observation has {spec.sample_column} == {run!r} (values: {have[:8]})")
            names = given[rows_of_run] if given is not None else np.asarray([_bare_barcode(str(ids[i]), run) for i in rows_of_run], dtype=object)
        covered[rows_of_run] = True
        bc = pd.Index(names)
        if bc.has_duplicates:
            raise ValueError(f"tracks: fragment barcodes are not unique per observation{f' in run {run}' if run else ''}")
        where = f" over ssh from {split_ssh_url(str(path))[0]}" if is_remote(path) else ""
        log(f"  tracks: streaming {_file_label(path)}{f' ({run})' if run else ''}{where} ({', '.join(fields)}; {bin_} bp bins)")
        n_used, n_chroms = _stream(path, ins, bc, rows_of_run, codes)
        log(f"  tracks: {n_used:,} fragments from {len(bc):,} barcodes over {n_chroms} chromosomes")
        if n_used == 0:
            raise ValueError(
                f"tracks: no fragment barcodes matched the observation names{f' of run {run}' if run else ''} ({_file_label(path)}); "
                "set `barcode_column:` to the obs column that holds them"
            )
    def scale(total: int, at_tss: int, n_cells: int) -> float | None:
        """What divides a group's counts: None when the group has nothing to scale by (no track is written)."""
        if spec.normalize == "tss":
            return 1e6 / at_tss if at_tss > 0 else None
        if spec.normalize == "cells":
            return 1.0 / n_cells if n_cells > 0 else None
        return 1e6 / total if total > 0 else None

    n_cells = {f: np.bincount(codes[f][covered], minlength=ncat[f]) for f in fields}
    if spec.normalize == "tss":
        log(f"  tracks: scaling by insertions within {spec.tss_window} bp of a TSS ({ins.tss_total_all:,} of {ins.total_all:,})")
    s_all = scale(ins.total_all, ins.tss_total_all, int(covered.sum()))
    if s_all is None:
        raise ValueError("tracks: nothing to scale the tracks by (no insertions at TSSs?); check `genes:` or use normalize: nfrags")
    _write_bigwig(pybigwig, tdir / "all.bw", sizes, ins.all, bin_, s_all)
    by: list[TrackSet] = []
    for f in fields:
        fdir = tdir / f
        fdir.mkdir()
        paths: dict[str, str] = {}
        used: set[str] = set()
        skipped: list[str] = []
        for k, label in enumerate(categories[f]):
            if ins.totals[f][k] == 0 or label == "NA":  # unlabelled cells are not a group anyone wants a track for
                continue
            sk = scale(int(ins.totals[f][k]), int(ins.tss_totals[f][k]), int(n_cells[f][k]))
            if sk is None:
                skipped.append(label)
                continue
            p = fdir / f"{_unique_slug(label, used)}.bw"
            _write_bigwig(pybigwig, p, sizes, ins.by[f][k], bin_, sk)
            paths[label] = f"tracks/{f}/{p.name}"
        by.append(TrackSet(field=f, categories=paths))
        log(f"  tracks: {f}: {len(paths)} categories" + (f" (no TSS insertions for {', '.join(skipped)})" if skipped else ""))
    return "tracks/all.bw", by


def _detect_bin(bw) -> int:
    """The bin size of an exported bigWig: the greatest common divisor of its interval widths on the first chromosome
    with data (fixed tiles give the tile size; bamCoverage merges equal neighbours, so widths are multiples of it)."""
    for chrom, size in bw.chroms().items():
        iv = bw.intervals(chrom, 0, min(int(size), 5_000_000))
        if iv:
            widths = np.fromiter((e - s for s, e, _ in iv), dtype=np.int64, count=len(iv))
            return max(int(np.gcd.reduce(widths)), 1)
    return DEFAULT_BIN


def _bigwig_for(src: str | dict, label: str, aliases: dict[str, str]) -> Path | None:
    """The exported file for a category: by its label, else by any raw label the vocabulary maps onto it."""
    names = [label] + [raw for raw, canon in aliases.items() if canon == label and raw != label]
    for name in names:
        p = Path(src[name]) if isinstance(src, dict) and name in src else Path(str(src).replace("{label}", name)) if not isinstance(src, dict) else None
        if p is not None and p.is_file():
            return p
    return None


def _copy_bigwigs(
    pybigwig, spec: TracksSpec, tdir: Path, fields: list[str], categories: dict[str, list[str]], aliases: dict[str, dict[str, str]], log: Log
) -> tuple[dict[str, int], int, str | None, list[TrackSet]]:
    """Copy exported per-category bigWigs into the sample; (chromosome sizes, bin, all path, track sets)."""
    assert spec.bigwigs is not None
    first: Path | None = None

    def take(src: Path, dst: Path) -> None:
        nonlocal first
        bw = pybigwig.open(str(src))
        if bw is None or not bw.isBigWig():
            raise ValueError(f"tracks.bigwigs: {src} is not a bigWig")
        bw.close()
        shutil.copy2(src, dst)
        first = first or dst

    by: list[TrackSet] = []
    for f in fields:
        src = spec.bigwigs.by[f]
        fdir = tdir / f
        fdir.mkdir()
        paths: dict[str, str] = {}
        used: set[str] = set()
        missing: list[str] = []
        for label in categories[f]:
            if label == "NA":
                continue
            p = _bigwig_for(src, label, aliases.get(f, {}))
            if p is None:
                missing.append(label)
                continue
            dst = fdir / f"{_unique_slug(label, used)}.bw"
            take(p, dst)
            paths[label] = f"tracks/{f}/{dst.name}"
        if not paths:
            raise ValueError(f"tracks.bigwigs: no file matched a category of {f!r} ({src}); labels tried: {missing[:6]}")
        by.append(TrackSet(field=f, categories=paths))
        log(f"  tracks: {f}: {len(paths)} bigWigs copied" + (f", no file for {', '.join(missing)}" if missing else ""))
    all_path = None
    if spec.bigwigs.all is not None:
        take(Path(spec.bigwigs.all), tdir / "all.bw")
        all_path = "tracks/all.bw"
    assert first is not None
    bw = pybigwig.open(str(first))
    chroms = {str(c): int(n) for c, n in bw.chroms().items()}
    sizes = chrom_sizes(spec, default=chroms)
    common = {c: n for c, n in sizes.items() if c in chroms}
    if not common:
        raise ValueError(
            f"tracks.bigwigs: chromosome names in {first.name} ({', '.join(list(chroms)[:4])}, ...) do not match "
            f"{spec.genome}'s ({', '.join(list(sizes)[:4])}, ...); set `chrom_sizes:` to theirs"
        )
    if len(common) < len(sizes):
        log(f"  tracks: chromosomes without data left out: {', '.join(c for c in sizes if c not in common)}")
    bin_ = spec.bin or _detect_bin(bw)
    bw.close()
    return common, bin_, all_path, by


def _write_annotations(
    spec: TracksSpec, tdir: Path, sizes: dict[str, int], feature_names: list[str], log: Log, gm: tuple[dict[str, list[GeneModel]], str] | None = None
) -> tuple[str | None, str | None, str | None]:
    """peaks.bed from the sample's features, gene models (`gm` when already computed), the links file; (peaks, genes, links) paths."""
    peaks_path = None
    peak_rows = []
    for name in feature_names:
        m = PEAK_RE.match(name)
        if m:
            chrom = m.group(1) if m.group(1).startswith("chr") else f"chr{m.group(1)}"
            peak_rows.append((chrom, int(m.group(2)), int(m.group(3)), name))
    if peak_rows:
        order = {c: i for i, c in enumerate(sizes)}
        peak_rows.sort(key=lambda r: (order.get(r[0], 1e9), r[1]))
        with open(tdir / "peaks.bed", "w") as fh:
            fh.writelines(f"{c}\t{s}\t{e}\t{n}\n" for c, s, e, n in peak_rows)
        peaks_path = "tracks/peaks.bed"
    genes_path = links_path = None
    if gm is None:
        gm = gene_models_for(spec.genes, spec.genome, sizes, log=log)
    if gm is not None:
        models, source = gm
        n_genes = write_gene_models(models, tdir / "genes", source=source, order=list(sizes))
        log(f"  tracks: gene models: {n_genes:,} genes from {source}")
        genes_path = "tracks/genes"
    if spec.links is not None:
        shutil.copy2(spec.links, tdir / "links.bedpe")
        links_path = "tracks/links.bedpe"
    return peaks_path, genes_path, links_path


def write_tracks(
    spec: TracksSpec,
    out_dir: Path,
    *,
    ids: list[str],
    barcodes: list[str] | None,
    runs: list[str] | None = None,
    cats: dict[str, np.ndarray],
    categories: dict[str, list[str]],
    aliases: dict[str, dict[str, str]] | None = None,
    feature_names: list[str],
    log: Log = print,
) -> TracksInfo:
    """Build the track files for one sample.

    ids: observation names in bundle order; barcodes: the fragment-file barcode per observation (default: ids, minus
    a run prefix or suffix when there are several runs); runs: the run per observation (`sample_column`);
    cats: field id -> category codes in bundle order; categories: field id -> label per code; aliases: field id ->
    raw label -> label (exported bigWigs may be named by raw labels); feature_names: the sample's features (peaks
    are recognised by name).
    """
    pybigwig = _pybigwig()
    tdir = Path(out_dir) / "tracks"
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    fields = [f for f in spec.by if f in cats]
    missing = [f for f in spec.by if f not in cats]
    if missing:
        raise KeyError(f"tracks.by: field(s) {missing} are not categorical fields of this sample")
    gm = None
    if spec.bigwigs is not None:
        sizes, bin_, all_path, by = _copy_bigwigs(pybigwig, spec, tdir, fields, categories, aliases or {}, log)
        units = spec.units or "signal"
    else:
        sizes = chrom_sizes(spec)
        bin_ = spec.bin or DEFAULT_BIN
        tss = None
        if spec.normalize == "tss":  # the gene models are needed before the fragments are read
            gm = gene_models_for(spec.genes, spec.genome, sizes, log=log)
            if gm is None:
                raise ValueError("tracks: `normalize: tss` needs gene models; set `genes:` to a GTF, genePred or BED (or use nfrags / cells)")
            tss = tss_positions(gm[0])
        all_path, by = _tracks_from_fragments(
            pybigwig, spec, tdir, sizes, bin_, ids=ids, barcodes=barcodes, runs=runs, cats=cats, categories=categories, fields=fields, tss=tss, log=log
        )
        units = spec.units or UNITS[spec.normalize]
    peaks_path, genes_path, links_path = _write_annotations(spec, tdir, sizes, feature_names, log, gm)
    with open(tdir / "chrom.sizes", "w") as fh:
        fh.writelines(f"{c}\t{n}\n" for c, n in sizes.items())
    return TracksInfo(
        genome=spec.genome, bin=bin_, all=all_path, units=units, by=by, peaks=peaks_path, genes=genes_path, links=links_path, chromSizes="tracks/chrom.sizes"
    )


def write_fragments(path: Path, rows: list[tuple[str, int, int, str]]) -> Path:
    """A small coordinate-sorted fragments.tsv.gz (tests and the synthetic dataset)."""
    rows = sorted(rows, key=lambda r: (r[0], r[1]))
    with gzip.open(path, "wt") as fh:
        fh.write("# synthetic fragments\n")
        fh.writelines(f"{c}\t{s}\t{e}\t{b}\t1\n" for c, s, e, b in rows)
    return path
