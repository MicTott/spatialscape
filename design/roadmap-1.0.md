# Road map to v1.0 and the paper


Written 2026-11-09, agreed with the user the same day (one Zenodo record: the examples repository plus the small
processed objects; large ones rebuild from scripts). Working rules: subtract before adding; one way to do each thing.

## Context

The software is feature-complete for 1.0: format 1 is declared final, the fidelity checks pass on real bundles,
every public example app (8) and every LIBD app (amygdala, dACC, BLA) is rebuilt on the final format, and 0.6.0
is on PyPI. What is left is release engineering, the public face (live site, landing page, docs), and the
reproducibility package the paper needs: a separate examples repository whose scripts anyone can run, with the
processed objects on Zenodo so nobody has to redo the 283 GB downloads to rebuild an app.

The review of the cluster scripts (2026-11-09) found: four of eight examples are minimal (12–19 line prepare
scripts, 18–25 line yamls), three are medium and justified by vendor formats, CosMx is the one hard-to-read script
and yaml, and no example starts from an SCE / Seurat / AnnData object, which is the path most users take.

Sizes that shape the Zenodo plan (processed objects on the cluster): atera 4.2 GB, merscope 3.0 GB, cosmx 2.9 GB,
visium-hd 374 MB, atac-rna 175 MB, xenium 165 MB, cytassist 119 MB; **11 GB without the Allen atlas (215 GB)**.
Built apps: 60 GB in all, 8.6 GB without atera and the Allen atlas.

## Outcome

- `v1.0.0` tagged, on PyPI, with a Zenodo DOI for the software.
- The live gallery and a landing page with every example app open to the public.
- `spatialscape-examples`: a public repo where each dataset is a folder with a download script, an optional
  prepare script, a `dataset.yaml` and a README, reproducible on a laptop from Zenodo in three commands, and on a
  cluster with the same scripts.
- One Zenodo record: the examples repository snapshot plus the processed objects of every dataset small enough
  to ship (all but the Allen atlas, which rebuilds from scripts).
- A bioRxiv preprint with figures taken from the live apps and benchmarks run under the written protocol.

## 1. Release engineering (spatialscape repo)

1. **Redeploy the live site**: viewer + rebuilt examples/{amygdala,dacc,bla} to the bucket and CloudFront
   distribution `E22O6HTOCVH06W`; invalidate; verify the showcase views. Blocked only on the
   user saying go.
2. **Public gallery hosting decision**: host the 8 public apps on S3 next to the LIBD ones (60 GB, ~$1.4/month
   storage plus egress) or only the 6 small ones (8.6 GB) with atera and the Allen atlas linked from the cluster
   mirror later. Recommendation: all 8, so the paper's links are stable.
3. **Landing page**: bring the concept at `site/landing/` into the repo, published at the Pages root with the
   viewer at `/app/`; four live embeds (dACC layers, PENK Visium vs HD, BLA UMAPs, habenula tracks) opened at
   saved URL states, "open full screen" links, provenance line per example. Needs the user's three decisions
   (viewer path, four examples, domain).
4. **Docs pass**: getting-started proves the object-first path (`init object.rds` → edit → `build` → `serve`);
   the gallery guide (`site.yaml`) with paper links and tags; a "Reproduce the examples" page pointing at the
   examples repo; `docs/reference/benchmarks.md` with the measured tables (see §3).
5. **One independent user** builds an app from their own object following only the docs; every stumble becomes a
   docs or CLI fix before the tag.
6. **Tag**: CHANGELOG 1.0.0, CITATION.cff version/date, `git tag v1.0.0`, approve the `pypi` environment in the
   release workflow, enable the GitHub–Zenodo integration first so the release mints the software DOI; add
   `.zenodo.json` (title, creators, license, keywords) so the record is right the first time.

## 2. The examples repository (`spatialscape-examples`)

Source: the cluster repo's `code/` (59 commits), which already has the right shape. Move, do not rewrite.

```
spatialscape-examples/
  README.md                 the table of datasets: modality, platform, cells, source, licence, Zenodo DOI, live app
  environment.yml | requirements.txt   pinned spatialscape==1.0.0 plus the readers' deps (anndata, pyarrow, zarr, tifffile)
  common/                   the shared readers (10x h5, Space Ranger spatial/, Xenium outs, Leiden) as they are
  <dataset>/
    README.md               source, licence, what the scripts do, cost (time, memory, disk), the live app link
    download.sh             raw data from the publisher, sizes and checksums (what 01_download.sh is now)
    fetch_processed.sh      the processed objects from Zenodo (new): the laptop path, skips prepare
    prepare.py              raw -> processed (what 02_prepare.py is now), absent where not needed
    dataset.yaml            unchanged; paths relative to the folder (processed/, raw/)
    slurm/                  the sbatch wrappers, optional
```

Changes while moving:

- **Paths**: every script resolves `ROOT` from its own location (they already do) and reads `raw/` and
  `processed/` beside the yaml instead of the cluster's `raw-data/` and `processed-data/`; one env var
  (`SPATIALSCAPE_EXAMPLES_DATA`) can point both elsewhere on a cluster. No JHPCE path anywhere.
- **Object-first example**: add `dlpfc-visium` from spatialLIBD's SpatialExperiment (12 sections, one `.rds`
  from ExperimentHub): a download line and a yaml written by `spatialscape init`; no prepare script. This is the
  first example in the README.
- **CosMx**: molecules mapping and image name under `defaults`; mask tracing through the package's
  `polygons.labels` where it fits, else keep the tracing but in `common/cosmx.py` with a docstring; the yaml to
  about 30 lines.
- **Allen atlas**: `tools/` subfolder for the memory check, the palette generator and the file manifests; the
  README says this one is cluster-scale and not on Zenodo (raw data are Allen's S3, free to fetch).
- **Spatial ATAC + RNA**: the per-section micron rule and the quarter turn are already in the yaml.
- **Each README** says whether a prepare step exists and why (the four 10x ones only reshape vendor files).
- **A `make`-style top level**: `./run <dataset> fetch|download|prepare|build|serve` is tempting; do not add it.
  Three commands per README is the interface: fetch (or download + prepare), `spatialscape build`,
  `spatialscape serve`.
- CI on the repo: a workflow that builds the two smallest datasets from Zenodo on every push (cytassist,
  xenium), so the scripts never rot against a new spatialscape release.

## 3. Zenodo

- **One record** (the user's decision, 2026-11-09): a snapshot of the examples repository (the GitHub–Zenodo
  integration archives the tagged release) together with the processed objects that are small enough to ship, so
  one DOI gives the code and the inputs. Contents: per dataset a `<dataset>-processed.tar` holding exactly what
  `prepare.py` writes (h5ad, boundaries parquet, composites) plus its `dataset.yaml`; a `MANIFEST.sha256`; the
  top-level README. Everything but the Allen atlas fits: 11 GB against Zenodo's 50 GB record limit (atera 4.2,
  merscope 3.0, cosmx 2.9, the four small ones under 1 GB together). Images and transcripts stay with the publisher
  (10x, Vizgen, NanoString buckets) and `download.sh` fetches those; the yaml works with or without them (images
  and molecules are optional parts of a sample).
- **Too large to deposit** (the Allen atlas, 215 GB processed, raw on Allen's S3; any future one past the record
  limit): the folder carries the download and prepare scripts with their costs in the README, so the objects are
  rebuilt rather than fetched. `fetch_processed.sh` says so and exits for those datasets.
- **Not deposited**: the LIBD datasets, which follow their papers' data releases.
- **Licences**: carry each source's terms into the record (10x CC BY 4.0, Allen CC BY-NC 4.0, Vizgen and
  NanoString public-data terms, GEO public domain); the scripts MIT.
- Deposit is the user's action (their Zenodo account). I prepare each record's folder, metadata JSON and
  checksums; the user uploads and publishes; `fetch_processed.sh` then gets the record id.
- The software release DOI comes from the GitHub integration (§1.6), distinct from the data records.

## 4. Benchmarks for the paper

The protocol is written (`design/benchmarks.md`); fidelity is done. Run the remaining two tables once, on named
machines, and commit the raw logs under `benchmarks/results/`:

- **Build**: wall time, peak RSS, bundle size for synthetic, amygdala, atera (cluster job), abc-atlas (the logs
  exist), habenula; laptop rows for the small public examples.
- **Viewer**: cold load, gene switch, pan frame times, points drawn at three zooms, on the M-series laptop in
  Chrome and Safari, with atera as the transcript row and abc-atlas as the matrix row; the Playwright timing hooks
  exist (`window.__sscape.timings`).

## 5. Manuscript

- **Form**: an application note (Bioinformatics) or a Brief Communication (Nature Methods); bioRxiv first.
- **Claims and their evidence**: static hosting with one range request per gene (architecture + build table);
  faithful to the data (fidelity table); every modality in one viewer (the examples table: Visium, Visium HD,
  Xenium, Atera, MERSCOPE, CosMx, spatial ATAC + RNA, snRNA-seq, multiome tracks); reproducible (the examples
  repo + Zenodo); the LIBD amygdala atlas as the driving case.
- **Figures**: 1 architecture + format; 2 the amygdala app (grid, pinned PENK Visium vs HD, UMAPs, region test);
  3 modality gallery, one panel per public example (PNG export at saved URL states); 4 benchmarks.
- **Authorship, data statements, code availability**: GitHub + Zenodo DOIs + live gallery URL.

## Order and rough timing

| Week | Work | Gate |
|---|---|---|
| 1 (to 16 Nov) | redeploy live site; landing page; scaffold `spatialscape-examples` from `code/`, generalise paths, CosMx cleanup, dlpfc example | all 9 examples build from the new repo on the cluster |
| 2 | the Zenodo record's tarballs, checksums and metadata (user uploads); `fetch_processed.sh`; examples CI; build and viewer benchmark runs | a laptop rebuilds xenium and cytassist from Zenodo alone |
| 3 | docs pass; independent user walkthrough; fixes | the user's walkthrough needs no help |
| 4 | tag v1.0.0, PyPI, software DOI; benchmarks page; preprint draft with figures from the live apps | preprint on bioRxiv |

## Decisions needed from the user

1. Examples repo owner and name (`MicTott/spatialscape-examples` or under `LieberInstitute`).
2. Public gallery: all 8 public apps on S3 (recommended) or the 6 small ones.
3. The landing page's three decisions (viewer at `/app/`, which four embeds, domain).
4. Which LIBD datasets appear in the paper and whether their objects can be released with it.
5. Target journal.

## Verification

- Examples repo: a fresh clone on the laptop, `fetch_processed.sh` + `spatialscape build` + `validate` for
  every Zenodo-backed dataset; on the cluster, `download.sh` + `prepare.py` + build for one dataset end to end
  (xenium) to prove the raw path still works; the CI workflow green.
- Fidelity script against two rebuilt public apps (xenium-mouse-brain, merscope) from the processed objects.
- Live site: every showcase URL opens and matches its PNG; the landing embeds load from CloudFront.
- Release: `pip install spatialscape==1.0.0` in a clean venv runs `examples/scripts/walkthrough_from_spe.sh`;
  Zenodo DOI badge resolves.
