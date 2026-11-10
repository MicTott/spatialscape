# Benchmarks

The protocol is in [design/benchmarks.md](../design/benchmarks.md). This folder holds what has been run: the scripts
are in the package and the app, the raw reports land in `results/`.

## Fidelity

Does what the viewer shows equal the data? `python -m spatialscape.fidelity` reads a built bundle back with the same
decoders `validate` uses and the source through the package's readers, then measures the difference. It runs in
CI on the synthetic dataset ([python/tests/test_fidelity.py](../python/tests/test_fidelity.py)) and on a real
bundle like this:

```bash
SPATIALAMYGDALA=~/Documents/R/spatialAmygdala python -m spatialscape.fidelity bundle examples/amygdala.yaml examples/amygdala \
  --sample xen_Br9192 --sample vis_Br9280 --sample hd_Br9280_CeA --sample sn_totty --out benchmarks/results/fidelity-amygdala.json
```

What it checks, and the bound each must meet:

| Check | Against | Bound |
|---|---|---|
| expression | the normalised source column, 200 random genes | half a code step, `(gmax − gmin) / 510`; a positive value under half a step is rounded up to code 1 (one step); zeros exact |
| rows | the same source rows, and the gene-major codes | identical codes; the same bound |
| positions | source coordinates through the micron rule, flip, rotation and shift | float32: under 1e-3 µm; `order` is the build's permutation; ids match |
| shapes | the source polygons through the same frame | half the 0.1 µm grid, every ring present |
| molecules | the source table past the Q20 and control-feature filters, 20 genes | counts equal; nearest neighbour within the 1/64 µm grid |
| zero genes | all-zero source columns | the list has exactly those |

The browser's own computations are checked by [app/e2e/fidelity.spec.ts](../app/e2e/fidelity.spec.ts): regions
drawn through the store must select exactly the cells an offline point-in-polygon selects, and the region test's
statistics (log2FC, p, adjusted p, AUROC, fractions, agreeing sections) must match the reference computed from the
row store with scipy's asymptotic Mann-Whitney:

```bash
cd app && npx playwright test fidelity          # writes test-results/fidelity-regions-test.json and the report
python -m spatialscape.fidelity browser-de app/test-results/fidelity-regions-test.json examples/synthetic
```

Tolerances there are float32 storage: 1e-3 in log10 p above the float32 underflow, 2e-4 in log2FC, 1e-5 in AUROC.

The quantisation's effect on the test itself (the same cells, source floats against dequantised codes) is measured
in `test_reference_test_is_scipy_on_the_dequantised_rows`: on log1p(CP10k) data the codes move log10 p by a few
hundredths and no gene crosses 0.05; values under half a code step tie at code 1, which makes the test slightly
conservative where a gene has many such values.

### Results so far

- `results/fidelity-amygdala.json` (2026-11-06, commit afd9a44, laptop): xen_Br9192 (267,091 cells, 200 genes, every
  ring, 20 genes of molecules), vis_Br9280, hd_Br9280_CeA and sn_totty against the Vitessce-era AnnData stores and the
  5 µm Xenium outputs. Every bound holds: expression within half a code step with zeros exact, rows equal to the
  gene-major codes, positions within 1e-3 µm, shape vertices within 0.05 µm, molecules within the 1/64 µm grid, the
  zero-gene lists complete. The run before the rebuild found the tile-edge rounding described in the changelog.

## Build and viewer tables

Run with `build_bench.sh` (one timed `spatialscape build` per row, with `bundle_size.py` for the bytes per store) and
`viewer_bench.mjs` (a headed Chrome through Playwright: cold load, what is drawn at three states, requests and bytes,
gene switches cold and cached, frame times over a scripted pan). The JSON reports are in `results/` as
`build-*.json` and `viewer-*.json` (`build-jhpce-*.json` are the cluster jobs' accounting plus the bundle sizes
measured there), and `tables.py --write` renders them into
[docs/reference/benchmarks.md](../docs/reference/benchmarks.md), the page that explains the columns.
