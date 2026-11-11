# Reproduce the examples

The eleven public example apps are live in the [examples gallery](https://mictott.github.io/spatialscape/). They are built from
<https://github.com/MicTott/spatialscape-examples>: one folder per dataset
with the script that fetches the published files, the script (when one is needed) that turns them into an AnnData,
the `dataset.yaml` that describes the app, and a README with the source, the licence and what each step costs.
Nothing in an app is edited by hand; every one rebuilds from those files, on a laptop or on a cluster.

| Folder | Technology | Scale | Source | Live app |
|---|---|---|---|---|
| `visium-human-dlpfc` | Visium, H&E, manual layer labels | 12 sections, 47,681 spots | spatialLIBD (Maynard et al. 2021) | [open](https://mictott.github.io/spatialscape/?d=visium-human-dlpfc) |
| `visium-cytassist-mouse-brain` | Visium CytAssist, H&E | 1 section, 2,310 spots | 10x Genomics | [open](https://mictott.github.io/spatialscape/?d=visium-cytassist-mouse-brain) |
| `visium-hd-mouse-brain` | Visium HD, 8 µm bins, H&E | 1 section, 394k bins | 10x Genomics | [open](https://mictott.github.io/spatialscape/?d=visium-hd-mouse-brain) |
| `xenium-mouse-brain` | Xenium Prime 5K: image, shapes, nuclei, transcripts | 1 section, 63k cells | 10x Genomics | [open](https://mictott.github.io/spatialscape/?d=xenium-mouse-brain) |
| `atera` | Atera whole-transcriptome in situ: morphology, shapes, transcripts | 2 sections, 888k cells, 1.66 billion transcripts | 10x Genomics previews | [open](https://mictott.github.io/spatialscape/?d=atera) |
| `merscope-mouse-brain` | MERSCOPE: boundaries, transcripts, mosaics | 3 slices, 233k cells | Vizgen | [open](https://mictott.github.io/spatialscape/?d=merscope-mouse-brain) |
| `cosmx-nsclc` | CosMx SMI: cell types and niches, boundaries, transcripts, composites | 8 sections, 800k cells | NanoString (He et al. 2022) | [open](https://mictott.github.io/spatialscape/?d=cosmx-nsclc) |
| `phenocycler-lymph-node` | PhenoCycler spatial proteomics: 56-channel image, cell outlines, gated cell types | 3 cores, 46,671 cells, 56 proteins | BioImage Archive S-BIAD2100 | [open](https://mictott.github.io/spatialscape/?d=phenocycler-lymph-node) |
| `spatial-atac-rna-mouse-brain` | spatial ATAC + RNA: RNA on 20 µm pixels, ATAC tracks per cluster | 3 sections, 14k pixels | GEO GSE205055 | [open](https://mictott.github.io/spatialscape/?d=spatial-atac-rna-mouse-brain) |
| `pbmc-multiome` | 10x Multiome: RNA and ATAC UMAPs of the same nuclei, ATAC tracks per cell type | 11,577 nuclei | 10x Genomics | [open](https://mictott.github.io/spatialscape/?d=pbmc-multiome) |
| `abc-atlas` | whole mouse brain: 59 MERFISH sections and all 10x nuclei on Allen's UMAP | 4.0 M cells + 4.0 M nuclei | Allen Brain Cell Atlas | [open](https://mictott.github.io/spatialscape/?d=abc-atlas) |

## Start with an R object

`visium-human-dlpfc` is the example to read first: it starts from the spatialLIBD `SpatialExperiment` and has no
prepare step. Its `build.sh` runs the four commands of the object-first path on this site's
[Getting started](./getting-started#goal-2-your-own-data-on-your-machine) page, on a real object:

```bash
git clone https://github.com/MicTott/spatialscape-examples && cd spatialscape-examples
bash setup_env.sh && source env/bin/activate      # the spatialscape release the apps were built with
cd visium-human-dlpfc && bash build.sh            # download.R, init, build, validate: under two minutes
spatialscape serve bundles --open
```

The committed `dataset.yaml` (34 lines) is what was kept of the 100-line menu `init` writes; `diff
dataset.init.yaml dataset.yaml` after the run shows exactly those choices. Needs R with spatialLIBD installed; without
R, `fetch_processed.sh` below gives the same `.rds`.

## Three commands for any of them

The processed objects of every dataset except `abc-atlas` are deposited with the repository in one Zenodo record
(the DOI is in the repository's README once the record is published), so an app rebuilds without the raw download
and without the prepare step:

```bash
bash fetch_processed.sh xenium-mouse-brain        # the processed objects, checksums verified
spatialscape build xenium-mouse-brain/dataset.yaml
spatialscape serve xenium-mouse-brain/bundles --open
```

The yaml also points at the published files in `raw/` for the layers that stay with the publisher (the image, the
cell shapes, the transcripts). When those are absent the build says so and leaves them out; `bash
xenium-mouse-brain/download.sh` fetches them, and the next `build` adds them. To go from the published files
instead, every folder's README lists the same three steps: `download.sh` → `prepare.py` → `build`.

## On a cluster

Each folder's `slurm/` has the same steps as SLURM jobs with the memory and time each one needed; the README of
the repository says how to chain them. The Allen atlas is the one dataset that is cluster-scale (215 GB of
processed objects, about a day of jobs) and is not on Zenodo; its raw data are Allen's own public bucket.

## What a run costs

Every dataset README has a table of its steps with the time, peak memory and disk each one took on a laptop or on
the cluster job named, so you know before you start whether it fits your machine; the measured build and viewer
tables of the paper come from the same bundles ([Benchmarks](../reference/benchmarks)).
