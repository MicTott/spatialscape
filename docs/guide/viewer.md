# Using the viewer

Open a bundle with `?d=<url>` or, when a registry is configured, `?d=<id>`. Everything you change ends up in the URL, so the address bar is always a shareable description of what you are looking at.

## Layout

The **spatial view** holds every section as a grid or a strip, at true physical scale, under one set of settings. If the dataset has embeddings (snRNA-seq UMAPs), they render in a second **embedding view** beside it; drag the divider to resize, use the swap button or the top bar to put it left or right, or turn it off.

| Action | How |
|---|---|
| Focus one sample | double-click it, or the ⤡ button in the sample list |
| Step through samples | `←` `→` (or `PageUp` `PageDown`) |
| Back to all samples | `Esc`, or "show all" |
| Fit to view | `f` |
| Hide a sample from the layout | its checkbox in the sample list |
| Show one platform | the top bar: All / Visium / Xenium …; shift-click toggles |
| Grid vs strip | Display → Grid / Strip |

## Color by

- **Gene**: type to search. Values are log-normalized expression; the range slider rescales the colormap, "hide zeros" removes non-expressing cells.
- **Feature groups**: non-gene features such as RCTD cell type weights appear under their own tab with a scrollable list.
- **Blend**: two gene sets, one gene or fifty each. Each set's score is the mean normalized expression of its genes; the two scores index a 2D color table. Schemes: yellow / blue → green, cyan / magenta → white, red / green → yellow. The legend becomes a color square.
- **Annotation**: any categorical or continuous field. Categorical legends show counts; click a category to hide it, double-click to solo it. Fields that only some samples carry are grouped separately in the menu.

Samples that don't carry the selected feature are drawn in grey ("not measured") rather than hidden.

## Filter by

Independent of coloring: keep cells whose gene expression or continuous value falls in a range (with a live histogram), or cells in chosen categories of an annotation. The map, counts and dot plot all respect it. The URL carries it as `fl=`.

## Expression by annotation

When coloring by a gene, this panel shows mean expression and percent expressing per category of any annotation across the visible samples, with a per-sample heatmap toggle. Clicking a row filters the map to that category; several rows combine.

## Hover

The tooltip lists the current gene's value, the filter gene's value if different, every categorical annotation of the cell with its swatch, and the cell id.

## Outlines

Display → Outlines draws the boundaries of any categorical annotation as light, dark or colored strokes over whatever you are coloring by. Outlines are traced at build time; see [Building](./building#what-happens-per-sample).

## Lasso

Press `L` or the ⌒ lasso button, drag around a region, release. Selected cells get a white ring and the Selection panel shows counts per sample, the composition of every annotation, and the current gene's mean and percent expressing in the selection versus the whole sample. "export CSV" downloads `sample,cell_id` rows. `Esc` clears.

## Images and polygons

H&E or fluorescence pyramids render under the points with an opacity slider. Cell boundary polygons, when the bundle has them, appear once you zoom in far enough that a cell spans several pixels.

## Sharing a view

Copy the URL. It encodes the dataset, the focused sample, color and filter settings, hidden categories, outlines, split layout and camera. See [URL parameters](../reference/url) for the keys.
