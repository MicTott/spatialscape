# Supported platforms and layers

Use `init`, `build` and `serve` for each platform. The input files, coordinate settings and available layers
differ by platform; the guides below describe those requirements.

- [Sequencing-based spatial](./sequencing) — Visium, Visium HD, Slide-seq, Stereo-seq: spots or bins on an H&E image.
- [Imaging-based spatial](./imaging) — Xenium, MERSCOPE (MERFISH), CosMx: segmented cells with boundaries, a fluorescence image and the individual transcripts.
- [Single-cell and multiome](./single-cell) — snRNA-seq, snATAC, 10x Multiome: an embedding beside the tissue, with shared cell type colours and genome tracks.

## The layers

| Layer | Sequencing-based | Imaging-based | Single-cell | From | Cost |
|---|---|---|---|---|---|
| Expression and annotations | always | always | always | the object's matrix and obs columns | 1 byte per cell per gene |
| Brightfield image (H&E) | usual | – | – | SpaceRanger `spatial/`, a PNG or TIFF, an OME-Zarr | 10–300 MB per section |
| Fluorescence image (DAPI, markers) | – | usual | – | the platform's morphology / mosaic image | about 200 MB per section at 0.85 µm/px |
| Cell or spot shapes | optional (HD bins, spots) | usual | – | a boundary table or an `obsm` array | about 44 B per cell |
| Molecules (transcripts) | – | optional | – | the platform's transcript table | 3.5 B per molecule; 170–400 MB per Xenium section |
| A second segmentation (nuclei) | – | optional | – | a second boundary table | like shapes |
| Embedding (UMAP) | – | – | always | an `obsm` key or a `reducedDim` | like a section |
| Genome tracks | – | – | optional (ATAC) | fragment files or bigWigs | 0.1–2 GB per dataset |

"Usual" identifies layers commonly available from that platform. `init` adds recognized files to the
configuration; other layers require explicit entries. Expression and coordinates are sufficient to draw
points. Add images, boundaries or transcripts later by editing the YAML and rebuilding the affected samples.
The sizes above are approximate and depend on the dataset and conversion settings.

## What the viewer does with them

Dots are what every sample starts as. Shapes replace the dots once a cell is about 6 px across; molecules draw once
a view holds about one per screen pixel; images sit under everything with an opacity slider and, for fluorescence,
a channel list. All of it is in [Using the viewer](../viewer).

## Platforms the CLI names

`platform:` on a sample is one of `visium`, `visium_hd`, `xenium`, `merfish`, `codex`, `snrnaseq` or `other`. It sets the
default point size (a 55 µm Visium spot, half the bin pitch for HD, 5 µm cells otherwise), the coordinate
assumption (pixels with SpaceRanger's scale factors for Visium and HD, microns for `xenium` and `merfish`; `codex`
and `other` need `microns:`) and the label in the viewer's platform bar. A platform the list does not name is `other` with `microns:` and `point_radius` set by hand;
the examples on the family pages show the values.
