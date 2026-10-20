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
import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .config import TracksSpec
from .genes import gene_models_for, write_gene_models
from .manifest import TrackSet, TracksInfo

Log = Callable[[str], None]
TRACKS_RECIPE = 3  # bump when write_tracks writes something different for the same inputs and settings
DEFAULT_BIN = 25  # bp per bin for tracks built from fragments
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
        bw.addEntries([chrom] * len(order), all_s[order].tolist(), ends=all_e[order].tolist(), values=all_v[order].tolist())
    bw.close()


def _bare_barcode(name: str, run: str) -> str:
    """The barcode inside an observation name that carries its run: `run#bc` (ArchR), `run_bc`, `run-bc`, `bc_run`, `bc-run`, `bc#run`."""
    for sep in ("#", "_", "-"):
        if name.startswith(run + sep):
            return name[len(run) + 1 :]
        if name.endswith(sep + run):
            return name[: -len(run) - 1]
    return name


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
    at a time, kept as non-zero bins once the chromosome is done, summed over fragment files."""

    def __init__(self, sizes: dict[str, int], bin_: int, fields: list[str], ncat: dict[str, int]):
        self.sizes, self.bin, self.fields, self.ncat = sizes, bin_, fields, ncat
        self.by: dict[str, list[dict[str, Hits]]] = {f: [{} for _ in range(ncat[f])] for f in fields}
        self.all: dict[str, Hits] = {}
        self.totals = {f: np.zeros(ncat[f], dtype=np.int64) for f in fields}
        self.total_all = 0
        self.cur: str | None = None
        self.acc: dict[str, np.ndarray] = {}
        self.acc_all = np.zeros(0, dtype=np.int32)

    def start(self, chrom: str) -> None:
        self.flush()
        self.cur = chrom
        nbins = -(-self.sizes[chrom] // self.bin)  # the last bin ends at the chromosome end, never past it
        self.acc_all = np.zeros(nbins, dtype=np.int32)
        self.acc = {f: np.zeros((self.ncat[f], nbins), dtype=np.int32) for f in self.fields}

    def add(self, pos: np.ndarray, rows: np.ndarray, codes: dict[str, np.ndarray]) -> None:
        """pos: bin per insertion; rows: observation per insertion."""
        nbins = len(self.acc_all)
        self.acc_all += np.bincount(pos, minlength=nbins).astype(np.int32)  # bincount: ~20x faster than add.at
        self.total_all += len(pos)
        for f in self.fields:
            ck = codes[f][rows]
            counts = np.bincount(ck, minlength=self.ncat[f])
            self.totals[f] += counts
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


def _stream(path: Path, ins: _Insertions, bc: pd.Index, rows_of_run: np.ndarray, codes: dict[str, np.ndarray]) -> tuple[int, int]:
    """Add one fragment file's insertions for the observations in `bc` (rows `rows_of_run`); (fragments used, chromosomes)."""
    reader = pd.read_csv(
        path, sep="\t", comment="#", header=None, usecols=[0, 1, 2, 3], names=["chrom", "start", "end", "barcode"],
        dtype={"chrom": str, "start": np.int64, "end": np.int64, "barcode": str}, chunksize=4_000_000,
        compression="gzip" if str(path).endswith(".gz") else None,
    )
    seen: list[str] = []
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
            nbins = len(ins.acc_all)
            pos = np.clip(np.concatenate([grp["start"].to_numpy(), grp["end"].to_numpy() - 1]) // ins.bin, 0, nbins - 1)
            ins.add(pos, np.concatenate([r, r]), codes)
            n_used += len(grp)
    ins.flush()
    return n_used, len(seen)


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
    log: Log,
) -> tuple[str, list[TrackSet]]:
    codes = {f: np.asarray(cats[f], dtype=np.int64) for f in fields}
    ins = _Insertions(sizes, bin_, fields, {f: len(categories[f]) for f in fields})
    given = np.asarray([str(b) for b in barcodes], dtype=object) if barcodes is not None else None
    run_of = np.asarray([str(r) for r in runs], dtype=object) if runs is not None else None
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
        bc = pd.Index(names)
        if bc.has_duplicates:
            raise ValueError(f"tracks: fragment barcodes are not unique per observation{f' in run {run}' if run else ''}")
        log(f"  tracks: streaming {path.name}{f' ({run})' if run else ''} ({', '.join(fields)}; {bin_} bp bins)")
        n_used, n_chroms = _stream(path, ins, bc, rows_of_run, codes)
        log(f"  tracks: {n_used:,} fragments from {len(bc):,} barcodes over {n_chroms} chromosomes")
        if n_used == 0:
            raise ValueError(
                f"tracks: no fragment barcodes matched the observation names{f' of run {run}' if run else ''}; "
                "set `barcode_column:` to the obs column that holds them"
            )
    _write_bigwig(pybigwig, tdir / "all.bw", sizes, ins.all, bin_, 1e6 / max(ins.total_all, 1))
    by: list[TrackSet] = []
    for f in fields:
        fdir = tdir / f
        fdir.mkdir()
        paths: dict[str, str] = {}
        used: set[str] = set()
        for k, label in enumerate(categories[f]):
            if ins.totals[f][k] == 0 or label == "NA":  # unlabelled cells are not a group anyone wants a track for
                continue
            p = fdir / f"{_unique_slug(label, used)}.bw"
            _write_bigwig(pybigwig, p, sizes, ins.by[f][k], bin_, 1e6 / ins.totals[f][k])
            paths[label] = f"tracks/{f}/{p.name}"
        by.append(TrackSet(field=f, categories=paths))
        log(f"  tracks: {f}: {len(paths)} categories")
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


def _write_annotations(spec: TracksSpec, tdir: Path, sizes: dict[str, int], feature_names: list[str], log: Log) -> tuple[str | None, str | None, str | None]:
    """peaks.bed from the sample's features, gene models, the links file; (peaks, genes, links) paths."""
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
    if spec.bigwigs is not None:
        sizes, bin_, all_path, by = _copy_bigwigs(pybigwig, spec, tdir, fields, categories, aliases or {}, log)
        units = spec.units or "signal"
    else:
        sizes = chrom_sizes(spec)
        bin_ = spec.bin or DEFAULT_BIN
        all_path, by = _tracks_from_fragments(
            pybigwig, spec, tdir, sizes, bin_, ids=ids, barcodes=barcodes, runs=runs, cats=cats, categories=categories, fields=fields, log=log
        )
        units = spec.units or "insertions per million"
    peaks_path, genes_path, links_path = _write_annotations(spec, tdir, sizes, feature_names, log)
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
