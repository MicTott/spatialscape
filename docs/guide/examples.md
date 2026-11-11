# Reproduce the examples

The eleven public example apps are live in the [examples gallery](https://mictott.github.io/spatialscape/examples/). They are built from
<https://github.com/MicTott/spatialscape-examples>: one folder per dataset
with download scripts, any required preparation scripts, a `dataset.yaml`, and a README documenting
the data source, license and resource requirements. Check the dataset's README before running its build;
larger examples require a cluster.

| Folder | Technology | Scale | Source | Live app |
|---|---|---|---|---|
| `visium-human-dlpfc` | Visium, H&E, manual layer labels | 12 sections, 47,681 spots | spatialLIBD (Maynard et al. 2021) | [open](https://mictott.github.io/spatialscape/examples/?d=visium-human-dlpfc) |
| `visium-cytassist-mouse-brain` | Visium CytAssist, H&E | 1 section, 2,310 spots | 10x Genomics | [open](https://mictott.github.io/spatialscape/examples/?d=visium-cytassist-mouse-brain) |
| `visium-hd-mouse-brain` | Visium HD, 8 µm bins, H&E | 1 section, 394k bins | 10x Genomics | [open](https://mictott.github.io/spatialscape/examples/?d=visium-hd-mouse-brain) |
| `xenium-mouse-brain` | Xenium Prime 5K: image, shapes, nuclei, transcripts | 1 section, 63k cells | 10x Genomics | [open](https://mictott.github.io/spatialscape/examples/?d=xenium-mouse-brain) |
| `atera` | Atera whole-transcriptome in situ: morphology, shapes, transcripts | 2 sections, 888k cells, 1.66 billion transcripts | 10x Genomics previews | [open](https://mictott.github.io/spatialscape/examples/?d=atera) |
| `merscope-mouse-brain` | MERSCOPE: boundaries, transcripts, mosaics | 3 slices, 233k cells | Vizgen | [open](https://mictott.github.io/spatialscape/examples/?d=merscope-mouse-brain) |
| `cosmx-nsclc` | CosMx SMI: cell types and niches, boundaries, transcripts, composites | 8 sections, 800k cells | NanoString (He et al. 2022) | [open](https://mictott.github.io/spatialscape/examples/?d=cosmx-nsclc) |
| `phenocycler-lymph-node` | PhenoCycler spatial proteomics: 56-channel image, cell outlines, gated cell types | 3 cores, 46,671 cells, 56 proteins | BioImage Archive S-BIAD2100 | [open](https://mictott.github.io/spatialscape/examples/?d=phenocycler-lymph-node) |
| `spatial-atac-rna-mouse-brain` | spatial ATAC + RNA: RNA on 20 µm pixels, ATAC tracks per cluster | 3 sections, 14k pixels | GEO GSE205055 | [open](https://mictott.github.io/spatialscape/examples/?d=spatial-atac-rna-mouse-brain) |
| `pbmc-multiome` | 10x Multiome: RNA and ATAC UMAPs of the same nuclei, ATAC tracks per cell type | 11,577 nuclei | 10x Genomics | [open](https://mictott.github.io/spatialscape/examples/?d=pbmc-multiome) |
| `abc-atlas` | whole mouse brain: 59 MERFISH sections and all 10x nuclei on Allen's UMAP | 4.0 M cells + 4.0 M nuclei | Allen Brain Cell Atlas | [open](https://mictott.github.io/spatialscape/examples/?d=abc-atlas) |

## Start with an R object

The `visium-human-dlpfc` example reads the spatialLIBD `SpatialExperiment` directly. Its `build.sh`
downloads the object, generates a configuration, builds the committed configuration and validates the result.
It follows the workflow in [Getting started](./getting-started#goal-2-your-own-data-on-your-machine):

```bash
git clone https://github.com/MicTott/spatialscape-examples && cd spatialscape-examples
bash setup_env.sh && source env/bin/activate      # the spatialscape release the apps were built with
cd visium-human-dlpfc && bash build.sh            # download.R, init, build, validate
spatialscape serve bundles --open
```

Compare `dataset.init.yaml` with the committed `dataset.yaml` after the run to see which annotations and
display settings the example uses. The download step requires R with spatialLIBD installed.

## Build from published inputs

Each dataset's README lists its download and preparation steps. For example, from the repository root
with the environment active:

```bash
cd xenium-mouse-brain
bash download.sh
python prepare.py
spatialscape build dataset.yaml
spatialscape serve bundles --open
```

Some datasets read the downloaded object directly and do not have a preparation script. The YAML also
references images, boundaries or transcript tables under `raw/`. If an optional file is absent, the build
reports it and omits that layer; downloading the file and rebuilding adds it.

### Processed-data downloads

The repository includes `fetch_processed.sh` for downloading prepared objects from Zenodo. Its default
record ID is currently a placeholder, so this route is not yet available. Use the published-input workflow
above until the repository provides a record ID and DOI. The Allen atlas is excluded from the planned
processed-data archive because of its size.

## On a cluster

Each folder's `slurm/` has the same steps as SLURM jobs with the memory and time each one needed; the README of
the repository says how to chain them. The Allen atlas is the one dataset that is cluster-scale (215 GB of
processed objects, about a day of jobs) and is not on Zenodo; its raw data are Allen's own public bucket.

## Runtime, memory and storage

The dataset READMEs report runtime, peak memory and disk use for the machines or cluster jobs used to build
the examples. Use these reports to estimate requirements for your run. [Benchmarks](../reference/benchmarks)
describes the build and viewer measurements and how to collect them on your own machine.
