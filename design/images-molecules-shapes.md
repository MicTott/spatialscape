# Full-resolution images, molecules and cell shapes

Status: plan, nothing built. Written 2026-10-22 from a ten-agent design pass: three research reports
(Xenium formats and sizes, browser limits, fit with this codebase), one design per area, an adversarial
review of each design's memory, compute, format and UX claims, and a completeness critic across all three.
All three designs came back "feasible with changes"; this plan adopts the reviewers' changes.

The request: higher-resolution images including multicolour fluorescence, individual Xenium transcripts,
segmentation outlines, and comparing segmentations, "somewhat similar to Xenium Explorer". Is it feasible or
too memory and compute heavy, and what optimisations make it work?

## Short answer

Feasible on the lab's laptops (16-32 GB Apple Silicon, Chrome and Safari), as long as the browser only ever
touches what is on screen. Today's code breaks that rule in two places, and both have to be fixed before any
new feature is safe to add:

| Today | Cost | After |
|---|---|---|
| Cell outlines: one whole-sample PathLayer once zoomed in | 6.4-6.7 M vertices per Xenium section, about 29 ms per frame on an M1 Max and about 100-120 ms on a base M1; 87 MB CPU plus 87 MB GPU per section | spatial tiles: at most about 6.6k cells and 0.3-0.65 MB per view, about 6-9 MB GPU |
| Images: Viv defaults (float32 textures at coarse levels, cache of 5x the visible tiles, every channel fetched even when hidden) | 400-700 MB GPU per pane with 4 channels; about 3.1 GB for 3 panes x 6 channels, enough to get a Safari tab killed | about 44 MB GPU per pane with 4 channels |

With screen-bounded tiles, every feature is cheap per view. All of it switched on in three panes comes to
roughly 1 GB of CPU memory and 0.3 GB of GPU memory per tab (estimate), inside a 2-4 GB tab budget.

| Per view, at the zoom where it appears | Molecules | Cell shapes | Images (4 channels) |
|---|---|---|---|
| Network to fill a 1440 x 900 pane | about 0.4 MB (amygdala, readable density) up to 6.5 MB (Prime 5K, at the cap) | 0.3-0.65 MB per segmentation | 0.5-1.8 MB |
| GPU memory | about 1 MB, at most 16 MB at the 2 M cap | 6-9 MB per segmentation | at most 44 MB |
| Frame time, M1 Max | 3-5 ms for 1-2.5 M molecules | well under 5 ms | unchanged |

The real constraints are on the build side, not in the browser:

- Xenium morphology images are JPEG 2000 OME-TIFF. They need the optional `imagecodecs` package to read,
  and the build has to stream them tile by tile, because today's code would need 16-46 GB of RAM per section.
- Disk: about 10-13 GB of source morphology per amygdala section, against about 12 GB free on this machine.
- The amygdala raw outputs (transcripts.parquet, morphology_focus, nucleus boundaries) are on JHPCE, not here.
- Safari decode speed and base-M1 GPU throughput are still extrapolated; week 0 measures them.

## What breaks today (verified in the code)

- `images.py` reads a whole pyramid level into numpy, then copies it for crop and flip. `mask_to_points` runs a
  float64 distance transform at full resolution: about 44 GB for one Xenium section.
- `write_ome_zarr` keeps every pyramid level in memory and always writes unsharded Zarr v2, whatever the
  dataset's `sharded` setting. A full-resolution section is 25-29k chunk files per channel.
- Default contrast windows are the full dtype range, so 16-bit DAPI renders nearly black.
- `imageLayers.ts` selects every channel; Viv fetches a tile for every selected channel even when hidden, and
  throws above 10 channels (Viv 0.23's `MAX_CHANNELS` is 10, not 6).
- There is no per-channel control: one "show images" box and one opacity slider.
- One fingerprint per sample: changing an image's colour would re-run a multi-GB conversion.
- A live hazard: `discover.auto_images` already adds any `morphology_focus*.ome.tif` next to a Xenium sample,
  and `max_size` defaults to none, so `init` or `show()` on an XOA outs folder reads level 0 whole (about
  6.5 GB for the public Prime mouse brain, about 11 GB per channel for an amygdala section), or fails on JPEG
  2000 without `imagecodecs`. It also misses the XOA 2+ `morphology_focus/` folder layout. This needs a small
  fix first, independent of this plan.

## Facts the plan rests on

From 10x documentation, public datasets read with range requests, and local measurement:

| Fact | Value |
|---|---|
| Transcripts per mm², 300-500 gene panels | 0.42-0.66 M decoded (brain preview); amygdala Q20 cell-assigned 16-47 M per section |
| Transcripts per mm², Prime 5K | 1.7-5.6 M typical, up to about 11 M; 148-189 M per public slide |
| transcripts.parquet | 12-16 B per row (zstd, xyz on a 1/64 µm grid since XOA 3.0, sorted by gene) |
| Xenium Explorer's transcript format | 250 µm level-0 tiles, sorted by gene, about 13.8 B per transcript, pyramid about 2.1x level 0 |
| Same tiles re-encoded compactly (measured) | 3.1-3.7 B per transcript with QV, about 3.2 without |
| Morphology images | uint16 BigTIFF OME-TIFF, 1024² tiles, lossy JPEG 2000, 0.2125 µm/px, 4 channels in XOA 2+ (DAPI, boundary, interior RNA, interior protein) |
| Amygdala section extents at 0.2125 µm/px | 4.9-5.7 Gpx per channel (about 54k x 91-105k px) |
| Cell boundaries | 25 vertices per ring including the closing one, on the 0.2125 µm pixel grid; amygdala 198-288k cells per section |
| Polygons as stored today | 23-26 MB per Xenium section raw; lossless int8 deltas plus zstd would be about 10 MB |
| Browser JPEG 2000 decoding | none: geotiff.js has no J2K decoder, so Xenium TIFFs cannot be served to Viv directly |
| deck.gl points, M1 Max | 5 M points at 60 fps; spatially ordered points draw 3-5x faster than random order |
| Safari kill thresholds (WebKit trunk) | active tab above 7 GB plus 1 GB per tab on 16 GB machines; inactive above 3 GB plus 1 GB per tab |

## The design in one rule

**Nothing is loaded for a whole section once you zoom in.** Below the zoom where cells are 6 px across, the
viewer keeps drawing what it draws today: cell dots, coloured by the cell-level expression already in the
bundle, which is the right overview of the molecules. Above it, three tiled layers take over, each fetching
only the tiles in view: cell shapes, molecules and full-resolution image tiles. No pyramid of molecules or
simplified shapes is needed, because the dots are the pyramid.

## Shared foundation (build once, first)

Each design invented its own frame, tiler, cache and hover path; the reviewers and the critic found the same
problems three times. These pieces are built once and used by all three features.

1. **Sections: one frame per tissue section.** `manifest.sections[] = {id, rawAffine, origin, assets}`.
   `rawAffine` maps raw instrument µm to section µm and is the only transform; the amygdala Br9192 and Br9206
   transposes move here from `polygons.affine`, which stays as an alias. The origin is fixed from the primary
   cells' raw bounding box minus a margin, so adding a segmentation or transcripts never moves it (and never
   breaks saved URLs). Samples reference a section plus a placement shift applied in the layer's model matrix.
   Section assets live under `sections/<id>/{images,transcripts,shapes}/`, outside the sample folder that
   `build_sample` deletes on every rebuild.
2. **Per-asset fingerprints and one disk preflight.** Expression, obs, each image, transcripts and each
   segmentation get their own `build.json`. A colour, name or window change never re-converts an image; adding
   a segmentation never rebuilds expression. Before writing anything, the build sums every asset's projected
   output and temp space and refuses if it would leave less than 2 GB free.
3. **One frame-check module that fails the build.** Polygon centroid versus cell position (exists), nearest
   cell for each molecule at `max(10 µm, 2 x radius)`, share of assigned molecules inside their own polygon,
   DAPI density versus cell density for images, and "the chosen frame is at least 5x better than the
   transposed or flipped alternative". A wrong transpose otherwise misplaces everything silently.
4. **One tile container for ragged per-tile data**, used by molecules and shapes: an index of (bytes, count)
   per tile, compressed, plus a file of one-shot zstd frames in row-major order, with planar byte streams
   inside each frame. Range hosts get one file; hosts without Range (GitHub Pages) get one file per tile. One
   writer, one validator, one worker reader that coalesces runs of uncached visible tiles into ranges of at
   most 1 MB and can abort per run.
5. **One pane-aware tile manager in the viewer.** It maps each pane's visible rectangle through the inverse
   placement matrix to section tiles, sums the index counts across every sample in the pane before fetching,
   and asks one tab-wide budget allocator (in `lod.ts`) whether to draw. Molecules and shapes are thin layers
   on top of it. Viv keeps its own tile layer for images, with its cache size set by the same allocator.
6. **One request scheduler and memory budget.** Priority: gene fetches, then shape and molecule tiles, then
   image tiles; in-flight dedupe; aborts by request id (Comlink cannot pass an AbortSignal); a cap on
   concurrent image requests on HTTP/1.1 hosts. One budget over all byte-LRUs, tighter on Safari. The local
   `serve` moves to HTTP/1.1 keep-alive.
7. **One hover dispatcher**, in this priority: a molecule within 4 px, then the cell polygon under the cursor,
   then the nearest cell dot, with "inside a <B> cell" appended when an overlay is on.
8. **One colour module**, factored out of the point layer's shader, so shapes and molecules follow the gene,
   annotation, blend, filter and hidden categories exactly like dots. One load-state signal that PNG export,
   tests and the status line all wait on.
9. **A Xenium outs reader.** One discover step that reads `experiment.xenium` (pixel size), finds images in
   either morphology layout, takes cell and nucleus boundaries as segmentation sets, and lists transcripts
   commented out with a disk estimate. A second Xenium Ranger outs folder of the same run becomes another
   segmentation of the same section. Without it, every section needs about 15 lines of yaml.

## Feature 1: cell shapes (the most visible win, and a prerequisite for molecules)

**Format.** Per segmentation, tiles of 1024 µm (512 or 256 where tissue is dense, so a tile holds 1-2k cells)
in the shared container. A ring belongs to the tile holding its centroid; readers widen the tile by the
largest centroid-to-vertex distance. Each ring is stored losslessly on its own pixel grid (0.2125 µm for
Xenium, detected at build): the first vertex as int16 from the tile origin, the rest as int8 consecutive
deltas, without the duplicated closing vertex. Measured: about 35 B per cell, about 10 MB per 288k-cell
segmentation, against 23-26 MB raw today. Polygons for cells removed by QC are dropped and counted. This
replaces `polygons.i16` outright; old bundles rebuild in about 7 s per section.

**Viewer.** Shapes appear at today's gate (a cell at least 6 px across) when the tiles in view hold at most
40,000 cells for that segmentation; otherwise the dots stay and the status line says "zoom in for cell shapes".
A 1440 x 900 pane at the gate shows at most about 6.6k amygdala cells. Shapes replace the dots they stand for,
in the same colours. Filled shapes need worker-side triangulation (deck's earcut, passed in so the main thread
never tessellates). Positions upload as float32 rather than deck's default float64 for this coordinate system.

**UI.** The "cell boundaries when zoomed in" checkbox becomes one control: *Cell shapes: dots | filled | edges*.
Filled is the default only when no image is shown, so fills never hide the morphology. The word "outlines"
stays reserved for the existing annotation-boundary panel.

## Feature 2: molecules

**Format.** Per section, stored once in the raw section frame and shared by every segmentation of that
section. Tiles of 64-512 µm, the largest power of two that keeps a tile under about 50k molecules (256 µm for
the amygdala, 64 µm for a dense Prime 5K mouse brain). Inside a tile, molecules are sorted by gene, then by
a Morton code of their position on the instrument's 1/64 µm grid; gene ids are implicit in the runs, positions
are delta-coded and split into byte planes before zstd. One flags byte per molecule keeps "assigned to a cell"
and "overlaps the nucleus". Rows below QV 20 are dropped at build, as 10x's own matrices do; there is no QV
plane. About 3.2 B per molecule: 0.48-0.64 GB for the four amygdala sections, about 0.5 GB for a Prime 5K
slide. The feature table is per section (the panel order), and molecule genes map to expression genes by name.

**Viewer.** The worker decodes 50-58 M molecules per second (V8, measured) into 8-byte vertices; a custom
point layer draws each tile with one call and drops unselected genes in the vertex shader, so changing genes
or colours never refetches. The gate is screen density, not zoom: molecules draw when the enabled molecules in
view come to at most about 0.1 per screen pixel, with a hard cap of 2 M fetched. That keeps the view readable:
for the amygdala, all molecules in grey appear at about 2.5 px/µm (about 0.11 M molecules, 0.4 MB); a single
coloured gene appears much earlier. When molecules are drawn, cell dots under them fade. Hover is a linear scan
of the 1-4 tiles under the cursor (0.1-0.4 ms each, measured); no spatial index is built.

**UI.** One checkbox, *Molecules (when zoomed in)*. Molecules follow the current colour: the gene on screen, or
a blend's two gene sets in the legend's colours; with an annotation colour on, all molecules show in grey,
which is the view for judging a segmentation. There is no second gene picker, no QV slider and no unassigned
toggle in v1 (unassigned molecules draw dimmer). The legend gains a molecule row, and PNG export waits for
molecule tiles and draws that row.

**Not doing.** Overview levels or density maps (the cell expression is the overview); 3D z; per-molecule ids,
FOV or codeword columns; serving 10x's `transcripts.zarr.zip` or the parquet directly (13.8 B and 12-16 B per
molecule, no JavaScript reader); a gene-major second copy (only useful to see one sparse gene's molecules across
a whole section, which the cell colouring already shows); KDBush or GPU picking for molecules.

## Feature 3: comparing segmentations

Xenium Explorer shows one cell and one nucleus polygon set per bundle and has no in-app comparison; comparing
means opening two bundles. Two comparison modes, built in order of value:

1. **Overlay (v1).** *Compare with: <segmentation>* draws one other segmentation of the same section as edges
   in a fixed accent colour, dashed so it does not rely on colour alone, over the current shapes, image and
   molecules. Xenium nucleus boundaries and any Xenium Ranger re-segmentation outs become segmentations of the
   section automatically. A static table lists, per segmentation, cells, median area, molecules per cell and %
   molecules assigned, all computed at build time from each segmentation's own files. Polygons only: about 10 MB
   per extra segmentation per section.
2. **Side by side (later, when a real alternative segmentation with its own expression exists).** A
   segmentation that brings its own cell table becomes a derived sample tagged `meta.segmentation`, and the
   existing *split by* panes show it next to the primary, with the image and molecules stored once and the
   cameras linked fully (pan as well as zoom) when the panes show the same section. Derived samples live in
   their own manifest list, not in `samples`, so counts, the sample strip and the comparisons feature's
   replicate linking never see a section twice.

**Later still, only if asked for after seeing the overlay:** colouring molecules by which segmentation claims
them (both, only A, only B, neither). It needs one bit per molecule per segmentation (0.1-0.25 B per molecule)
and a build-time join on transcript id, which at Prime scale (up to 2.6 B rows) needs a partitioned join.

## Feature 4: full-resolution and multichannel images

**Build.** A streaming converter replaces `images.py`'s whole-image path. It reads only the source tiles inside
the crop, snapped to the source tile grid so no tile is decoded twice, from pyramidal OME-TIFF (including both
Xenium morphology layouts and the JPEG 2000 they use, through the optional `imagecodecs`), OME-Zarr and plain
PNG/JPEG. It masks on an 8 µm grid with a feathered edge instead of a full-resolution distance transform, takes
flips, rotations and registration as part of the section's affine instead of moving pixels, and writes each
pyramid level shard by shard from 4096 px blocks in a thread pool. Peak RAM stays under about 2 GB whatever the
image size. Measured rate: about 51 Mpx/s on 8 threads, so about 2 minutes per channel per amygdala section at
full resolution.

**Encoding.** One display encoding: 8-bit tiles, windowed per channel, compressed as WebP (or JPEG, decided by
the week-0 Safari test), in Zarr v3 with NGFF 0.5 metadata, sharded in 4096 px blocks on Range hosts. RGB images
store all three planes in one chunk, one request and one texture per tile instead of three. The stored window
is wide (0.1 to 99.99th percentile of tissue pixels) so the viewer's contrast slider has room; the default
display window is narrower. `lossless: true` keeps the source uint16 with zstd for anyone reading intensities.
Measured on real Xenium morphology: 13 KB per 512² tile as WebP against 211 KB as today's lossless uint16, and
WebP is about half of JPEG at equal quality. The source JPEG 2000 is already lossy, so this is a second
generation of loss, visually negligible at quality 90; the docs will say so.

**Viewer.** A pixel source that decodes tiles in two workers with a small compressed-byte cache, so channel
toggles and panning back cost no network; nearest-neighbour textures at every pyramid level (1 byte per pixel
instead of Viv's float32 cast at coarse levels); a tile cache of about 1.25x the visible tiles; and only the
active channels fetched, at most 6 at once. Together these take a 4-channel pane from 400-700 MB of GPU memory
to at most about 44 MB.

**UI.** All in the existing Display panel. With a single RGB image per sample, today's two controls stay as
they are. With fluorescence, one row per channel name across the dataset: a checkbox (on means fetched and
drawn), a colour dot and the name; clicking the name opens one two-handle contrast slider in source units with
a reset. At most 6 boxes can be checked; the rest are disabled with a hint, nothing unchecks itself. Channel
state is shared by name across samples, like annotation fields. Not in v1: histograms behind the slider,
presets, a filter box for 60-channel panels, SVS/NDPI/QPTIFF and SpatialData readers.

**Resolution default.** Every 2x coarser cap is 4x smaller. For the amygdala, 0.425 µm/px (nuclei still 12-24 px
across) until full resolution is needed:

| Amygdala, 4 sections x 4 channels | Disk | Build (8 threads) |
|---|---|---|
| 0.425 µm/px, WebP | 0.9-1.4 GB | about 10 min |
| Full 0.2125 µm/px, WebP | 2.8-4.2 GB | about 35 min |
| Full, DAPI only, WebP | 0.7-1.05 GB | about 9 min |
| Full, lossless uint16 | about 94 GB | not practical here |
| GitHub Pages cap, 1 µm/px | 0.2-0.4 GB | minutes |

## Combined budget

The case that matters is everything on at once: a Xenium section at the gate with an image, shapes, molecules,
dots and the gene cache, in one and in three panes, on a base M1 in Safari. Estimated, to be measured in week 0
and again before release:

| | CPU memory | GPU memory | Frame time |
|---|---|---|---|
| Gene cache (exists) | 192 MB | - | - |
| Images, 3 panes x 6 channels | about 0.48 GB | about 0.21 GB | - |
| Molecules | about 0.1 GB | up to 3 x 16 MB | 3-5 ms (M1 Max) |
| Shapes, own plus overlay | about 0.15 GB | about 55 MB | under 5 ms |
| Total | about 1.0 GB | about 0.3 GB | 10-20 ms (estimate, base M1) |

It fits only once the image cache and texture changes ship: Viv's defaults alone would hold about 3.1 GB.

Disk per amygdala bundle: images 0.9-1.4 GB at 0.425 µm/px (2.8-4.2 GB at full resolution), molecules
0.48-0.64 GB, shapes about 0.1 GB for three segmentations per section, on top of today's 1.9 GB. This, and
hundreds of thousands of files unsharded, puts such bundles on a Range-capable host (S3/CloudFront, R2, a lab
server); GitHub Pages stays for demos and coarse images.

## Optimisations, in one place

| Optimisation | Effect |
|---|---|
| Spatial tiles plus the existing 6 px gate | work bounded by the screen, not the section: about 6.6k of 288k cells, 0.11 M molecules |
| Cell dots as the overview | no molecule or shape pyramids (Xenium Explorer spends about 1.1x level 0 on them) |
| Gene, then Morton order inside molecule tiles | 3.2-3.7 B per molecule (13.8 in Explorer's format); 3-5x faster to draw than random order |
| Byte-plane split before zstd | positions 4 B raw to 2.7 B |
| Fetch all genes per tile, cull in the shader | gene and colour changes need no network or upload |
| Screen-density gate for molecules | readable views, and a 2 M cap that holds on any panel size |
| Lossless int8 ring deltas on the pixel grid | about 35 B per cell, 2.5x smaller than today's raw polygons |
| Float32 positions and worker triangulation for shapes | half the GPU bytes; no main-thread tessellation |
| Streaming, tile-snapped image conversion | build RAM from 16-46 GB per section to under 2 GB; each source tile read once |
| 8-bit windowed WebP image tiles | full-resolution amygdala images 2.8-4.2 GB instead of 94 GB |
| Nearest textures, 1.25x tile cache, active channels only | image GPU from 400-700 MB to about 44 MB per pane |
| Zarr v3 sharding for images | 58x fewer files per channel per section |
| Coalesced range requests for molecule and shape tiles | 7-9 requests to fill a pane instead of 70-110 |
| Per-asset fingerprints | cosmetic edits never re-convert images; adding a segmentation never rebuilds expression |
| Build-time stats, windows and checks | the browser computes nothing statistical |

## Order of work

Each step is shippable and useful on its own.

| # | Step | What it delivers |
|---|---|---|
| 0 | Measure and de-risk (a few days) | fix the auto-image hazard; check `imagecodecs` installs on Python 3.14; Safari and Chrome byte-exact WebP/JPEG decode test; base-M1 Safari benchmark of points and paths; measure the real row counts on a real transcripts.parquet |
| 1 | Shared foundation | sections and frames, per-asset fingerprints, disk preflight, frame checks, the tile container and its validator |
| 2 | Tiled cell shapes | dots, filled or edges at full speed on every Xenium section, today's 100 ms frames gone |
| 3 | Molecules v1 | the Xenium-Explorer view of molecules, following the current gene colour |
| 4 | Compare with a segmentation | nucleus and re-segmentation edges overlaid, Xenium outs auto-discovered, a build-time QC table |
| 5 | Image viewer fixes | worker decoding, nearest textures, capped caches, active channels only: also makes today's H&E lighter |
| 6 | Streaming image converter and channel rows | full-resolution H&E and multichannel morphology |
| 7 | Verification and docs | the combined all-on benchmark in Safari on a 16 GB laptop as a release gate; format, url and yaml references; `show()` defaults (1 µm/px images, molecules off) |
| later | on demand | side-by-side segmentations, molecule assignment colouring, SpatialData, Visium HD Space Ranger 4 cell segmentations, MERSCOPE and CosMx readers, 2x PNG export, histograms and presets, SVS/NDPI |

Planning size: about ten developer-weeks for steps 0-7, with shapes and molecules visible on real Xenium data
about halfway through. Building the three designs separately, as first written, came to 50-60 days, because the
tiler, frame, caches and hover would have been duplicated.

## URL keys

New keys, none colliding with existing ones: `cs` (cell shapes: dots, filled, edges; `poly=0` maps to dots),
`mol=1` (molecules on), `ov` (segmentation overlaid), `ch` (active channels by index in the manifest's channel
list, with colour and window). `imgs` extends to carry an image id when a sample has more than one image. With
linked cameras, `pv` holds a single entry.

## Testing

Each step's definition of done: format, url and yaml references updated; a vitest decoder test against a
Python-written fixture; a Playwright test that zooms past each gate and checks what is drawn; validate checks
that do not need `imagecodecs`. One shared real fixture for all three features: the public Xenium Prime mouse
brain outs already in `~/Downloads` (morphology_focus with 4 channels, cell and nucleus polygon sets, the 5K
matrix; 2.0 GB), plus its transcripts.parquet once fetched.

## Decisions needed

1. **Data access.** The amygdala raw outputs are on JHPCE. Can you copy one section's outs folder here
   (transcripts.parquet plus morphology_focus, about 10-15 GB, against about 12 GB free), or should step 0 use
   the public Prime mouse brain fixture and you download its transcripts.parquet from 10x (about 2.3 GB)?
2. **Which morphology the amygdala runs have.** Four-channel morphology_focus or DAPI only, and which XOA
   version (the runs date from April 2024, before XOA 3.0)? This changes image disk by 4x.
3. **Lossy display by default.** 8-bit windowed WebP for viewing, with `lossless: true` only where someone reads
   intensities off the images: acceptable?
4. **Resolution default.** 0.425 µm/px for the amygdala until full resolution is needed, or full resolution?
5. **Hosting.** These bundles need a Range-capable host; is S3/CloudFront (or R2) the plan, with GitHub Pages for
   demos only?
6. **Which segmentations exist.** Original XOA cells versus the 5 µm re-segmentation now in the bundle, nucleus
   boundaries, any Baysor or Proseg runs? Side by side waits for one with its own expression matrix.

## Evidence

The research reports, the three designs, their reviews and the critic are in the session's workflow journal.
Key sources: 10x Xenium output, archive-size and Zarr format documentation; public Xenium datasets (breast
Rep1, Prime ovarian cancer, Prime mouse brain, Prime lymph node, XOA 4.0 tiny ovary); installed sources of
deck.gl 9.4, Viv 0.23, zarrita 0.7.5 and geotiff 2.1.3; WebKit's memory-pressure thresholds; Celldega,
TissUUmaps, Vitessce, napari-spatialdata and the Allen ABC atlas for prior art. Local measurements: compression
and decode on the Prime mouse brain morphology, GPU frame times for points and paths in headless Chromium on an
M1 Max, polygon sizes and decode on the four amygdala boundary files, and compact molecule encoding on synthetic
molecules built from the real Br9192 cells and on the XOA 4.0 subset.
