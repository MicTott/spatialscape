# Genome tracks


A sample with a fragment file can carry genome tracks: pseudobulk accessibility (Tn5 insertions per million,
binned) per category of the fields you name, built once by `build` and streamed by the viewer's genome panel.

```yaml
  - id: atac
    platform: snrnaseq
    kind: embedding
    path: pbmc.h5ad
    coords: obsm/X_umap_atac
    tracks:
      fragments: atac_fragments.tsv.gz    # Cell Ranger (ARC / ATAC) fragments, coordinate-sorted, bgzipped
      by: [cell_type]                     # one track per category of each field listed
      genome: hg38                        # assembly: names the RefSeq gene models and the chromosome sizes (hg38, mm10, mm39 built in)
      # genes: genes.gtf.gz               # gene models: a GTF, a UCSC genePred table or a BED (default `refseq`)
      # links: links.bedpe                # optional: peak-gene links
      # bin: 25, chrom_sizes: sizes.tsv, barcode_column: barcode
```

Fragment barcodes are matched to the observation names (or to `barcode_column`). Peaks are recognised among the
sample's features by name (`chr1:9790-10675`, with or without a `peak: ` prefix) and written as a BED track.
Building tracks needs `pip install "spatialscape[tracks]"` (pyBigWig); streaming a 2 GB fragment file takes a
few minutes and never decompresses it to disk.

## Several runs in one object

An object pooled from several 10x runs has colliding barcodes (`AAACAGCCAAGGAATC-1` exists in every run), so list
one fragment file per run and name the obs column that says which run each observation came from:

```yaml
    tracks:
      fragments: { Br2743: runs/Br2743/atac_fragments.tsv.gz, Br6423: runs/Br6423/atac_fragments.tsv.gz }
      sample_column: donor                # obs column holding Br2743 / Br6423 per observation
      by: [cell_type]
```

Observations are matched within their run, by `barcode_column` or by their names with the run's prefix or suffix
removed (`Br2743#AAAC…-1` as ArchR names cells, `Br2743_AAAC…-1`, `AAAC…-1_Br2743`). A category's track sums
its cells over every run and is then scaled to insertions per million, so donors weigh in by their cell numbers.

`normalize:` sets what each group's track is scaled by: `nfrags` (default) divides by the group's total insertions
(per million; Signac's `RC`, ArchR's `nFrags`); `tss` divides by its insertions within `tss_window` bp (50) of a gene
TSS (ArchR's `ReadsInTSS`), which keeps a group with noisier libraries from looking weaker everywhere; `cells` divides
by its number of nuclei. `bin:` (25 bp) sets the tile size; dense pooled data is better served by `bin: 100`, ArchR's
default, which also keeps the bigWigs a fraction of the size.

A fragment file may live on another machine: `ssh://host/abs/path/atac_fragments.tsv.gz` is read through
`ssh host cat …` in one pass while the tracks are counted, so nothing is copied to the building machine (a
rebuild streams it again). The build asks the same host for the file's size and date to decide whether the
sample is stale. Your ssh key must be loaded, and the host must allow non-interactive logins; `${VAR}` in the URL is expanded, so a login can stay out of the yaml (`ssh://${CLUSTER_USER}@host/...`).

## Tracks you already have

If another tool exported per-group bigWigs (ArchR `getGroupBW`, Signac `ExportGroupBW`, `bamCoverage` per group),
copy them in instead of streaming fragments. Name the files by a template with `{label}`, filled with the field's
category labels (or the raw labels its `aliases` map onto them), or list them label by label:

```yaml
    tracks:
      bigwigs:
        by:
          cell_type: GroupBigWigs/cell_type/{label}-TileSize-100-normMethod-ReadsInTSS-ArchR.bw
          # leiden: { "0": bw/cluster0.bw, "1": bw/cluster1.bw }
        all: GroupBigWigs/all.bw            # optional
      units: reads in TSS, normalized       # shown on the panel's scale
      genome: hg38
```

Categories without a file get no track (the build log says which). The bin size is read from the files, and when
the genome is not a known assembly the chromosome names and sizes come from the files too.

Gene models come from `genes:`: the reference's own GTF (for 10x data, `genes/genes.gtf.gz` inside the Cell Ranger
reference, which matches the matrix exactly), a UCSC genePred table such as `refGene.txt.gz`, or a BED (12 columns
with blocks, or plain spans). Without `genes:`, `refseq` downloads UCSC's RefSeq table for the genome once (about
8 MB for hg38, kept in `~/.cache/spatialscape`); `none` leaves the gene track out, as does a genome UCSC does not
know. Transcripts of a gene are collapsed into one model per locus (the union of their exons) and written per
chromosome, so the viewer loads only the chromosome on screen.

The viewer side is in [Using the viewer](./viewer#genome-panel).
