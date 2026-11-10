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
