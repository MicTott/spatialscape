# In a notebook or an R session: `show()`

No yaml, no site. Look at the object you have in memory, and take what you lasso back out.

```python
import spatialscape

s = spatialscape.show(adata, color="cell_type")   # the viewer opens under the cell
```

The first call builds the object the same way `build` would, straight from memory, into
`~/.cache/spatialscape/show/<hash>`, where the hash covers the data and the settings. Showing the same object
again is instant, and an edited object is new data. One server thread per Python process serves everything shown
so far, so the viewer's gallery lists your earlier objects too. Outside a notebook, `s.url` is the address and
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
| `layer`, `normalized`, `platform`, `name`, `height` | as in [dataset.yaml](./dataset-yaml) |

## From a lasso to a variable

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
s.save_regions("amygdala-regions.json")   # the drawing itself (the viewer's *save* button writes the same file)
```

The session keeps the drawing: reloading the viewer, or opening the same object again from the same kernel, brings the
polygons back. Across kernels, `spatialscape.show(adata, regions="amygdala-regions.json")` (or
`s.load_regions(path)`) restores a saved drawing onto the same object, so you can annotate in several sittings,
switching between cell type maps and genes while you draw. For data shown from a path the
selection comes back as the cell ids. Under the hood the viewer posts the selection to the session's own server
(`/_api/selection`); a viewer served from anywhere else never makes that request.

## From R

`show()` reads R objects, so one `saveRDS` and reticulate are all an R session needs:

```r
reticulate::py_require("spatialscape")
ss <- reticulate::import("spatialscape")
saveRDS(spe, f <- tempfile(fileext = ".rds"))
s <- ss$show(f, open_browser = TRUE)        # or rstudioapi::viewer(s$url)
cells <- s$selection()                       # colnames(spe) inside the lasso
spe[, cells]
keep <- s$selection(as_mask = TRUE)          # or a logical vector over the columns
```

The first call reads the object once (about as long as `readRDS` takes); later calls on the same file are instant.

## Housekeeping

`spatialscape.stop()` stops the server thread; the cache is plain folders, safe to delete:
`rm -rf ~/.cache/spatialscape/show`. A remote JupyterHub or Colab needs the kernel's localhost proxied to your
browser (jupyter-server-proxy); not covered yet.
