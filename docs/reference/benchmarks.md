# Benchmarks

What the benchmark scripts measure and how to run them on a bundle of your own. The protocol is `design/benchmarks.md`
in the repository. The measured tables for the example datasets (what a build costs and how the viewer behaves, on a
named machine at a named commit) belong to the paper and live in its repository, not here: they go stale with every
commit and machine, and this repository carries only what measures.

## Build

`benchmarks/build_bench.sh <name> <dataset.yaml>` runs `spatialscape build` from a clean output folder under
`/usr/bin/time -l` (wall time, CPU time, peak RSS of the process) and then `benchmarks/bundle_size.py`, which counts
the bundle's bytes per store: expression (gene-major, `expr.zarr`), rows (cell-major, `rows.zarr`), images (OME-Zarr
pyramids), shapes (cell polygons and segmentation tiles), molecules (transcript tiles) and tracks (genome coverage),
and divides them by the cells or transcripts in the bundle. The report is `build-<name>.json` with the log beside it.
For a cluster job, SLURM's accounting (`sacct`: elapsed, CPU time, MaxRSS of the batch step) gives the same columns
and `bundle_size.py` alone gives the sizes.

## Viewer

`benchmarks/viewer_bench.mjs` drives the app in a headed Chrome (1440 × 860 CSS pixels at 2× scale) through
Playwright against `spatialscape serve` on the same machine, so no network sits between the browser and the data.
It reads the viewer's own instrumentation: the store's gene-switch timings (data ready, first frame drawn with it),
the controller's tally of what the last layer build put on screen, and `requestAnimationFrame` timestamps during
a scripted 10 s pan (a slow circle of 240 px radius). Requests and bytes are Playwright's page events, which include
the data worker's range requests. The report is `viewer-<name>.json`.

**Cold load and gene switch.** Ready is the store's `ready` state (manifest read, every sample's metadata loaded);
the first frame with cells is the first frame whose pixels are not background. The gene switch is measured on the
focused section over 20 genes drawn at random from the dataset's gene list, each first cold (never requested in this
tab) then again cached: "data" is the time to the gene's values being in memory, "frame" the time to the first
frame drawn with them. On a bundle with genome tracks the script waits for the panel's coverage reads after each
switch, so they count toward the switch that caused them.

**States.** Overview is every sample in the fitted grid; one section is the largest section focused; the 1 mm
window spans 1000 µm across the short side of the pane, centred on that section, where cell polygons replace dots
once a section's visible shape tiles are loaded; the molecules state halves that window until the viewer draws
transcripts (it refuses when more than about a million would be visible, and says so). Dots drawn is the LOD prefix
summed over the visible samples: the viewer draws about 0.6 points per screen pixel of each sample's footprint.
Frame times are per `requestAnimationFrame` tick, so on a 120 Hz display 8.3 ms is a frame at the display's rate;
"over 16.7 ms" counts frames that would have stuttered at 60 Hz.

## Fidelity

Does what the viewer shows equal the data? `python -m spatialscape.fidelity` reads a built bundle back and measures
it against the source; the checks, their bounds and the browser-side region test are in `benchmarks/README.md`. It
runs in CI on the synthetic dataset.

## Run

```bash
# a build row (the output folder is scratch; the dataset's own bundle is not touched)
bash benchmarks/build_bench.sh amygdala examples/amygdala.yaml

# the viewer rows of one dataset
spatialscape serve examples --port 8790
node benchmarks/viewer_bench.mjs --app http://127.0.0.1:8790 --data http://127.0.0.1:8790/amygdala --name amygdala --section xen_Br9192
```

Reports land in `benchmarks/results/`, which is not tracked here; `BENCH_RESULTS=<folder>` and `--out <file>` put
them somewhere else, such as the paper's repository.
