# Benchmarks: what we will measure, on what, and how it is reported

A plan, not results. The viewer's claims (a gene switch is one request, panning stays smooth on large sections,
billions of transcripts can be browsed) are true in the sense the architecture makes them true, but the README
quoted numbers without a protocol. This page fixes the protocol first; the numbers come from running it and go into
`docs/reference/benchmarks.md` with the raw logs under `benchmarks/results/`.

Three questions, each with its own table:

1. **Build.** What does it cost to turn an object into a bundle, and how big is the bundle?
2. **Viewer.** How long do loading, a gene switch and a pan take, on what hardware, drawing how many points?
3. **Fidelity.** Does what the viewer shows equal the data: expression after 8-bit quantisation, positions after
   the frame transforms, selections and tests against the same computation done offline?

Every table row names the dataset, the commit (`spatialscape --version`, `git rev-parse HEAD`), the machine, the
browser and the exact command or script. Nothing is reported from memory or a screenshot.

## Datasets

Fixed set, each with a provenance block (source URL or accession, file checksums, preprocessing script, yaml):

| Name | What it stands for | Cells | Genes | Transcripts | Images |
|---|---|---|---|---|---|
| synthetic | the committed example, every feature on | 6,800 | 50 | 1.2 M synthetic | 1 small |
| amygdala | the paper's atlas: 3 platforms, 16 sections, 2 references | 1.56 M | 35 k | 46–117 M per Xenium section, 4 sections | H&E and DAPI |
| atera | one whole-transcriptome Xenium section | 0.3 M | 18 k | ~250 M | DAPI, 0.425 µm |
| allen | the whole-brain embedding: the largest matrix | 4 M | 1.1 k | none | none |
| habenula | multiome with tracks: the genome panel | 375 k | 35 k | none | H&E |
| transcripts-1B | a dataset whose transcript coordinates pass 10⁹: several Xenium Prime sections, or a public MERSCOPE whole-brain run (candidates: 10x Xenium Prime 5K mouse brain series; Vizgen MERFISH mouse brain receptor map) | TBD | TBD | > 1 B | yes |

The last row is the one the "billions of transcripts" claim rests on. It does not exist as a bundle yet; building
it is part of this work, and until it is built the claim is removed from the README.

## 1. Build

Per dataset, from `/usr/bin/time -l` (macOS) or `-v` (Linux) around `spatialscape build`, on the machine named:

- input: object or files, their size on disk, cells and genes before and after the build's filters (all-zero genes
  listed in `zero_genes.json`, dropped control features, cells outside images)
- wall time, CPU time, peak RSS, scratch space used (`bundles/.cache`), threads
- bundle size in total and per store: `expr.zarr`, `rows.zarr`, images, `shapes.bin`, `molecules.bin`, `tracks/`
- bytes per cell for expression and rows, bytes per transcript, bytes per polygon vertex

Two machines: a laptop (M1 Pro, 32 GB) and a JHPCE node (the sbatch request named). The Allen row is the memory
story (the 60 GB figure in the changelog), the atera row the image story, transcripts-1B the molecule story.

## 2. Viewer

Measured by a Playwright script against `spatialscape serve` on the same machine (localhost, no network) and
against the CloudFront deployment (network named: wired, Wi-Fi, a throttled profile), in Chromium with a 1440×860
viewport at device scale 2. Headless Chromium uses SwiftShader and is only good for correctness, so frame timings
come from the headed browser via `window.__sscape.timings` and a `requestAnimationFrame` sampler, with the GPU
named (the M1 Pro's, and one discrete desktop GPU).

For each dataset and each of these states:

| State | What is on screen |
|---|---|
| overview | every section in the grid at the fitted zoom |
| one section | a section focused at the zoom that first draws every cell |
| zoomed | a 1 × 1 mm window with cell shapes, then with transcripts |

report:

- **points drawn**, not points in the dataset: the LOD prefix per sample at that zoom (the controller exposes it),
  plus shapes and molecules drawn
- **cold load**: navigation to first frame with cells, and bytes transferred
- **gene switch**: data-ready and first-frame-with-it times, cold (not cached) and cached, median and 95th
  percentile over 20 genes
- **pan and zoom**: frame-time median and 95th percentile over a scripted 10 s pan, and the fraction of frames
  over 16.7 ms
- **memory**: the tab's JS heap and GPU memory from `performance.measureUserAgentSpecificMemory` and the
  task manager, after the state is reached
- **requests**: count and bytes per state, so "one range request per gene" is a measured row

The comparison tools: Vitessce (the amygdala's existing Vitessce bundle), CartoScope, TissUUmaps and Celldega, each
on the same amygdala sections with the same task script where their configuration allows it: open, colour by one
gene, switch gene, zoom to a 1 mm window, lasso 10,000 cells. Report what each tool loads and draws for that task and
where the workflow differs, not a feature checklist.

## 3. Fidelity

Offline computation in Python against the same bundle, as tests that run in CI on the synthetic dataset and as a
script on the real ones:

- **expression**: for 200 random genes, the dequantised values against the source matrix: max absolute error
  (bounded by gmax/510), Pearson and Spearman correlation, fraction of zeros preserved exactly
- **positions**: cell centroids, shape vertices and molecule coordinates against the source files after the frame
  transforms, in microns; images against known landmarks (fiducials on Visium, nuclei under DAPI on Xenium)
- **selections and regions**: a lasso's cell ids against a point-in-polygon computed offline
- **the browser test**: for a drawn region pair, the viewer's Wilcoxon p, log2FC and fractions against
  `scipy.stats.mannwhitneyu` and numpy on the same cells, including the two cases the review found (a gene absent
  from one section's panel; raw-valued data)
- **rare populations**: a category with 50 cells among a million at overview zoom: is it drawn, and how many of
  its cells survive the LOD prefix

## Order of work

1. The fidelity scripts first, on synthetic and amygdala; they are also the regression tests the review asked for.
2. Build and viewer tables on the laptop for synthetic, amygdala and atera.
3. Build transcripts-1B; its build and viewer rows.
4. The comparison tools on the amygdala sections.
5. Publish the tables and the scripts; put the README sentence back with its numbers and a link.
