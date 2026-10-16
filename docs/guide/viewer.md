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
| Cluster names on the embedding | Display → label clusters in the embedding |

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

## Gene color scale

Gene colors share one scale across all samples on screen, so the same color means the same log-normalized value in every section; the legend shows the numeric range. Tick *scale each sample to its own max* to stretch every section to its own maximum instead, which brings out structure in low-count platforms at the cost of comparability. The two gene sets of the **Blend** mode are scored as the mean log-normalized expression of their genes, on the same shared scale.

## Sharing and export

*copy link* in the panel header copies a URL that reproduces the whole view: dataset, coloring, filters, hidden categories, camera, split and point sizes. *PNG* downloads the current frame at screen resolution (2× on high-density displays) with the legend and scale bar drawn in. Press `?` for the list of keyboard and mouse shortcuts.

## Point size

## Regions: your own annotation

The Regions panel turns the lasso into an annotation tool. Add a group, then lasso as many areas as you like, in
any section or in the embedding; each lasso becomes a translucent polygon in the group's colour, labelled, and
stays attached to its section through layout changes. Add the next group and keep going; click a group (or press
`1`–`9`) to draw into it, Backspace removes the last area, Esc stops drawing. Where lassos overlap, the last one
drawn wins. Double-click a name to rename it; the swatch changes the colour.

The groups are a live annotation called *Regions*: colour the cells by it, and the legend shows the counts per
region (plus "unassigned", which you can hide), hover rows name the region, the dot plot can be grouped by it and
filters can use it. *export CSV* writes `sample, cell_id, region` for every cell inside a region; *save* writes
the drawing itself (groups and polygons) as JSON and *load* brings it back, including onto a rebuilt bundle, since
polygons are stored in each section's own coordinates. In a notebook, `s.regions()` returns the same table as a
pandas Series aligned with your object ([In a notebook](./notebooks)).

## Genome panel

An ATAC sample built with `tracks:` ([dataset.yaml](./dataset-yaml#genome-tracks-for-atac-samples)) adds a genome
panel under the maps, drawn by the same renderer as the maps: scroll to zoom around the cursor, drag to pan,
double-click to zoom in, and drag the panel's top edge to resize it. From top to bottom it shows the coordinate
axis, one accessibility track per visible category of the annotation you last colored by (in the vocabulary's
colors, on one shared scale printed in the header, so hiding a category in the legend removes its track), the
sample's peaks, and gene models with exons and strand arrows. Coloring by a gene keeps the per-category tracks,
so a locus reads per cell type.

![The genome panel: six cell-type accessibility tracks over the peaks and gene models of chr1:1.0-1.2 Mb](/screenshots/genome-panel.png)

The locus follows what you color by: a gene (with room around it), a gene's activity score, or a peak (plus or
minus 10 kb), and a band marks it. The search box takes a gene name, completed from the genome's gene models, or
a locus such as `chr11:60,405,808-60,512,181`; the chromosome menu shows a whole chromosome. Hovering shows the
position and the value of the track under the cursor; clicking a gene colors the maps by its expression (or its
activity score when the sample has no RNA), clicking a peak colors them by that peak's accessibility. The locus
travels in the URL as `gl`; the `genome` switch in the top bar hides the panel (`gb=0`).

Features that take negative values (module scores, motif deviations) are stored symmetrically around zero and drawn with a diverging colormap centred on zero, whatever the colormap setting; the legend shows the real minimum and maximum.

When an embedding is colored by an annotation, each category's name floats at the centre of its cells, largest clusters first and never overlapping; hidden categories lose their label. Turn it off under Display (`cl=0` in the URL).

Each view has its own point-size slider at its bottom-left corner: one for the tissue sections, one for the embedding, so dense UMAPs and sparse Visium spots can be tuned independently. Double-click a slider to reset it. The values travel in the URL as `ps` (spatial) and `pse` (embedding).

## Images and polygons

H&E or fluorescence pyramids render under the points with an opacity slider. Cell boundary polygons, when the bundle has them, appear once you zoom in far enough that a cell spans several pixels.

## Sharing a view

Copy the URL. It encodes the dataset, the focused sample, color and filter settings, hidden categories, outlines, split layout and camera. See [URL parameters](../reference/url) for the keys.
