# Benchmarks

The protocol is in [design/benchmarks.md](../design/benchmarks.md); what each script measures and how to run it is in
[docs/reference/benchmarks.md](../docs/reference/benchmarks.md). Reports land in `results/` (untracked) unless
`BENCH_RESULTS` or `--out` says otherwise. The measured tables for the example datasets are kept with the paper, in
its repository, not here.

## Fidelity

Does what the viewer shows equal the data? `python -m spatialscape.fidelity` reads a built bundle back with the same
decoders `validate` uses and the source through the package's readers, then measures the difference. It runs in
CI on the synthetic dataset ([python/tests/test_fidelity.py](../python/tests/test_fidelity.py)) and on a real
bundle like this:

```bash
python -m spatialscape.fidelity bundle dlpfc.yaml bundles/dlpfc \
  --sample 151673 --sample 151507 --out benchmarks/results/fidelity-dlpfc.json
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

## Build and viewer tables

`build_bench.sh` (one timed `spatialscape build` per row, with `bundle_size.py` for the bytes per store) and
`viewer_bench.mjs` (a headed Chrome through Playwright: cold load, what is drawn at three states, requests and bytes,
gene switches cold and cached, frame times over a scripted pan) each write one JSON report per dataset. The paper's
repository holds the reports for the example datasets and renders them into its tables.
