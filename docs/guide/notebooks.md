# In a notebook or an R session: `show()`

`show()` opens an object in the viewer without a YAML configuration. Select cells or draw regions in the viewer, then retrieve them in Python or R.

```python
import spatialscape

s = spatialscape.show(adata, color="cell_type")   # the viewer opens under the cell
```

The first call builds the object the same way `build` would, straight from memory, into
`~/.cache/spatialscape/show/<hash>`, where the hash covers the data and the settings. Showing the same object
again reuses the cached build when its fingerprint matches. Changes detected by the fingerprint trigger a
new build; see the fingerprint limitations below. One server thread per Python process serves the objects
shown in that session, which are also listed in the viewer's gallery. Outside a notebook, `s.url` is the address and
`show(..., open_browser=True)` opens it. The server lives in your Python process: in an interactive session it
stays up between prompts, but a plain `python script.py` exits as soon as the script ends and takes the viewer
with it, so end such a script with something that waits (`input("press Enter to stop")`, or a loop that polls
`s.selection()`).

## What you can pass

| Argument | Meaning |
|---|---|
| `adata` | an AnnData: `obsm["spatial"]` makes a spatial sample, otherwise the UMAP-like `obsm` key is used (`coords="obsm/X_umap_atac"` to choose) |
| a path | an `.h5ad`, a Zarr or SpatialData store, an `.rds` / `.rda` SpatialExperiment or SingleCellExperiment, a dataset yaml, or a built bundle |
| `color` | an obs column or a gene to color by at first |
| `sample` | an obs column that splits the object into one panel per value (donors, sections) |
| `fields` | extra obs columns to expose, a `{field id: column}` map, or `"auto"` for every usable column; by default the same heuristics as `init` pick domains, cell types and QC |
| `meta` | sample metadata, `{key: obs column}` with one value per sample (`{"condition": "condition", "mouse": "mouse"}`): the viewer splits the canvas by these keys, and comparisons link their replicates through them |
| `comparisons` | results of tests you ran, each a dict with the arguments of `add_comparison()` below, added once the object is built |
| `layer`, `normalized`, `platform`, `name`, `height` | as in [dataset.yaml](./dataset-yaml) |

## Retrieve selected cells

Draw a lasso in the viewer (the `lasso` tool at the top left, or press `l`). Then:

```python
cells = s.selection()            # obs names inside the lasso, a pandas Index
sub = adata[cells]               # straight into scanpy, decoupler, a pseudobulk DE
mask = s.selection(as_mask=True) # or a boolean array over adata.obs
```

Every lasso replaces the previous one; `s.selection()` always returns the latest.

Drawn regions (the Regions panel: named groups of lassos across sections) come back the same way:

```python
adata.obs["region"] = s.regions()    # a Series aligned with adata.obs: the group name, or None
                                     # (for data shown from a path: the cells inside a region, indexed by (sample, cell id))
s.save_regions("regions.json")   # the drawing itself (the viewer's *save* button writes the same file)
```

The session keeps the drawing: reloading the viewer, or opening the same object again from the same kernel, brings the
polygons back. Across kernels, `spatialscape.show(adata, regions="regions.json")` (or
`s.load_regions(path)`) restores a saved drawing onto the same object, so you can annotate in several sittings,
switching between cell type maps and genes while you draw. For data shown from a path the
selection comes back as the cell ids. Under the hood the viewer posts the selection to the session's own server
(`/_api/selection`); a viewer served from anywhere else never makes that request.

## Add analysis results

Run the analysis in R or Python, then add the results and replicate-level values to the session:

```python
s = spatialscape.show(adata, sample="section", meta={"condition": "condition", "mouse": "mouse"})
cells = s.selection()                          # lasso a region, then pseudobulk and test it in scanpy, pyDESeq2, decoupler, ...
res, pb = my_test(adata[cells])                # a results table (one row per gene) and the per-mouse values it was fit on
s.add_comparison("Stress vs control, lassoed region", res, pb, groups=["control", "stress"], units="log2 CPM",
                 description="pyDESeq2 on per-mouse pseudobulk of the lassoed cells")
s                                              # re-display: the Compare section lists it
```

`add_comparison` takes data frames or paths and the same keys as a [`comparisons:` entry](./comparisons#comparisons-results-of-a-test-next-to-the-sections)
(`replicates`, `population`, `split`, `link`, `columns`, `kind`, `facet`). Marker genes have a shortcut:

```python
sc.tl.rank_genes_groups(adata, "cell_type", method="wilcoxon")
s.add_markers(adata)                           # reads uns["rank_genes_groups"]; the clusters link to the cell_type annotation
s.add_markers(find_all_markers_df, name="Seurat markers", field="cell_type")   # or any marker table as a data frame
```

Each cluster becomes a level of one *markers* comparison: pick a cluster, click a gene, see it on every section,
and *only &lt;cluster&gt;* keeps the cluster alone on the map. It writes the comparison into the session's bundle
and its manifest without rebuilding the expression or coordinate arrays. A comparison with the same name
replaces the previous one. Replicates are linked to sections through `meta` keys, such as a replicate ID
matching `meta.mouse`. The group labels determine the split key. Click a gene in the table to view its
replicate values alongside its expression in the sections.

Whether the object changed since the last `show()` is decided from a fingerprint: the names, the columns in use, the
coordinates, and the matrix through its index pointer and a sample of its values and column indices. An edit that
touches only values outside that sample is the one thing it cannot see; `show(adata, rebuild=True)` builds again
regardless.

## From R

Save the R object and call `show()` through reticulate:

```r
reticulate::py_require("spatialscape")
ss <- reticulate::import("spatialscape")
saveRDS(spe, f <- tempfile(fileext = ".rds"))
s <- ss$show(f, open_browser = TRUE)        # or rstudioapi::viewer(s$url)
cells <- s$selection()                       # colnames(spe) inside the lasso
spe[, cells]
s$add_comparison("Stress vs control", results_df, pseudobulk_df, groups = list("control", "stress"))   # data frames convert through reticulate
```

The first call reads and builds the object. Later calls reuse the cached build when the file and settings are unchanged.

## Housekeeping

`spatialscape.stop()` stops the server thread; the cache is plain folders, safe to delete:
`rm -rf ~/.cache/spatialscape/show`. A remote JupyterHub or Colab needs the kernel's localhost proxied to your
browser (jupyter-server-proxy); not covered yet.
