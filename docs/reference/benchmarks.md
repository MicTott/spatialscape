# Benchmarks

What a build costs and how the viewer behaves, measured under the protocol in the repository's
`design/benchmarks.md`. Every number here was produced by a script in `benchmarks/` and is kept as a JSON report
under `benchmarks/results/`; the tables are rendered from those reports by `benchmarks/tables.py`, not typed in.
The fidelity checks (does what the viewer shows equal the data) are described in `benchmarks/README.md`.

## Machines

| Name | Hardware | Software |
|---|---|---|
| laptop | Apple M1 Max, 10 cores, 64 GB, 120 Hz display | macOS 15.6, Google Chrome 157, spatialscape 0.6.0 at the commit named in each report |
| JHPCE | one node of the JHPCE cluster per job, the SLURM request named in the row | Python 3.14, spatialscape 0.6.0 (commit afd9a44, the 1.0 data), one `sbatch` per build |

## Build

`spatialscape build` from a clean output folder. Laptop rows: `/usr/bin/time -l` around the command
(`benchmarks/build_bench.sh`), peak RSS of the process. Cluster rows: SLURM's accounting for the job (`sacct`:
elapsed, CPU time, MaxRSS of the batch step). Bundle sizes are file bytes per store (`benchmarks/bundle_size.py`):
expression (gene-major, `expr.zarr`), rows (cell-major, `rows.zarr`), images (OME-Zarr pyramids), shapes
(cell polygons and segmentation tiles), molecules (transcript tiles) and tracks (genome coverage). The last three
columns divide those by the cells or transcripts in the bundle.

<!-- build-table -->
<!-- /build-table -->

\* The Allen atlas job's MaxRSS counts the page cache of the 106 GB matrix streamed through it, above the 192 GB
the job requested; the process itself fit the request.

Three rows need a word. The DLPFC laptop row reads the SpatialExperiment through the conversion cache its folder
already had (a first run converts the `.rds` once more, about ten seconds). The habenula row streams the two
ATAC fragment files (8.7 GB) from the cluster over ssh while it builds the coverage tracks, so its wall time
includes that transfer. The laptop and the cluster are not comparable machine to machine: the cluster rows ran on
shared nodes with four CPUs, the laptop rows on ten cores with nothing else running.

The processed inputs behind each row are the ones the examples repository's scripts write; their sizes are in each
dataset's README there.

## Viewer

`benchmarks/viewer_bench.mjs` drives the app in a headed Chrome (1440 × 860 CSS pixels at 2× scale) through
Playwright against `spatialscape serve` on the same machine, so no network sits between the browser and the data.
It reads the viewer's own instrumentation: the store's gene-switch timings (data ready, first frame drawn with it),
the controller's tally of what the last layer build put on screen, and `requestAnimationFrame` timestamps during
a scripted 10 s pan (a slow circle of 240 px radius). Requests and bytes are Playwright's page events, which include
the data worker's range requests.

**Cold load and gene switch.** Ready is the store's `ready` state (manifest read, every sample's metadata loaded);
the first frame with cells is the first frame whose pixels are not background. The gene switch is measured on the
focused section over 20 genes drawn at random from the dataset's gene list, each first cold (never requested in this
tab) then again cached: "data" is the time to the gene's values being in memory, "frame" the time to the first
frame drawn with them.

**States.** Overview is every sample in the fitted grid; one section is the largest section focused; the 1 mm
window spans 1000 µm across the short side of the pane, centred on that section, where cell polygons replace dots
once a section's visible shape tiles are loaded; the molecules state halves that window until the viewer draws
transcripts (it refuses when more than about a million would be visible, and says so). Dots drawn is the LOD prefix
summed over the visible samples: the viewer draws about 0.6 points per screen pixel of each sample's footprint, so
the overview of a 1.56 M-cell atlas draws about 100 k dots. Frame times are per `requestAnimationFrame` tick on a
120 Hz display, so 8.3 ms is a frame at the display's rate; the "over 16.7 ms" column counts frames that would have
stuttered at 60 Hz.

<!-- viewer-tables -->
<!-- /viewer-tables -->

## What the tables say

- **Opening an app** takes under a second to the first frame with cells on every dataset, from 2 thousand spots
  to 1.56 million cells, because the viewer reads each section's metadata and the default gene and nothing else;
  the bytes it fetches are the manifest, the per-section index files, the thumbnails and the first image levels.
- **A gene switch is one range request per section**, plus an 8 KB read of the shard index the first time a
  section's shard of 502 genes is touched. Cold switches take tens of milliseconds on localhost; a cached switch
  is one to two frames. On the two bundles with genome tracks the panel re-reads its coverage slices on every
  switch, cached or not, which is where their extra requests come from; caching them is an open item.
- **What is drawn is bounded by the screen, not the data.** The overview of the amygdala atlas draws about 100
  thousand of its 1.56 million cells and the Atera overview about 190 thousand of 888 thousand; zooming in trades
  dots for polygons and, once fewer than about a million would be visible, molecules. Every state on every
  dataset panned at the display's rate (120 Hz, 8.3 ms a frame) with no frame over 16.7 ms, including the Atera
  window with 609 thousand molecules and 3.5 thousand polygons on screen.
- **Memory** stays under half a gigabyte of JS heap in the heaviest state measured (Atera with molecules).

## Reproduce

```bash
# a build row (the output folder is scratch; the dataset's own bundle is not touched)
bash benchmarks/build_bench.sh amygdala examples/amygdala.yaml

# the viewer rows of one dataset
spatialscape serve examples --port 8790
node benchmarks/viewer_bench.mjs --app http://127.0.0.1:8790 --data http://127.0.0.1:8790/amygdala --name amygdala --section xen_Br9192

# the tables on this page
python benchmarks/tables.py --write
```
