"""`spatialscape.show(...)`: look at an object from the session you are in, no site needed.

    import spatialscape
    s = spatialscape.show(adata, color="cell_type")   # builds once, starts a local server, shows the viewer
    cells = s.selection()                              # the cells inside the last lasso, as obs names
    sub = adata[cells]                                 # straight into a DE test

Accepts an AnnData in memory, a path (h5ad, zarr, SpatialData, .rds / .rda), a dataset yaml or a built bundle.
An in-memory object is built straight from memory into ~/.cache/spatialscape/show/<hash>, where the hash covers
the data and the settings, so showing the same object again is instant. One server thread per Python process
serves every bundle shown so far (the gallery lists them); the viewer posts each lasso selection back to it, and
`selection()` maps the selection onto the rows of your object.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

Log = Callable[[str], None]
EMBEDDING_RE = re.compile(r"umap|tsne|t-sne|embedding|draw_graph|pca", re.I)

_SERVER: dict[str, Any] = {}  # one per process: httpd, thread, url, root
_LOCK = threading.Lock()


def cache_root() -> Path:
    from .genes import cache_dir

    return cache_dir() / "show"


# ---------------------------------------------------------------- what to show
def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_")
    return s or "sample"


def _hash_bytes(h, x) -> None:
    if isinstance(x, np.ndarray):
        h.update(np.ascontiguousarray(x).tobytes())
    else:
        h.update(str(x).encode())


def _hash_adata(adata, params: dict, *, obs_columns: list[str], obsm_key: str | None, layer: str) -> str:
    """A digest of the data that matters for the viewer: names, the used obs columns, coordinates and a strided
    sample of the matrix. Cheap enough to run on every call; strict enough that an edited object rebuilds."""
    h = hashlib.sha1()
    _hash_bytes(h, json.dumps(params, sort_keys=True, default=str))
    _hash_bytes(h, adata.shape)
    if getattr(adata, "isbacked", False):  # on disk: the file identity stands in for the matrix
        p = Path(str(adata.filename))
        st = p.stat() if p.exists() else None
        _hash_bytes(h, f"backed:{p}:{st.st_size if st else 0}:{st.st_mtime_ns if st else 0}")
    _hash_bytes(h, pd.util.hash_pandas_object(pd.Series(np.asarray(adata.obs_names, dtype=str)), index=False).to_numpy())
    _hash_bytes(h, pd.util.hash_pandas_object(pd.Series(np.asarray(adata.var_names, dtype=str)), index=False).to_numpy())
    for col in obs_columns:
        if col in adata.obs:
            _hash_bytes(h, pd.util.hash_pandas_object(adata.obs[col].astype(str), index=False).to_numpy())
    if obsm_key is not None and obsm_key in adata.obsm:
        _hash_bytes(h, np.asarray(adata.obsm[obsm_key])[:, :2].astype(np.float64))
    if getattr(adata, "isbacked", False):
        return h.hexdigest()[:16]
    X = adata.X if layer == "X" else adata.layers[layer]
    if hasattr(X, "nnz") and hasattr(X, "data"):
        _hash_bytes(h, X.nnz)
        _hash_bytes(h, np.asarray(X.data[:: max(1, X.nnz // 200_000)]))
        if hasattr(X, "indptr"):
            _hash_bytes(h, np.asarray(X.indptr[:: max(1, len(X.indptr) // 50_000)]))
    else:  # dense (or array-like): a strided sample of rows, never the whole matrix
        step = max(1, adata.n_obs // 500)
        arr = np.asarray(X[::step])
        _hash_bytes(h, arr.ravel()[:: max(1, arr.size // 200_000)])
    return h.hexdigest()[:16]


def _coords_for(adata, coords: str | None) -> str:
    if coords is not None:
        return coords if coords.startswith(("obsm/", "obs/")) else f"obsm/{coords}"
    if "spatial" in adata.obsm:
        return "obsm/spatial"
    emb = next((k for k in adata.obsm if EMBEDDING_RE.search(str(k))), None)
    if emb is None:
        raise ValueError(f"no coordinates found: pass coords='obsm/<key>' (obsm has {list(adata.obsm.keys())})")
    return f"obsm/{emb}"


def _config_for_adata(adata, *, key: str, name: str, coords: str, platform: str | None, sample: str | None, fields, color: str | None, layer: str, normalized: str):
    """A DatasetConfig for one in-memory object: `init`'s column heuristics, one sample per value of `sample`."""
    from .config import DatasetConfig, ExpressionSpec, SampleSpec, SubsetSpec
    from .discover import field_id
    from .init import describe_columns, suggest_fields

    obs = adata.obs
    spatial = "spatial" in coords.lower()
    if platform is None:
        platform = ("visium" if "spatial" in (adata.uns or {}) else "other") if spatial else "snrnaseq"
    fmap: Any
    if fields == "auto":
        fmap = "auto"
    elif isinstance(fields, dict):
        fmap = dict(fields)
    else:
        fmap = dict(suggest_fields(describe_columns(obs), skip={sample} if sample else None).mapped)
        for col in fields or []:
            if col not in obs:
                raise KeyError(f"fields: obs column {col!r} not found")
            fmap[field_id(col)] = col
    default_color: dict | None = None
    default_gene: str | None = None
    if color is not None:
        if color in obs.columns:
            if fmap != "auto" and color not in fmap.values():
                fmap[field_id(color)] = color
            default_color = {"field": field_id(color) if fmap == "auto" else next(f for f, c in fmap.items() if c == color)}
        elif color in adata.var_names:
            default_gene = color
        else:
            raise KeyError(f"color={color!r} is neither an obs column nor a gene")
    elif fmap != "auto" and fmap:
        first_cat = next((f for f, c in fmap.items() if isinstance(c, str) and not pd.api.types.is_numeric_dtype(obs[c])), None)
        if first_cat:
            default_color = {"field": first_cat}
    base: dict[str, Any] = {"platform": platform, "kind": "spatial" if spatial else "embedding", "path": Path(f"memory:{key}"), "coords": coords, "expression": ExpressionSpec(layer=layer, normalized=normalized), "fields": fmap, "images": []}
    specs: list[SampleSpec] = []
    rows: dict[str, np.ndarray] = {}
    if sample is None:
        specs.append(SampleSpec(id="all", name=name, **base))
        rows["all"] = np.arange(adata.n_obs)
    else:
        if sample not in obs:
            raise KeyError(f"sample={sample!r} is not an obs column")
        values = obs[sample].astype(str).to_numpy()
        for v in pd.unique(values):
            sid = _safe(v)
            specs.append(SampleSpec(id=sid, name=str(v), group=str(v), subset=SubsetSpec(column=sample, values=[str(v)]), **base))
            rows[sid] = np.flatnonzero(values == v)
    cfg = DatasetConfig(id=key, name=name, default_color=default_color, default_gene=default_gene, samples=specs)
    return cfg, rows


# ---------------------------------------------------------------- one builder per bundle folder
def _alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) would terminate the process there; trust the lock's age instead
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _build_lock(out: Path, log: Log, *, timeout: float = 7200) -> Iterator[bool]:
    """Two sessions showing the same object build the same folder; the second waits for the first instead of
    writing into it. An O_EXCL lock file holds the owner's pid; a lock whose owner is gone (or, on Windows,
    older than the timeout) is stale. Yields whether we waited, so the caller re-checks what exists."""
    lock = out.with_name(out.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    waited = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
                age = time.time() - lock.stat().st_mtime
            except (OSError, ValueError):
                pid, age = 0, 0.0
            if (pid and not _alive(pid)) or age > timeout:
                claim = lock.with_name(f"{lock.name}.stale{os.getpid()}")
                try:
                    os.replace(lock, claim)  # atomic: only one waiter wins the stale lock, the others see it gone and retry
                    claim.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - t0 > timeout:
                raise TimeoutError(f"another process has been building {out} for over {timeout:.0f} s; remove {lock} if it is stale") from None
            if not waited:
                log(f"another process is building this object (pid {pid or '?'}); waiting for it")
                waited = True
            time.sleep(0.5)
    try:
        yield waited
    finally:
        lock.unlink(missing_ok=True)


# ---------------------------------------------------------------- the server thread
def _ensure_server(root: Path, host: str = "127.0.0.1", port: int | None = None) -> str:
    from .serve import make_server

    with _LOCK:
        cur = _SERVER
        if cur and cur["root"] == root and cur["thread"].is_alive():
            return cur["url"]
        httpd = make_server(root, port=port or 0, host=host, session=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="spatialscape-show")
        thread.start()
        url = f"http://{host}:{httpd.server_address[1]}/"
        _SERVER.update(httpd=httpd, thread=thread, url=url, root=root)
        return url


def stop() -> None:
    """Stop this process's viewer server (bundles stay in the cache)."""
    with _LOCK:
        if _SERVER:
            _SERVER["httpd"].shutdown()
            _SERVER.clear()


# ---------------------------------------------------------------- the session
class Session:
    """A shown dataset: its URL, and the way back from a lasso to your rows."""

    def __init__(self, *, url: str, api: str, key: str, bundle: Path, adata=None, rows: dict[str, np.ndarray] | None = None, height: int = 650):
        self.url = url
        self.api = api
        self.key = key
        self.bundle = Path(bundle)
        self.adata = adata
        self.rows = rows
        self.height = height
        self._orders: dict[str, np.ndarray] = {}
        self._ids: dict[str, np.ndarray] = {}

    def __repr__(self) -> str:
        return f"spatialscape.Session({self.url})"

    def _repr_html_(self) -> str:
        return f'<iframe src="{self.url}" style="width:100%;height:{self.height}px;border:0;border-radius:8px;background:#0e1116" allow="clipboard-write"></iframe>'

    def open(self) -> None:
        """Open the viewer in the default browser (outside notebooks)."""
        webbrowser.open(self.url)

    def _obs(self, sid: str, name: str) -> np.ndarray:
        import zarr

        return np.asarray(zarr.open_group(str(self.bundle / "samples" / sid / "obs.zarr"), mode="r")[name][:])

    def _ids_of(self, sid: str) -> np.ndarray:
        """Cell ids in bundle order (stored as JSON blocks, the way the viewer reads them)."""
        d = self.bundle / "samples" / sid / "ids"
        blocks = sorted(d.glob("*.json"), key=lambda p: int(p.stem))
        return np.asarray([i for b in blocks for i in json.loads(b.read_text())], dtype=str)

    def raw_selection(self) -> dict:
        """What the viewer last posted: {version, samples: {sample id: bundle-order indices}}."""
        with urllib.request.urlopen(f"{self.api}/selection?d={self.key}", timeout=5) as r:
            return json.loads(r.read() or b"{}")

    def raw_regions(self) -> dict:
        """The regions drawn in the viewer: {version, groups: [{name, color}], codes: {sample id: base64 uint16}}."""
        with urllib.request.urlopen(f"{self.api}/regions?d={self.key}", timeout=5) as r:
            return json.loads(r.read() or b"{}")

    def regions(self) -> pd.Series | dict[str, str]:
        """The region each cell was drawn into (the Regions panel of the viewer), as a pandas Series indexed by obs
        names (None outside every region) for an in-memory object, or {id: region} for data shown from a path."""
        doc = self.raw_regions()
        names = [g["name"] for g in doc.get("groups") or []]
        per_sample = {sid: np.frombuffer(base64.b64decode(b64), dtype="<u2") for sid, b64 in (doc.get("codes") or {}).items()}
        if self.adata is not None and self.rows is not None:
            out = pd.Series([None] * self.adata.n_obs, index=self.adata.obs_names, dtype=object, name="region")
            for sid, codes in per_sample.items():
                if sid not in self.rows:
                    continue
                if sid not in self._orders:
                    self._orders[sid] = self._obs(sid, "order")
                hit = np.flatnonzero(codes < len(names))
                rows = self.rows[sid][self._orders[sid][hit]]
                out.iloc[rows] = [names[c] for c in codes[hit]]
            return out
        result: dict[str, str] = {}
        for sid, codes in per_sample.items():
            if sid not in self._ids:
                self._ids[sid] = self._ids_of(sid)
            for i in np.flatnonzero(codes < len(names)):
                result[str(self._ids[sid][i])] = names[codes[i]]
        return result

    def selection(self, *, as_mask: bool = False):
        """The cells inside the last lasso. For an in-memory object: their obs names (a pandas Index you can index
        the object with), or with `as_mask=True` a boolean array over its rows. For data shown from a path: the ids."""
        doc = self.raw_selection()
        per_sample = doc.get("samples") or {}
        if self.adata is not None and self.rows is not None:
            parts = []
            for sid, idx in per_sample.items():
                if sid not in self.rows or not idx:
                    continue
                if sid not in self._orders:
                    self._orders[sid] = self._obs(sid, "order")
                parts.append(self.rows[sid][self._orders[sid][np.asarray(idx, dtype=np.int64)]])
            rows = np.sort(np.concatenate(parts)) if parts else np.zeros(0, dtype=np.int64)
            if as_mask:
                mask = np.zeros(self.adata.n_obs, dtype=bool)
                mask[rows] = True
                return mask
            return self.adata.obs_names[rows]
        names: list[str] = []
        for sid, idx in per_sample.items():
            if not idx:
                continue
            if sid not in self._ids:
                self._ids[sid] = self._ids_of(sid)
            names.extend(self._ids[sid][np.asarray(idx, dtype=np.int64)].tolist())
        return names


# ---------------------------------------------------------------- show()
def show(
    data,
    *,
    color: str | None = None,
    coords: str | None = None,
    sample: str | None = None,
    platform: str | None = None,
    fields: list[str] | dict[str, str] | str | None = None,
    layer: str = "X",
    normalized: str = "auto",
    name: str | None = None,
    height: int = 650,
    port: int | None = None,
    open_browser: bool = False,
    verbose: bool = False,
    log: Log = print,
) -> Session:
    """Show an object in the viewer and return a Session (displays inline in notebooks; `.url` elsewhere).

    data: an AnnData, or a path (h5ad / zarr / SpatialData / .rds / .rda / dataset yaml / built bundle).
    color: an obs column or a gene to color by at first. coords: obsm key (default: spatial, else the UMAP-like
    one). sample: obs column that splits the object into one panel per value. fields: obs columns to expose
    besides the ones picked automatically, a {field id: column} map, or "auto" for every usable column.
    """
    from .build import build_dataset

    lines: list[str] = []
    blog: Log = log if verbose else lines.append
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    rows: dict[str, np.ndarray] | None = None
    adata = None
    if hasattr(data, "obs") and hasattr(data, "X"):  # an AnnData
        from . import readers

        adata = data
        coords = _coords_for(adata, coords)
        params = {"coords": coords, "sample": sample, "platform": platform, "fields": fields, "color": color, "layer": layer, "normalized": normalized, "recipe": 2}
        name = name or f"AnnData {adata.n_obs:,} cells x {adata.n_vars:,} features"
        # the menu decides which obs columns are shown; they must be part of the hash, or re-clustering shows stale labels
        cfg, rows = _config_for_adata(adata, key="pending", name=name, coords=coords, platform=platform, sample=sample, fields=fields, color=color, layer=layer, normalized=normalized)
        used_cols = sorted({c for c in [sample, color] if c} | {c for sp in cfg.samples for c in (list(map(str, adata.obs.columns)) if sp.fields == "auto" else sp.fields.values())})
        key = _hash_adata(adata, params, obs_columns=used_cols, obsm_key=coords[5:] if coords.startswith("obsm/") else None, layer=layer)
        cfg.id = key
        for sp in cfg.samples:
            sp.path = Path(f"memory:{key}")
        out = root / key
        with _build_lock(out, log):
            built = not (out / "manifest.json").exists()
            if built:
                readers.MEMORY[key] = adata
                try:
                    build_dataset(cfg, out, log=blog)
                finally:
                    readers.MEMORY.pop(key, None)
                np.savez(out / "rows.npz", **rows)
            else:
                rows = dict(np.load(out / "rows.npz"))
    else:
        key, out, built = _show_path(Path(str(data)).expanduser(), root, color=color, coords=coords, sample=sample, platform=platform, log=blog)
    url_root = _ensure_server(root, port=port)
    url = f"{url_root}?d={key}"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    what = "built" if built else "cached"
    log(f"{what} in {time.perf_counter() - t0:.1f} s → {url}" + ("" if built else " (same data as before: no rebuild)"))
    return Session(url=url, api=f"{url_root}_api", key=key, bundle=out, adata=adata, rows=rows, height=height)


def _show_path(path: Path, root: Path, *, color, coords, sample, platform, log: Log) -> tuple[str, Path, bool]:
    """A file, store, R object, dataset yaml or built bundle: `init`'s menu when needed, then an incremental build
    keyed by the path, so a rebuilt file shows its new contents and an unchanged one is instant."""
    from .build import build_bundle
    from .config import load_config
    from .init import write_menu

    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    if (path / "manifest.json").exists():  # a built bundle: link it into the served folder under its own name
        key = _safe(path.name)
        link = root / key
        if link.is_symlink() or link.exists():
            if link.resolve() != path:
                link.unlink()
                link.symlink_to(path, target_is_directory=True)
        else:
            link.symlink_to(path, target_is_directory=True)
        return key, path, False
    key = hashlib.sha1(str(path).encode()).hexdigest()[:12]
    work = root / f"{key}.src"
    work.mkdir(parents=True, exist_ok=True)
    if path.suffix in (".yaml", ".yml"):
        cfg = load_config(path)
    else:
        menu = work / "dataset.yaml"
        if not menu.exists():
            write_menu([str(path)], out=menu, dataset_id=key, name=path.name, platform=platform, log=log)
        cfg = load_config(menu)
        if color or coords or sample:
            log("note: color/coords/sample apply to in-memory objects; for files edit the menu yaml the first call wrote: " + str(menu))
    out = root / key
    with _build_lock(out, log):
        res = build_bundle(cfg, out, log=log)
    built = any(a.build for a in res.plan.actions)
    return key, out, built
