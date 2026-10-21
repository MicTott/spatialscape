"""The gallery: `site.yaml` -> a folder you can upload (the packaged viewer, datasets.json and the bundles).

`site.yaml` is the one place that describes the gallery: its title and intro, an optional navigation bar,
where the bundles are hosted, and one card per dataset. A card is either a dataset yaml to build (`config:`),
an already built bundle (`bundle:`), or a placeholder (`id:` + `name:`). `datasets.json` is written from it
on every `site build` and is never edited by hand.
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .registry import build_registry, bundle_entry, find_bundles, packaged_app_dir, placeholder_entry

Log = Callable[[str], None]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperSpec(_Model):
    title: str
    url: str | None = None


class NavLink(_Model):
    label: str
    url: str


class NavSpec(_Model):
    """The slim bar above the viewer and the gallery (the registry's `site` block)."""

    title: str | None = None
    logo: str | None = None
    links: list[NavLink] = Field(default_factory=list)


class SiteDataset(_Model):
    """One gallery card: a dataset yaml to build, an already built bundle, or a placeholder."""

    config: Path | None = None  # a dataset.yaml; built (incrementally) into bundles/<id> next to it
    bundle: Path | None = None  # a built bundle directory
    id: str | None = None  # a placeholder card ("coming soon"); needs `name`
    name: str | None = None  # card title; default: the dataset's name
    description: str | None = None  # card text; default: the dataset's description
    platforms: list[str] = Field(default_factory=list)  # placeholder cards only; bundles report their own
    status: Literal["live", "local", "coming soon"] | None = None
    paper: PaperSpec | None = None
    tags: list[str] = Field(default_factory=list)
    accent: str | None = None  # color of the generated card art when there is no thumbnail
    thumbnail: str | None = None  # image URL; default: <bundle>/thumbnail.png

    @model_validator(mode="after")
    def _one_source(self):
        n = sum(x is not None for x in (self.config, self.bundle, self.id))
        if n != 1:
            raise ValueError("each dataset needs exactly one of `config:` (a dataset.yaml), `bundle:` (a built bundle) or `id:` (a placeholder card)")
        if self.id is not None and not self.name:
            raise ValueError(f"placeholder {self.id!r}: set `name:`")
        return self


class SiteConfig(_Model):
    title: str = "spatialscape"
    intro: str | None = None
    nav: NavSpec | None = None
    data_url: str | None = None  # bundles hosted elsewhere at <data_url>/<id>; nothing is copied into the site
    datasets: list[SiteDataset]


def load_site_config(path: str | Path) -> SiteConfig:
    path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping (title, datasets, ...) at the top level")
    site = SiteConfig.model_validate(raw)
    base = path.parent
    for d in site.datasets:
        for attr in ("config", "bundle"):
            p = getattr(d, attr)
            if p is not None:
                p = Path(os.path.expandvars(str(p))).expanduser()
                setattr(d, attr, p if p.is_absolute() else (base / p).resolve())
    return site


def copy_app(app_dir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_dir / "index.html", out / "index.html")
    if (app_dir / "favicon.svg").exists():
        shutil.copy2(app_dir / "favicon.svg", out / "favicon.svg")
    assets_out = out / "assets"
    if assets_out.exists():
        shutil.rmtree(assets_out)
    shutil.copytree(app_dir / "assets", assets_out)


def _viewer(app_dir: Path | None) -> Path:
    app_dir = app_dir or packaged_app_dir()
    if app_dir is None:
        raise FileNotFoundError(
            "this install has no packaged viewer. Install spatialscape from PyPI, or in a source checkout run "
            "`npm run build` then `python python/scripts/bundle_app.py`"
        )
    return app_dir


def _place(bundle: Path, dest: Path, link: bool, log: Log) -> None:
    if dest.resolve() == bundle.resolve():
        return
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    if link:
        os.symlink(bundle.resolve(), dest, target_is_directory=True)
    else:
        # the per-sample build.json fingerprints and the config path hold paths from the building machine
        shutil.copytree(bundle, dest, ignore=shutil.ignore_patterns("build.json"))
        info = dest / "build-info.json"
        if info.exists():
            try:
                d = json.loads(info.read_text())
                d.pop("config", None)
                info.write_text(json.dumps(d, indent=1))
            except ValueError:
                pass
    log(f"{'linked' if link else 'copied'} {bundle} -> {dest}")


def _overlay(entry: dict[str, Any], d: SiteDataset) -> dict[str, Any]:
    """What site.yaml says about a card, on top of what its manifest says."""
    if d.name:
        entry["name"] = d.name
    if d.description is not None:
        entry["description"] = d.description
    if d.status:
        entry["status"] = d.status
    if d.paper:
        entry["paper"] = d.paper.model_dump(exclude_none=True)
    if d.tags:
        entry["tags"] = list(d.tags)
    if d.accent:
        entry["accent"] = d.accent
    if d.thumbnail:
        entry["thumbnail"] = d.thumbnail
    return entry


def build_site_from_config(site_yaml: Path, out: Path | None = None, *, link: bool = False, force: bool = False, app_dir: Path | None = None, log: Log = print) -> Path:
    """Build every `config:` dataset that changed, place the bundles, write the viewer and `datasets.json`."""
    from .build import build_bundle
    from .config import load_config

    site_yaml = Path(site_yaml).expanduser().resolve()
    site = load_site_config(site_yaml)
    out = Path(out).expanduser().resolve() if out is not None else site_yaml.parent / "site"
    app = _viewer(app_dir)
    entries: list[dict[str, Any]] = []
    placed = 0
    for d in site.datasets:
        if d.id is not None:
            entries.append(_overlay(placeholder_entry(d.id, d.name or d.id, d.description, d.platforms), d))
            continue
        if d.config is not None:
            cfg = load_config(d.config)
            log(f"{cfg.id}: {d.config}")
            res = build_bundle(cfg, force=force, log=log)
            for p in res.problems:
                log(f"  ! {p}")
            if res.problems:
                raise ValueError(f"{cfg.id}: the bundle did not validate; fix the problems above and rerun")
            bundle = res.out
        else:
            bundle = d.bundle
            if not (bundle / "manifest.json").exists():
                raise FileNotFoundError(f"{bundle}: no manifest.json here (not a built bundle)")
        bid = json.loads((bundle / "manifest.json").read_text()).get("id") or bundle.name
        if site.data_url:
            url = f"{site.data_url.rstrip('/')}/{bid}"
        else:
            url = bid
            if placed == 0:
                copy_app(app, out)
                log(f"viewer -> {out}")
            _place(bundle, out / bid, link, log)
        placed += 1
        entries.append(_overlay(bundle_entry(bundle, url), d))
    if placed == 0 or site.data_url:
        copy_app(app, out)
        log(f"viewer -> {out}")
    doc: dict[str, Any] = {"title": site.title}
    if site.intro:
        doc["intro"] = site.intro
    if site.nav:
        doc["site"] = site.nav.model_dump(exclude_none=True)
    doc["datasets"] = entries
    reg = out / "datasets.json"
    reg.write_text(json.dumps(doc, indent=2) + "\n")
    log(f"registry -> {reg} ({len(entries)} dataset(s))")
    return out


def build_site(out: Path, bundles: list[Path], *, data_url: str | None = None, link: bool = False, app_dir: Path | None = None, log: Log = print) -> Path:
    """A site from built bundles alone (no site.yaml): the viewer plus a registry generated from their manifests."""
    out = Path(out).expanduser().resolve()
    app = _viewer(app_dir)
    expanded: list[Path] = []
    for b in bundles:
        found = find_bundles(Path(b))
        if not found:
            raise FileNotFoundError(f"{b}: no bundle here (no manifest.json in it or directly under it)")
        expanded += found
    copy_app(app, out)
    log(f"viewer -> {out}")
    if data_url is None:
        for b in expanded:
            bid = json.loads((b / "manifest.json").read_text()).get("id") or b.name
            _place(b, out / bid, link, log)
    doc = build_registry(expanded, url_for=(lambda b, bid: f"{data_url.rstrip('/')}/{bid}") if data_url else (lambda b, bid: bid))
    reg = out / "datasets.json"
    reg.write_text(json.dumps(doc, indent=2) + "\n")
    log(f"registry -> {reg} ({len(doc['datasets'])} dataset(s))")
    return out


def _pad(text: str, comment: str, width: int = 44) -> str:
    return f"{text:<{width}} # {comment}" if len(text) < width else f"{text}   # {comment}"


def write_site_template(items: list[Path], out: Path, *, title: str | None = None) -> Path:
    """A commented `site.yaml` listing the given dataset yamls and bundle folders."""
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    base = out.parent.resolve()
    L = [
        "# site.yaml for spatialscape: the gallery and the viewer around it. Lines starting with # are optional.",
        "# `spatialscape site build site.yaml` builds every `config:` dataset that changed, then writes a folder",
        "# with the viewer, datasets.json and the bundles, ready to upload to any static host.",
        f"title: {json.dumps(title) if title and (':' in title or '#' in title) else (title or 'My datasets')}",
        "# intro: One or two sentences shown under the title.",
        _pad("# nav:", "a slim bar above the viewer and the gallery"),
        "#   title: Our lab",
        "#   links: [{ label: Lab site, url: https://lab.example.org }]",
        _pad("# data_url: https://data.example.org", "bundles hosted elsewhere at <data_url>/<id>; nothing is copied into the site"),
        "datasets:",
    ]
    for item in items:
        item = Path(item).expanduser().resolve()
        rel = os.path.relpath(item, base)
        if item.is_dir():
            L.append(_pad(f"  - bundle: {rel}", "an already built bundle"))
        else:
            L.append(_pad(f"  - config: {rel}", "built into bundles/<id> next to it when the data or the yaml changed"))
        L.append("    # paper: { title: Someone et al. 2026, url: https://doi.org/... }")
        L.append("    # tags: [cortex, visium]")
    L += [
        _pad("  # - id: hippocampus", 'a "coming soon" card'),
        "  #   name: Human hippocampus",
        "  #   description: Later this year.",
        "  #   platforms: [visium, snrnaseq]",
    ]
    out.write_text("\n".join(L) + "\n")
    return out
