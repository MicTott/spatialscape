"""sscape command line."""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="Build static spatialscape viewer bundles.", no_args_is_help=True)


@app.command()
def build(
    config: Path = typer.Argument(..., help="dataset.yaml"),
    out: Path = typer.Option(..., "-o", "--out", help="output bundle directory"),
    no_shard: bool = typer.Option(False, help="one file per gene instead of sharded zarr"),
    quiet: bool = typer.Option(False, "-q"),
):
    """Build a complete bundle from dataset.yaml."""
    from .build import build_dataset
    from .config import load_config
    from .validate import validate_local

    cfg = load_config(config)
    log = (lambda *_: None) if quiet else typer.echo
    m = build_dataset(cfg, out, sharded=not no_shard, log=log)
    problems = validate_local(out)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    typer.echo(f"built {out} : {len(m.samples)} samples, {sum(s.nObs for s in m.samples)} obs")
    raise typer.Exit(1 if problems else 0)


@app.command("add-sample")
def add_sample_cmd(
    config: Path,
    out: Path = typer.Option(..., "-o", "--out"),
    sample: str = typer.Option(..., "--sample", help="sample id in dataset.yaml"),
    no_shard: bool = False,
    allow_vocab_append: bool = typer.Option(True, help="allow new category labels (appended, never reordered)"),
):
    """(Re)build one sample into an existing bundle and refresh manifest/genes."""
    from .build import add_sample
    from .config import load_config

    add_sample(load_config(config), out, sample, sharded=not no_shard, allow_vocab_append=allow_vocab_append)
    typer.echo(f"updated {out} with sample {sample}")


@app.command()
def outlines(
    config: Path,
    out: Path = typer.Option(..., "-o", "--out"),
    sample: list[str] = typer.Option(None, "--sample", help="limit to these sample ids"),
    field: list[str] = typer.Option(None, "--field", help="limit to these categorical field ids"),
    smooth_um: float = typer.Option(150.0, help="majority-smoothing window in microns"),
    min_feature_um: float = typer.Option(300.0, help="islands/holes smaller than this (per side) are removed"),
):
    """Compute boundary outlines for categorical fields from an existing bundle."""
    from .build import add_outlines
    from .config import load_config

    m = add_outlines(load_config(config), out, sample_ids=sample or None, fields=field or None, smooth_um=smooth_um, min_feature_um=min_feature_um)
    typer.echo(f"outlines written: {[(s.id, s.outlines) for s in m.samples if s.outlines]}")


@app.command()
def refresh(config: Path, out: Path = typer.Option(..., "-o", "--out")):
    """Rewrite manifest.json, genes.json and features.json without rebuilding samples."""
    from .build import refresh as _refresh
    from .config import load_config

    m = _refresh(load_config(config), out)
    typer.echo(f"refreshed {out}: {len(m.samples)} samples, groups: {[g.id for g in m.featureGroups]}")


@app.command()
def validate(target: str = typer.Argument(..., help="bundle directory or http(s) URL")):
    """Check a bundle: schema, shapes, codes, and (for URLs) CORS + Range support."""
    from .validate import validate as _validate

    problems = _validate(target)
    for p in problems:
        typer.secho(f"  ! {p}", fg="red")
    if problems:
        raise typer.Exit(1)
    typer.secho("ok", fg="green")


@app.command()
def serve(directory: Path = typer.Argument("."), port: int = 8787, host: str = "127.0.0.1"):
    """Serve a directory with CORS and HTTP Range support for local viewing."""
    from .serve import serve as _serve

    _serve(directory.resolve(), port=port, host=host)


@app.command()
def synth(out: Path = typer.Argument(..., help="directory for synthetic inputs"), cells: int = 2000, genes: int = 50):
    """Write a tiny synthetic dataset (h5ad + png + dataset.yaml)."""
    from .synthetic import make_synthetic

    typer.echo(f"wrote {make_synthetic(out, cells, genes)}")


@app.command()
def plan(config: Path):
    """Show the expanded sample list (globs, templates, defaults applied) without building anything."""
    from .config import load_config

    cfg = load_config(config)
    typer.echo(f"{cfg.id}: {len(cfg.samples)} samples")
    for s in cfg.samples:
        fields = "auto" if s.fields == "auto" else f"{len(s.fields)} fields"
        images = "auto" if s.images == "auto" else f"{len(s.images)} image(s)"
        typer.echo(f"  {s.id:<22} {s.platform:<10} {s.kind:<9} {fields:<10} {images:<10} {s.path}")


@app.command()
def init(
    paths: list[str] = typer.Argument(..., help="glob(s) or paths of h5ad / zarr samples, e.g. 'data/xenium/*/adata.zarr'"),
    out: Path = typer.Option("dataset.yaml", "-o", "--out"),
    platform: str = typer.Option("xenium", help="platform for the matched samples"),
    dataset_id: str = typer.Option("my_dataset", "--id"),
    name: str = typer.Option("My dataset", "--name"),
):
    """Write a starter dataset.yaml: one glob entry per pattern, fields and images discovered automatically."""
    import yaml

    doc = {
        "id": dataset_id,
        "name": name,
        "layout": {"mode": "grid"},
        "platforms": {platform: {"fields": "auto", "images": "auto"}},
        "samples": [
            {"glob": p, "platform": platform, "id": f"{platform[:3]}_{{name}}", "name": f"{{name}} ({platform})", "group": "{name}"} for p in paths
        ],
    }
    out.write_text(yaml.safe_dump(doc, sort_keys=False, width=200))
    typer.echo(f"wrote {out}; next: `spatialscape plan {out}` then `spatialscape build {out} -o bundle`")


@app.command()
def inspect(path: Path, table: str | None = None):
    """Print obs columns, obsm keys and scale hints of an AnnData/SpatialData object."""
    import numpy as np

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
    typer.echo("layers: " + ", ".join(a.layers.keys()))
    hints = [k for k in a.uns if any(t in k.lower() for t in ("scale", "spacing", "unit", "spatial", "pixel"))]
    typer.echo("uns scale hints: " + ", ".join(hints))
    for k in hints:
        v = a.uns[k]
        if not isinstance(v, dict):
            typer.echo(f"  {k} = {v}")


if __name__ == "__main__":
    app()
