"""Gene models for the genome panel: one collapsed model per gene (the union of its exons), per chromosome.

Sources (`tracks.genes` in the yaml): a GTF (Cell Ranger, GENCODE, Ensembl), a UCSC genePred table such as
refGene.txt.gz, a BED (12 columns with blocks, or 3-6 columns of plain spans), or the keyword `refseq`, which
downloads the UCSC RefSeq table for the genome once into the user cache (~/.cache/spatialscape). Written as

    tracks/genes/index.json    {"source": ..., "chroms": {"chr1": ["DDX11L1", ...], ...}}   names, for search
    tracks/genes/<chrom>.json  [[name, strand, start, end, [exon starts], [exon ends]], ...]  sorted by start

Coordinates are 0-based half-open (BED style); strand is 1, -1, or 0 when unknown. The viewer loads the index
once and one chromosome at a time.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

Log = Callable[[str], None]
REFSEQ_URL = "https://hgdownload.soe.ucsc.edu/goldenPath/{genome}/database/refGene.txt.gz"
REFSEQ_GENOMES = {"hg38", "hg19", "mm10", "mm39", "rn6", "rn7", "danRer11", "dm6", "ce11", "sacCer3"}  # UCSC assemblies with a refGene table
KEYWORDS = {"refseq", "none"}
STRAND = {"+": 1, "-": -1}
# (chrom, name, strand, unit, exon start, exon end), 0-based half-open; `unit` tells transcripts (or rows) apart
Record = tuple[str, str, int, object, int, int]


@dataclass
class GeneModel:
    name: str
    chrom: str
    strand: int
    start: int
    end: int
    exon_starts: list[int] = field(default_factory=list)
    exon_ends: list[int] = field(default_factory=list)

    def row(self) -> list:
        return [self.name, self.strand, self.start, self.end, self.exon_starts, self.exon_ends]


def cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(root) / "spatialscape"


def normalize_chrom(chrom: str, sizes: Mapping[str, int]) -> str | None:
    """Map `1`, `chr1`, `MT` onto the names in chrom.sizes; None drops the record (alt contigs, scaffolds)."""
    if chrom in sizes:
        return chrom
    if chrom.startswith("chr"):
        if chrom[3:] in sizes:
            return chrom[3:]
    elif f"chr{chrom}" in sizes:
        return f"chr{chrom}"
    if chrom in ("MT", "M", "chrMT", "chrM"):
        return next((alt for alt in ("chrM", "MT", "M", "chrMT") if alt in sizes), None)
    return None


def merge_intervals(starts: Iterable[int], ends: Iterable[int]) -> tuple[list[int], list[int]]:
    out_s: list[int] = []
    out_e: list[int] = []
    for s, e in sorted(zip(starts, ends, strict=True)):
        if out_e and s <= out_e[-1]:
            out_e[-1] = max(out_e[-1], e)
        else:
            out_s.append(s)
            out_e.append(e)
    return out_s, out_e


def collapse(records: Iterable[Record]) -> dict[str, list[GeneModel]]:
    """One model per locus of a gene name: transcripts (units) of the same name whose spans overlap are merged into
    the union of their exons; copies elsewhere on the chromosome (the many U6 or Y_RNA genes) stay separate."""
    acc: dict[tuple[str, str], dict[object, tuple[int, list[int], list[int]]]] = {}
    for chrom, name, strand, unit, s, e in records:
        units = acc.setdefault((chrom, name), {})
        cur = units.get(unit)
        if cur is None:
            units[unit] = (strand, [s], [e])
        else:
            cur[1].append(s)
            cur[2].append(e)
    out: dict[str, list[GeneModel]] = {}
    for (chrom, name), units in acc.items():
        spans = sorted(((min(ss), max(ee), strand, ss, ee) for strand, ss, ee in units.values()), key=lambda t: (t[0], t[1]))
        clusters: list[list[tuple[int, int, int, list[int], list[int]]]] = []
        cluster_end = -1
        for span in spans:
            if clusters and span[0] <= cluster_end:
                clusters[-1].append(span)
                cluster_end = max(cluster_end, span[1])
            else:
                clusters.append([span])
                cluster_end = span[1]
        for cluster in clusters:
            ms, me = merge_intervals([x for c in cluster for x in c[3]], [x for c in cluster for x in c[4]])
            out.setdefault(chrom, []).append(GeneModel(name, chrom, cluster[0][2], ms[0], me[-1], ms, me))
    for models in out.values():
        models.sort(key=lambda g: (g.start, g.end, g.name))
    return out


def _chrom_map(chroms: Iterable[str], sizes: Mapping[str, int]) -> dict[str, str | None]:
    return {c: normalize_chrom(c, sizes) for c in set(chroms)}


def _read_gtf(path: Path, sizes: Mapping[str, int]) -> dict[str, list[GeneModel]]:
    """Exon lines of a GTF, named by gene_name (gene_id when absent); streamed in chunks (GENCODE is ~3 M lines)."""
    records: list[Record] = []
    cols = ["chrom", "source", "feature", "start", "end", "score", "strand", "frame", "attrs"]
    reader = pd.read_csv(
        path, sep="\t", header=None, names=cols, usecols=["chrom", "feature", "start", "end", "strand", "attrs"],
        dtype=str, quoting=csv.QUOTE_NONE, chunksize=500_000, na_filter=False,
    )
    for chunk in reader:
        ex = chunk[chunk["feature"] == "exon"]
        if ex.empty:
            continue
        cmap = _chrom_map(ex["chrom"].unique(), sizes)
        chrom = ex["chrom"].map(cmap)
        keep = chrom.notna()
        if not keep.any():
            continue
        ex = ex[keep]
        chrom = chrom[keep]
        names = ex["attrs"].str.extract(r'gene_name "([^"]+)"', expand=False)
        names = names.fillna(ex["attrs"].str.extract(r'gene_id "([^"]+)"', expand=False))
        units = ex["attrs"].str.extract(r'transcript_id "([^"]+)"', expand=False).fillna(names)
        ok = names.notna()
        starts = ex["start"].astype("int64").to_numpy() - 1  # 1-based inclusive -> 0-based half-open
        ends = ex["end"].astype("int64").to_numpy()
        strands = ex["strand"].map(STRAND).fillna(0).astype(int).to_numpy()
        for c, n, st, u, s, e, k in zip(chrom.to_numpy(), names.to_numpy(), strands, units.to_numpy(), starts, ends, ok.to_numpy(), strict=True):
            if k:
                records.append((c, n, int(st), u, int(s), int(e)))
    return collapse(records)


def _read_genepred(path: Path, sizes: Mapping[str, int]) -> dict[str, list[GeneModel]]:
    """UCSC genePred / genePredExt, with or without the leading `bin` column of a table dump (refGene.txt.gz)."""
    df = pd.read_csv(path, sep="\t", header=None, dtype=str, quoting=csv.QUOTE_NONE, na_filter=False, comment="#")
    if df.shape[1] < 10:
        raise ValueError(f"{path}: not a genePred table (expected at least 10 tab-separated columns)")
    off = 1 if df.iloc[0, 3] in ("+", "-", ".") and df.shape[1] >= 11 else 0  # bin, name, chrom, strand, ...
    name = df.iloc[:, off]
    name2_col = off + 11
    if df.shape[1] > name2_col:
        name2 = df.iloc[:, name2_col]
        name = name2.where(name2 != "", name)
    chrom = df.iloc[:, off + 1].map(_chrom_map(df.iloc[:, off + 1].unique(), sizes))
    strand = df.iloc[:, off + 2].map(STRAND).fillna(0).astype(int)
    records: list[Record] = []
    for i, (c, n, st, es, ee) in enumerate(zip(chrom, name, strand, df.iloc[:, off + 8], df.iloc[:, off + 9], strict=True)):
        if c is None or not isinstance(c, str):
            continue
        for s, e in zip(es.strip(",").split(","), ee.strip(",").split(","), strict=True):
            records.append((c, n, int(st), i, int(s), int(e)))
    return collapse(records)


def _read_bed(path: Path, sizes: Mapping[str, int]) -> dict[str, list[GeneModel]]:
    """BED12 (blocks become exons) or plain BED3-6 spans (one block per gene, strand from column 6 when present)."""
    df = pd.read_csv(path, sep="\t", header=None, dtype=str, quoting=csv.QUOTE_NONE, na_filter=False, comment="#")
    ncol = df.shape[1]
    chrom = df.iloc[:, 0].map(_chrom_map(df.iloc[:, 0].unique(), sizes))
    records: list[Record] = []
    for i, c in enumerate(chrom):
        if not isinstance(c, str):
            continue
        s, e = int(df.iat[i, 1]), int(df.iat[i, 2])
        n = df.iat[i, 3] if ncol > 3 and df.iat[i, 3] else f"{c}:{s + 1}-{e}"
        st = STRAND.get(df.iat[i, 5], 0) if ncol > 5 else 0
        if ncol >= 12:
            bsz = [int(x) for x in df.iat[i, 10].strip(",").split(",") if x]
            bst = [int(x) for x in df.iat[i, 11].strip(",").split(",") if x]
            for a, b in zip(bst, bsz, strict=True):
                records.append((c, n, st, i, s + a, s + a + b))
        else:
            records.append((c, n, st, i, s, e))
    return collapse(records)


def read_gene_models(path: Path, sizes: Mapping[str, int]) -> dict[str, list[GeneModel]]:
    """Dispatch on the file name: .gtf, .bed, otherwise a genePred table (all optionally .gz)."""
    name = Path(path).name.lower()
    if name.endswith(".gz"):
        name = name[:-3]
    if name.endswith(".gtf"):
        return _read_gtf(Path(path), sizes)
    if name.endswith((".gff", ".gff3")):
        raise ValueError(f"{path}: GFF3 gene models are not supported; convert to GTF first (for example `gffread -T`)")
    if name.endswith(".bed"):
        return _read_bed(Path(path), sizes)
    return _read_genepred(Path(path), sizes)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh)
    tmp.replace(dest)


def refseq_table(genome: str, *, log: Log = print, cache: Path | None = None) -> Path:
    """The UCSC refGene table for `genome`, downloaded once into the cache."""
    if genome not in REFSEQ_GENOMES:
        raise ValueError(f"no RefSeq gene table for genome {genome!r}; set `genes:` to a GTF, genePred or BED file")
    dest = (cache or cache_dir()) / "genomes" / genome / "refGene.txt.gz"
    if not dest.exists():
        url = REFSEQ_URL.format(genome=genome)
        log(f"  tracks: downloading RefSeq gene models {url} -> {dest}")
        _download(url, dest)
        log(f"  tracks: cached {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def gene_models_for(genes: str | None, genome: str, sizes: Mapping[str, int], *, log: Log = print) -> tuple[dict[str, list[GeneModel]], str] | None:
    """Models and a source label for a `tracks.genes` setting, or None when there is nothing to draw."""
    if genes is None or genes == "none":
        return None
    if genes == "refseq":
        if genome not in REFSEQ_GENOMES:
            log(f"  tracks: no RefSeq gene table for genome {genome!r}; set `genes:` to a GTF, genePred or BED for a gene track")
            return None
        return read_gene_models(refseq_table(genome, log=log), sizes), f"RefSeq ({genome})"
    path = Path(genes)
    return read_gene_models(path, sizes), path.name


def write_gene_models(models: Mapping[str, list[GeneModel]], out_dir: Path, *, source: str, order: Iterable[str] | None = None) -> int:
    """index.json plus one <chrom>.json per chromosome; returns the number of genes written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chroms = [c for c in (order or models) if c in models] if order else list(models)
    index = {"source": source, "chroms": {c: [g.name for g in models[c]] for c in chroms}}
    (out_dir / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    n = 0
    for c in chroms:
        (out_dir / f"{c}.json").write_text(json.dumps([g.row() for g in models[c]], separators=(",", ":")))
        n += len(models[c])
    return n
