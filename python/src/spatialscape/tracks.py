"""Genome tracks for ATAC samples: pseudobulk accessibility per annotation category, from a fragment file.

For every field listed in `tracks.by`, one bigWig per category holds Tn5 insertions per million (both ends of
every fragment, binned), plus one for all cells; the viewer's genome panel stacks them under the current locus,
colored from the shared vocabulary. The fragment file is streamed once (it is coordinate-sorted, so one
chromosome is in memory at a time) and never decompressed to disk. Needs pyBigWig (`pip install "spatialscape[tracks]"`).

    samples/<id>/tracks/
      all.bw                   every cell
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
TRACKS_RECIPE = 2  # bump when write_tracks writes something different for the same inputs and settings
PEAK_RE = re.compile(r"^(?:peak: )?(chr[0-9XYM]+|[0-9XYM]+):(\d+)-(\d+)$")

# GRCh38 primary chromosomes (the 10x references use these names and lengths)
GRCH38 = {
    "chr1": 248956422, "chr2": 242193529, "chr3": 198295559, "chr4": 190214555, "chr5": 181538259,
    "chr6": 170805979, "chr7": 159345973, "chr8": 145138636, "chr9": 138394717, "chr10": 133797422,
    "chr11": 135086622, "chr12": 133275309, "chr13": 114364328, "chr14": 107043718, "chr15": 101991189,
    "chr16": 90338345, "chr17": 83257441, "chr18": 80373285, "chr19": 58617616, "chr20": 64444167,
    "chr21": 46709983, "chr22": 50818468, "chrX": 156040895, "chrY": 57227415, "chrM": 16569,
}
GENOME_SIZES = {"hg38": GRCH38, "GRCh38": GRCH38}


def _pybigwig():
    try:
        import pyBigWig
    except ImportError as e:  # pragma: no cover
        raise ImportError("genome tracks need pyBigWig: pip install 'spatialscape[tracks]'") from e
    return pyBigWig


def chrom_sizes(spec: TracksSpec) -> dict[str, int]:
    if spec.chrom_sizes is not None:
        df = pd.read_csv(spec.chrom_sizes, sep="\t", header=None, usecols=[0, 1], names=["chrom", "size"], dtype={"chrom": str})
        return dict(zip(df["chrom"], df["size"].astype(int), strict=False))
    if spec.genome in GENOME_SIZES:
        return dict(GENOME_SIZES[spec.genome])
    raise ValueError(f"tracks: no chromosome sizes known for genome {spec.genome!r}; set `chrom_sizes:`")


def _slug(label: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_")
    return s or "category"


def _write_bigwig(pybigwig, path: Path, sizes: dict[str, int], per_chrom: dict[str, tuple[np.ndarray, np.ndarray]], bin_: int, scale: float) -> None:
    """per_chrom: chrom -> (bin indices, counts) for the non-zero bins. Values are counts * scale."""
    bw = pybigwig.open(str(path), "w")
    bw.addHeader(list(sizes.items()))
    for chrom in sizes:
        hit = per_chrom.get(chrom)
        if hit is None or len(hit[0]) == 0:
            continue
        idx, cnt = hit
        starts = (idx.astype(np.int64) * bin_)
        ends = np.minimum(starts + bin_, sizes[chrom])
        bw.addEntries([chrom] * len(starts), starts.tolist(), ends=ends.tolist(), values=(cnt.astype(np.float64) * scale).tolist())
    bw.close()


def write_tracks(
    spec: TracksSpec,
    out_dir: Path,
    *,
    ids: list[str],
    barcodes: list[str] | None,
    cats: dict[str, np.ndarray],
    categories: dict[str, list[str]],
    feature_names: list[str],
    log: Log = print,
) -> TracksInfo:
    """Build the track files for one sample.

    ids: observation names in bundle order; barcodes: the fragment-file barcode per observation (default: ids);
    cats: field id -> category codes in bundle order; categories: field id -> label per code;
    feature_names: the sample's features (peaks are recognised by name).
    """
    pybigwig = _pybigwig()
    sizes = chrom_sizes(spec)
    tdir = Path(out_dir) / "tracks"
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    fields = [f for f in spec.by if f in cats]
    missing = [f for f in spec.by if f not in cats]
    if missing:
        raise KeyError(f"tracks.by: field(s) {missing} are not categorical fields of this sample")
    codes = {f: np.asarray(cats[f], dtype=np.int64) for f in fields}
    ncat = {f: len(categories[f]) for f in fields}
    bc = pd.Index([str(b) for b in (barcodes if barcodes is not None else ids)])
    if bc.has_duplicates:
        raise ValueError("tracks: fragment barcodes are not unique per observation")
    bin_ = spec.bin

    # accumulators: per field, per category (+ all), chrom -> (nonzero bin indices, counts)
    nonzero: dict[str, list[dict[str, tuple[np.ndarray, np.ndarray]]]] = {f: [{} for _ in range(ncat[f])] for f in fields}
    nonzero_all: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    totals = {f: np.zeros(ncat[f], dtype=np.int64) for f in fields}
    total_all = 0
    cur: str | None = None
    acc: dict[str, np.ndarray] = {}
    acc_all: np.ndarray | None = None

    def flush() -> None:
        nonlocal acc_all
        if cur is None:
            return
        nz = np.flatnonzero(acc_all)
        if len(nz):
            nonzero_all[cur] = (nz.astype(np.int32), acc_all[nz].copy())
        for f in fields:
            a = acc[f]
            for k in range(ncat[f]):
                nzk = np.flatnonzero(a[k])
                if len(nzk):
                    nonzero[f][k][cur] = (nzk.astype(np.int32), a[k][nzk].copy())

    def start(chrom: str) -> None:
        nonlocal cur, acc_all, acc
        cur = chrom
        nbins = sizes[chrom] // bin_ + 1
        acc_all = np.zeros(nbins, dtype=np.int32)
        acc = {f: np.zeros((ncat[f], nbins), dtype=np.int32) for f in fields}

    log(f"  tracks: streaming {spec.fragments.name} ({', '.join(fields)}; {bin_} bp bins)")
    reader = pd.read_csv(
        spec.fragments, sep="\t", comment="#", header=None, usecols=[0, 1, 2, 3], names=["chrom", "start", "end", "barcode"],
        dtype={"chrom": str, "start": np.int64, "end": np.int64, "barcode": str}, chunksize=4_000_000, compression="gzip" if str(spec.fragments).endswith(".gz") else None,
    )
    seen_chroms: list[str] = []
    n_used = 0
    for chunk in reader:
        rows = bc.get_indexer(chunk["barcode"].to_numpy())
        keep = rows >= 0
        if not keep.any():
            continue
        chunk = chunk[keep].reset_index(drop=True)
        rows = rows[keep]
        for chrom, grp in chunk.groupby("chrom", sort=False):
            chrom = str(chrom)
            if chrom not in sizes:
                continue
            if chrom != cur:
                if chrom in seen_chroms:
                    raise ValueError(f"tracks: {spec.fragments} is not sorted by chromosome ({chrom} appears twice)")
                flush()
                start(chrom)
                seen_chroms.append(chrom)
            r = rows[grp.index.to_numpy()]
            pos = np.concatenate([grp["start"].to_numpy(), grp["end"].to_numpy() - 1]) // bin_
            pos = np.clip(pos, 0, sizes[chrom] // bin_)
            rr = np.concatenate([r, r])
            np.add.at(acc_all, pos, 1)
            total_all += len(pos)
            n_used += len(grp)
            for f in fields:
                ck = codes[f][rr]
                np.add.at(acc[f], (ck, pos), 1)
                totals[f] += np.bincount(ck, minlength=ncat[f])
    flush()
    log(f"  tracks: {n_used:,} fragments from {len(bc):,} barcodes over {len(seen_chroms)} chromosomes")
    if n_used == 0:
        raise ValueError("tracks: no fragment barcodes matched the observation names; set `barcode_column:` to the obs column that holds them")

    _write_bigwig(pybigwig, tdir / "all.bw", sizes, nonzero_all, bin_, 1e6 / max(total_all, 1))
    by: list[TrackSet] = []
    for f in fields:
        fdir = tdir / f
        fdir.mkdir()
        paths: dict[str, str] = {}
        for k, label in enumerate(categories[f]):
            if totals[f][k] == 0 or label == "NA":  # unlabelled cells are not a group anyone wants a track for
                continue
            p = fdir / f"{_slug(label)}.bw"
            _write_bigwig(pybigwig, p, sizes, nonzero[f][k], bin_, 1e6 / totals[f][k])
            paths[label] = f"tracks/{f}/{p.name}"
        by.append(TrackSet(field=f, categories=paths))
        log(f"  tracks: {f}: {len(paths)} categories")

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
    with open(tdir / "chrom.sizes", "w") as fh:
        fh.writelines(f"{c}\t{n}\n" for c, n in sizes.items())
    return TracksInfo(genome=spec.genome, bin=bin_, all="tracks/all.bw", by=by, peaks=peaks_path, genes=genes_path, links=links_path, chromSizes="tracks/chrom.sizes")


def write_fragments(path: Path, rows: list[tuple[str, int, int, str]]) -> Path:
    """A small coordinate-sorted fragments.tsv.gz (tests and the synthetic dataset)."""
    rows = sorted(rows, key=lambda r: (r[0], r[1]))
    with gzip.open(path, "wt") as fh:
        fh.write("# synthetic fragments\n")
        fh.writelines(f"{c}\t{s}\t{e}\t{b}\t1\n" for c, s, e, b in rows)
    return path
