"""spatialscape command line.

Every command is also available as ``sscape <command>``. Help strings here are the source for the
generated CLI reference (``python/scripts/gen_cli_docs.py``), so keep them complete.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(
    help="Build, check and serve static spatialscape viewer bundles.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        typer.echo(f"spatialscape {version('spatialscape')}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", "-V", help="Print the version and exit.", callback=_version_callback, is_eager=True),
) -> None:
    """Build, check and serve static spatialscape viewer bundles."""


PLATFORM_LABEL = {"visium": "Visium", "visium_hd": "Visium HD", "xenium": "Xenium", "merfish": "MERFISH", "snrnaseq": "snRNA-seq", "other": "Sample"}
PLATFORM_PREFIX = {"visium": "vis", "visium_hd": "hd", "xenium": "xen", "merfish": "mer", "snrnaseq": "sn", "other": "smp"}
GENERIC_STORE_NAMES = {"adata", "data", "sample", "outs", "table", "sdata", "spe", "sce"}

CONFIG_ARG = typer.Argument(..., help="Path to `dataset.yaml`. Relative paths inside it resolve against its own folder.", show_default=False)
OUT_OPT = typer.Option(..., "-o", "--out", help="Bundle directory to write (created if missing).", show_default=False)


@app.command()
def init(
    paths: list[str] = typer.Argument(..., help="One or more globs or paths of sample files, e.g. `'data/xenium/*/adata.zarr'`. Quote globs so the shell does not expand them.", show_default=False),
    out: Path = typer.Option("dataset.yaml", "-o", "--out", help="Where to write the starter config."),
    platform: str = typer.Option("xenium", "--platform", help="Platform assigned to every matched sample: `visium`, `visium_hd`, `xenium`, `merfish`, `snrnaseq` or `other`."),
    dataset_id: str = typer.Option("my_dataset", "--id", help="Dataset id (used in `?d=<id>` and bundle names)."),
    name: str = typer.Option("My dataset", "--name", help="Human-readable dataset name."),
):
    """Write a starter `dataset.yaml`.

    Creates one `glob:` entry per pattern with templated ids (`<platform>_{name}`), and a platform block with
    `fields: auto` and `images: auto`, so the first build needs no hand-written mapping. Review the result with
    `plan`, then edit field names, palettes and scale factors as needed.
    """
    import glob as _glob
    import os

    import yaml

    label = PLATFORM_LABEL.get(platform, platform)
    prefix = PLATFORM_PREFIX.get(platform, platform[:3])
    out = out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for pat in paths:
        matches = sorted(_glob.glob(os.path.expanduser(pat)))
        if not matches:
            typer.secho(f"warning: {pat!r} matches nothing right now; ids will come from the files present at build time", fg="yellow", err=True)
        # `{name}` is the parent folder (right for `<sample>/adata.zarr`); `{stem}` is the file or store name
        # (right for `samples/*.h5ad` or `samples/<sample>.zarr`). Pick whichever carries the sample name.
        stems = {Path(m).name.split(".")[0].lower() for m in matches}
        var = "{name}" if matches and stems <= GENERIC_STORE_NAMES else "{stem}"
        # paths in dataset.yaml resolve against the yaml's own folder, so store the pattern relative to it
        abs_pat = os.path.abspath(os.path.expanduser(pat))
        rel_pat = os.path.relpath(abs_pat, out.parent.resolve())
        entries.append({"glob": rel_pat, "platform": platform, "id": f"{prefix}_{var}", "name": f"{var} ({label})", "group": var})
    platform_block: dict = {"fields": "auto"}
    if platform == "snrnaseq":
        platform_block.update({"kind": "embedding", "coords": "obsm/X_umap"})
    else:
        platform_block["images"] = "auto"
    doc = {
        "id": dataset_id,
        "name": name,
        "layout": {"mode": "grid"},
        "platforms": {platform: platform_block},
        "samples": entries,
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False, width=200))
    typer.echo(f"wrote {out}; next: `spatialscape plan {out}` then `spatialscape build {out} -o bundle`")


@app.command()
def plan(config: Path = CONFIG_ARG):
    """Show the expanded sample list without building anything.

    Globs are expanded, templates filled, and `defaults` / `platforms` blocks merged exactly as `build` would do
    it. Use it to check ids, platforms and paths before a long build. No data files are read.
    """
    from .config import load_config

    cfg = load_config(config)
    typer.echo(f"{cfg.id}: {len(cfg.samples)} samples")
    for s in cfg.samples:
        fields = "auto" if s.fields == "auto" else f"{len(s.fields)} fields"
        images = "auto" if s.images == "auto" else f"{len(s.images)} image(s)"
        typer.echo(f"  {s.id:<22} {s.platform:<10} {s.kind:<9} {fields:<10} {images:<10} {s.path}")


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="An `.h5ad` file, an AnnData Zarr store, a SpatialData Zarr store, or an R `.rds` / `.rda` holding a SpatialExperiment / SingleCellExperiment.", show_default=False),
    table: str | None = typer.Option(None, "--table", help="Table key inside a SpatialData store (required when the store has more than one)."),
):
    """Print what a sample file contains, to help write `dataset.yaml`.

    Lists every `obs` column with its type and number of levels (with example values for categoricals),
    the `obsm` keys and their shapes, the layers, and any `uns` keys that look like scale information.
    """
    import numpy as np

    if path.suffix.lower() in (".rds", ".rda", ".rdata"):
        from .rds import read_experiment

        x = read_experiment(path)
        typer.echo(f"{path}: {x.class_name}, {x.n_obs} cells x {x.n_vars} genes; assays: {', '.join(x.assays)}")
        if "sample_id" in x.obs:
            counts = x.obs["sample_id"].astype(str).value_counts()
            typer.echo(f"samples ({len(counts)}): " + ", ".join(f"{k} ({v})" for k, v in counts.items()))
        typer.echo("colData columns:")
        for c in x.obs.columns:
            s = x.obs[c]
            if isinstance(s.dtype, pd.CategoricalDtype) or s.dtype == object:
                n = s.nunique(dropna=True)
                typer.echo(f"  {c:<40} categorical  {n:>5} levels  e.g. {list(map(str, s.dropna().unique()[:6]))}")
            else:
                v = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
                typer.echo(f"  {c:<40} numeric     range {np.nanmin(v):.3g}..{np.nanmax(v):.3g}")
        typer.echo("spatialCoords: " + ("yes" if x.spatial is not None else "no (an snRNA-seq / embedding object)"))
        typer.echo("reducedDims: " + ", ".join(f"{k}{v.shape}" for k, v in x.reduced_dims.items()))
        typer.echo("images: " + (", ".join(f"{i.sample_id}/{i.image_id} (scale {i.scale_factor:.4g}, {'loaded' if i.rgb is not None else 'stored'})" for i in x.images) or "none"))
        typer.echo("rowData columns: " + ", ".join(x.var.columns) + f"; rownames e.g. {', '.join(x.var.index[:3])}")
        typer.echo(f"next: spatialscape convert {path} -o <folder> --assay {'logcounts' if 'logcounts' in x.assays else next(iter(x.assays))} --cols <col1,col2,...>")
        return

    from .readers import read_anndata

    a = read_anndata(path, table)
    typer.echo(f"{path}: {a.n_obs} obs x {a.n_vars} vars")
    typer.echo("obs columns:")
    for c in a.obs.columns:
        s = a.obs[c]
        if isinstance(s.dtype, object) and str(s.dtype) in ("category", "object", "string", "bool"):
            n = s.nunique(dropna=True)
            ex = list(map(str, s.dropna().unique()[:6]))
            typer.echo(f"  {c:<40} categorical  {n:>5} levels  e.g. {ex}")
        else:
            v = s.to_numpy()
            typer.echo(f"  {c:<40} numeric     range {np.nanmin(v):.3g}..{np.nanmax(v):.3g}")
    typer.echo("obsm: " + ", ".join(f"{k}{tuple(np.asarray(a.obsm[k]).shape)}" for k in a.obsm))
    typer.echo("layers: " + ", ".join(k for k in a.layers if k))
    hints = [k for k in a.uns if any(t in k.lower() for t in ("scale", "spacing", "unit", "spatial", "pixel"))]
    typer.echo("uns scale hints: " + ", ".join(hints))
    for k in hints:
        v = a.uns[k]
        if not isinstance(v, dict):
            typer.echo(f"  {k} = {v}")


@app.command()
def convert(
    objects: list[Path] = typer.Argument(..., help="R objects: `.rds` or `.rda`/`.RData` files holding a SpatialExperiment or SingleCellExperiment.", show_default=False),
    out: Path = typer.Option(..., "-o", "--out", help="Folder to write into (created if missing).", show_default=False),
    assay: str = typer.Option("logcounts", "--assay", help="Assay written as the expression matrix. Counts are fine too; `build` normalizes them."),
    cols: str | None = typer.Option(None, "--cols", help="Comma-separated colData columns to keep as annotations. Default: all. Fewer columns keep files small and the viewer's field list short."),
    sample_col: str = typer.Option("sample_id", "--sample-col", help="colData column that defines samples (spatial objects only)."),
    embedding: str | None = typer.Option(None, "--embedding", help="reducedDims entry to use as the 2-D embedding (objects without spatialCoords). Default: UMAP if present."),
    microns_per_pixel: float | None = typer.Option(None, "--microns-per-pixel", help="Microns per coordinate unit, when known (e.g. SpaceRanger's `microns_per_pixel`; required for Visium HD). Default: derive a Visium spot diameter from the spot spacing."),
    object_name: str | None = typer.Option(None, "--object", help="Which object to take from an `.rda` that holds several."),
):
    """Turn R objects (SpatialExperiment / SingleCellExperiment saved as .rds or .rda) into build inputs.

    No R needed: the file is parsed in Python. A spatial object becomes one folder per sample under `OUT`
    (`adata.h5ad`, the H&E as PNG, SpaceRanger-style scale factors), which `init` and `build` pick up with
    no image or scale settings; an object without spatialCoords becomes `OUT/<name>.h5ad` with its UMAP in
    `obsm/X_umap`, ready to be an embedding sample. Needs enough memory to hold the object (roughly what R needs).
    """
    from .convert import convert_object

    keep = [c.strip() for c in cols.split(",") if c.strip()] if cols else None
    written: list[Path] = []
    for obj in objects:
        written += convert_object(obj, out, assay=assay, cols=keep, sample_col=sample_col, embedding=embedding, microns_per_pixel=microns_per_pixel, object_name=object_name, log=typer.echo)
    spatial = [w for w in written if w.name == "adata.h5ad"]
    hint = f'spatialscape init "{out}/*/adata.h5ad" --platform visium --id <id> -o dataset.yaml' if spatial else f"add `{written[0]}` to dataset.yaml as an embedding sample (kind: embedding, coords: obsm/X_umap)"
    typer.echo(f"{len(written)} file(s) written under {out.resolve()}\n  next: {hint}")


@app.command()
def build(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    no_shard: bool = typer.Option(False, "--no-shard", help="Write one file per gene instead of sharded Zarr. Larger file counts, but works on hosts without HTTP Range support (e.g. GitHub Pages)."),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="Suppress per-sample progress output."),
):
    """Build a complete bundle from `dataset.yaml`.

    For every sample: read the object, resolve automatic fields and images, quantize and shard the expression
    matrix, convert coordinates to microns, write observation arrays and ids, pack polygons, convert images,
    and trace annotation outlines. Then write the dataset-level files, render thumbnails and run the same
    checks as `validate`. Exits with status 1 if validation reports problems.
    """
    from .build import build_dataset
    from .config import load_config
    from .validate import validate_local

    cfg = load_config(config)
    log = (lambda *_: None) if quiet else typer.echo
    m = build_dataset(cfg, out, sharded=not no_shard, log=log)
    try:
        from .thumbnail import write_thumbnails

        write_thumbnails(out, hero_id=cfg.thumbnail_sample, log=log)
    except Exception as e:
        typer.secho(f"  thumbnails skipped: {e}", fg="yellow")
    problems = validate_local(out)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    typer.echo(f"built {out} : {len(m.samples)} samples, {sum(s.nObs for s in m.samples)} obs")
    raise typer.Exit(1 if problems else 0)


@app.command("add-sample")
def add_sample_cmd(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    sample: str = typer.Option(..., "--sample", help="Id of the sample to (re)build, as listed by `plan`.", show_default=False),
    no_shard: bool = typer.Option(False, "--no-shard", help="Write one file per gene instead of sharded Zarr."),
    allow_vocab_append: bool = typer.Option(True, "--allow-vocab-append/--no-allow-vocab-append", help="Allow category labels not yet in the dataset vocabulary. They are appended, so existing codes never change; with `--no-allow-vocab-append` a new label is an error."),
):
    """Rebuild one sample inside an existing bundle.

    Reads the sample's entry from `dataset.yaml`, rebuilds only that sample folder, and refreshes
    `manifest.json`, `genes.json` and `features.json`. Other samples are untouched.
    """
    from .build import add_sample
    from .config import load_config

    add_sample(load_config(config), out, sample, sharded=not no_shard, allow_vocab_append=allow_vocab_append)
    typer.echo(f"updated {out} with sample {sample}")


@app.command()
def refresh(config: Path = CONFIG_ARG, out: Path = OUT_OPT):
    """Rewrite the dataset-level files without rebuilding any sample.

    Use after changing field display names, the palette, feature groups, layout order or `thumbnail_sample`.
    Reads each sample's existing `genes.json` and the current manifest, then rewrites `manifest.json`,
    `genes.json` and `features.json`.
    """
    from .build import refresh as _refresh
    from .config import load_config

    m = _refresh(load_config(config), out)
    typer.echo(f"refreshed {out}: {len(m.samples)} samples, groups: {[g.id for g in m.featureGroups]}")


@app.command()
def outlines(
    config: Path = CONFIG_ARG,
    out: Path = OUT_OPT,
    sample: list[str] = typer.Option(None, "--sample", help="Only these sample ids (repeatable). Default: every spatial sample."),
    field: list[str] = typer.Option(None, "--field", help="Only these categorical field ids (repeatable). Default: every categorical field the sample carries."),
    smooth_um: float = typer.Option(150.0, "--smooth-um", help="Side of the majority-vote smoothing window, in microns. Larger values merge small islands into their neighbours."),
    min_feature_um: float = typer.Option(300.0, "--min-feature-um", help="Islands and holes smaller than this (per side, in microns) are removed before tracing."),
):
    """Trace annotation boundaries from the arrays already in a bundle.

    Labels are rasterized at half the cell spacing, majority-smoothed, cleaned of small features, traced with
    marching squares and simplified. Cells labelled `NA` are treated as unknown and filled by their neighbours.
    Results go to `samples/<id>/outlines/<field>.json` and the manifest. No source data is needed, so this is
    cheap to re-run while tuning the two size parameters.
    """
    from .build import add_outlines
    from .config import load_config

    m = add_outlines(load_config(config), out, sample_ids=sample or None, fields=field or None, smooth_um=smooth_um, min_feature_um=min_feature_um)
    typer.echo(f"outlines written: {[(s.id, s.outlines) for s in m.samples if s.outlines]}")


@app.command()
def thumbnails(
    out: Path = typer.Argument(..., help="Bundle directory.", show_default=False),
    hero: str | None = typer.Option(None, "--hero", help="Sample shown on the dataset thumbnail. Default: `thumbnail_sample` from the build, else the first spatial sample in layout order."),
    no_per_sample: bool = typer.Option(False, "--no-per-sample", help="Skip the per-sample thumbnails."),
):
    """Render `thumbnail.png` for the dataset and for each sample.

    One section is drawn from the bundle's own coordinates, colored by the default annotation
    (or the first categorical field the sample carries). `build` runs this automatically.
    """
    from .thumbnail import write_thumbnails

    paths = write_thumbnails(out, per_sample=not no_per_sample, hero_id=hero, log=typer.echo)
    typer.echo(f"wrote {len(paths)} thumbnail(s)")


@app.command()
def validate(target: str = typer.Argument(..., help="A bundle directory, or the `http(s)://` URL of a hosted bundle.", show_default=False)):
    """Check a bundle on disk or over HTTP.

    Locally: the manifest parses, every array has the expected shape and gene-major chunking, categorical
    codes fit their vocabularies, id blocks, polygon files and images are consistent. For a URL: the manifest
    is fetched with CORS headers present, and one expression chunk is requested with a `Range` header expecting
    `206 Partial Content`. Exits with status 1 when problems are found.
    """
    from .validate import validate as _validate

    problems = _validate(target)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    if problems:
        raise typer.Exit(1)
    typer.secho("ok", fg="green")


@app.command()
def serve(
    directory: Path = typer.Argument(".", help="Folder of bundles (each reachable at `/<folder-name>`), a single bundle, or a site written by `site build`."),
    port: int = typer.Option(8787, "--port", help="TCP port."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind. Use `0.0.0.0` to reach the server from other machines."),
    open_browser: bool = typer.Option(False, "--open", help="Open the viewer in the default browser once the server is up."),
):
    """Open your bundles in the viewer locally: one origin for the app and the data.

    Serves the viewer that ships with this package at `/`, a `datasets.json` generated from every bundle in
    the folder (so the landing gallery lists them all), and the bundles themselves with CORS and HTTP Range
    headers. A folder that already contains `index.html` (the output of `site build`) is served as-is.
    A development server, not meant for production traffic.
    """
    from .serve import serve as _serve

    _serve(directory.resolve(), port=port, host=host, open_browser=open_browser)


site_app = typer.Typer(help="Assemble a deployable static site: viewer + registry + bundles.", no_args_is_help=True)
app.add_typer(site_app, name="site")


@site_app.command("build")
def site_build(
    bundles: list[Path] = typer.Argument(..., help="Bundle directories, or folders that contain bundles.", show_default=False),
    out: Path = typer.Option(..., "-o", "--out", help="Site directory to write (created if missing; an existing `datasets.json` there is merged, not replaced).", show_default=False),
    data_url: str | None = typer.Option(None, "--data-url", help="Bundles are hosted elsewhere at `<data-url>/<id>`: write the registry to point there and copy nothing."),
    link: bool = typer.Option(False, "--link", help="Symlink bundle folders into the site instead of copying them (local previews of large data)."),
    title: str | None = typer.Option(None, "--title", help="Gallery title."),
    intro: str | None = typer.Option(None, "--intro", help="One or two sentences under the title."),
):
    """Write a folder you can upload to any static host.

    Copies the viewer into `OUT`, places every bundle at `OUT/<id>/` (or references `--data-url`), and writes
    `OUT/datasets.json` from the bundles' manifests: names, descriptions, platforms, counts and thumbnails.
    Edit that file afterwards for paper links, tags, a `site` navigation block or "coming soon" entries;
    rerunning keeps those edits. Preview with `spatialscape serve OUT`.
    """
    from .site import build_site

    build_site(out, bundles, data_url=data_url, link=link, title=title, intro=intro, log=typer.echo)
    typer.echo(f"site ready: {out}\n  preview: spatialscape serve {out}\n  deploy:  upload the folder to GitHub Pages, Cloudflare Pages, Netlify, S3 + CloudFront, or any static host")


@app.command()
def synth(
    out: Path = typer.Argument(..., help="Directory for the generated inputs.", show_default=False),
    cells: int = typer.Option(2000, "--cells", help="Cells in the first synthetic section (the second has 40% more)."),
    genes: int = typer.Option(50, "--genes", help="Number of synthetic genes."),
):
    """Write a tiny synthetic dataset for tests and demos.

    Produces two fake tissue sections (one log-normalized, one as counts with a flip and rotation), PNG images,
    cell polygons, an embedding sample, and a `dataset.yaml` that ties them together.
    """
    from .synthetic import make_synthetic

    typer.echo(f"wrote {make_synthetic(out, cells, genes)}")


def _describe(e: BaseException) -> str:
    """One readable message per error class; the traceback stays behind SPATIALSCAPE_DEBUG=1."""
    from pydantic import ValidationError
    from yaml import YAMLError

    if isinstance(e, ValidationError):
        lines = [f"{'.'.join(str(x) for x in err['loc']) or '<root>'}: {err['msg']}" for err in e.errors()]
        return "dataset.yaml is not valid:\n  " + "\n  ".join(lines)
    if isinstance(e, YAMLError):
        return f"dataset.yaml could not be parsed: {e}"
    if isinstance(e, FileNotFoundError):
        return f"file not found: {e.filename or e}"
    if isinstance(e, KeyError) and e.args:
        return str(e.args[0])
    if isinstance(e, (ValueError, OSError)):
        return str(e)
    return f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> None:
    """Console entry point: run the Typer app and turn expected failures into one-line errors."""
    import os
    import sys

    try:
        app(args=argv, standalone_mode=False, prog_name="spatialscape")
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except typer.Abort:
        typer.secho("aborted", fg="red", err=True)
        sys.exit(130)
    except Exception as e:
        # usage errors (Typer ships its own click, so match by shape rather than class)
        if hasattr(e, "show") and hasattr(e, "exit_code"):
            e.show()  # type: ignore[attr-defined]
            sys.exit(e.exit_code)  # type: ignore[attr-defined]
        if os.environ.get("SPATIALSCAPE_DEBUG"):
            raise
        typer.secho(f"error: {_describe(e)}", fg="red", err=True)
        typer.secho("set SPATIALSCAPE_DEBUG=1 for the full traceback", dim=True, err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
