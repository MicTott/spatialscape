"""SpatialData stores (scverse), read without the spatialdata package: the on-disk layout is a Zarr group per
element kind and plain Parquet files, in zarr v2 (spatialdata <= 0.4, `.zattrs`) or zarr v3 (0.5 and later,
`zarr.json`), and this module reads both.

    store.zarr/
      images/<name>/     OME-Zarr pyramid; `multiscales[0].coordinateTransformations` places it in each coordinate system
      labels/<name>/     the same, one integer per cell
      shapes/<name>/     shapes.parquet (GeoParquet, WKB geometry: polygons, or points with a `radius` column for
                         Visium spots); the group's attributes carry the transformations
      points/<name>/     points.parquet/part.*.parquet with x, y and a feature column (molecules); attributes name the
                         feature and instance columns and the transformations
      tables/<name>/     AnnData; uns["spatialdata_attrs"] says which element it annotates (region, region_key,
                         instance_key). spatialdata < 0.1 wrote a single table at table/table.

Everything is read into one coordinate system (`global` unless the yaml says otherwise). Transformations are turned
into 2-D affines over (x, y); an image whose transformation rotates or shears is placed by its scale and translation
with a note, since the viewer places images by a pixel size and an offset.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ELEMENT_KINDS = ("images", "labels", "points", "shapes", "tables")
Affine = np.ndarray  # 3x3, rows (x', y', 1) = A @ (x, y, 1)


# ---------------------------------------------------------------- the store
def node_attrs(path: Path) -> dict[str, Any]:
    """A Zarr node's attributes: zarr v3 (`zarr.json`) or v2 (`.zattrs`); {} for a plain directory."""
    zj = Path(path) / "zarr.json"
    if zj.exists():
        try:
            return dict(json.loads(zj.read_text()).get("attributes") or {})
        except (OSError, ValueError):
            return {}
    za = Path(path) / ".zattrs"
    if za.exists():
        try:
            return dict(json.loads(za.read_text()))
        except (OSError, ValueError):
            return {}
    return {}


def is_spatialdata(path: Path) -> bool:
    """A SpatialData store: its root attributes say so, or it has tables next to spatial elements."""
    path = Path(path)
    if not path.is_dir():
        return False
    if "spatialdata_attrs" in node_attrs(path):
        return True
    has_tables = (path / "tables").is_dir() or (path / "table").is_dir()
    return has_tables and any((path / k).is_dir() for k in ("images", "labels", "points", "shapes"))


def elements(store: Path) -> dict[str, list[str]]:
    """The element names per kind, tables included (the single legacy `table/table` counts as `table`)."""
    store = Path(store)
    out: dict[str, list[str]] = {}
    for kind in ELEMENT_KINDS:
        d = store / kind
        names = sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")) if d.is_dir() else []
        if kind == "tables" and not names and (store / "table" / "table").is_dir():
            names = ["table"]
        out[kind] = names
    return out


def table_dir(store: Path, table: str | None) -> Path:
    """The AnnData group of a table; the only table when none is named."""
    store = Path(store)
    names = elements(store)["tables"]
    if table is None:
        if len(names) != 1:
            raise ValueError(f"{store.name} has tables {names}; set `table:`")
        table = names[0]
    if table not in names:
        raise KeyError(f"{store.name} has no table {table!r}; tables are {names}")
    d = store / "tables" / table
    return d if d.is_dir() else store / "table" / "table"


@dataclass
class TableLink:
    """What a table annotates: the element (one name, or several for a table over many regions), the obs column
    naming the element per row, and the obs column matching the element's instances."""

    region: str | list[str] | None
    region_key: str | None
    instance_key: str | None


def table_link(adata) -> TableLink:
    sa = (adata.uns or {}).get("spatialdata_attrs") if adata.uns is not None else None
    if not isinstance(sa, dict):
        return TableLink(None, None, None)
    region = sa.get("region")
    if isinstance(region, np.ndarray | list | tuple):
        region = [str(r) for r in region]
        region = region[0] if len(region) == 1 else region
    elif region is not None:
        region = str(region)
    rk, ik = sa.get("region_key"), sa.get("instance_key")
    return TableLink(region, None if rk is None else str(rk), None if ik is None else str(ik))


# ---------------------------------------------------------------- transformations
def _axes_names(axes: Any) -> list[str]:
    return [a["name"] if isinstance(a, dict) else str(a) for a in (axes or [])]


def _matrix(t: dict[str, Any], in_axes: list[str], out_axes: list[str]) -> tuple[np.ndarray, list[str], list[str]]:
    """One NGFF / SpatialData transformation as a homogeneous matrix (len(out) + 1, len(in) + 1) with its axes."""
    if isinstance(t.get("input"), dict) and t["input"].get("axes"):
        in_axes = _axes_names(t["input"]["axes"])
    if isinstance(t.get("output"), dict) and t["output"].get("axes"):
        out_axes = _axes_names(t["output"]["axes"])
    kind = t.get("type")
    if kind == "sequence":
        m = np.eye(len(in_axes) + 1)
        cur_in, cur_out = in_axes, in_axes
        for sub in t.get("transformations", []):
            sm, s_in, s_out = _matrix(sub, cur_out, cur_out)
            m = sm @ _reorder(m, cur_out, s_in)
            cur_out = s_out
        return m, cur_in, cur_out
    if kind == "identity":
        m = np.zeros((len(out_axes) + 1, len(in_axes) + 1))
        for i, a in enumerate(out_axes):
            if a in in_axes:
                m[i, in_axes.index(a)] = 1
        m[-1, -1] = 1
        return m, in_axes, out_axes
    if kind == "scale":
        s = [float(v) for v in t["scale"]]
        m = np.eye(len(in_axes) + 1)
        for i, v in enumerate(s[: len(in_axes)]):
            m[i, i] = v
        return m, in_axes, in_axes
    if kind == "translation":
        s = [float(v) for v in t["translation"]]
        m = np.eye(len(in_axes) + 1)
        for i, v in enumerate(s[: len(in_axes)]):
            m[i, -1] = v
        return m, in_axes, in_axes
    if kind == "affine":
        rows = np.asarray(t["affine"], dtype=np.float64)
        if rows.ndim != 2:
            raise ValueError("affine transformation without a matrix")
        n_out, n_in = rows.shape[0], rows.shape[1] - 1
        out_axes = out_axes[:n_out] if len(out_axes) >= n_out else out_axes + [f"_{i}" for i in range(n_out - len(out_axes))]
        in_axes = in_axes[:n_in] if len(in_axes) >= n_in else in_axes + [f"_{i}" for i in range(n_in - len(in_axes))]
        m = np.zeros((n_out + 1, n_in + 1))
        m[:n_out] = rows
        m[-1, -1] = 1
        return m, in_axes, out_axes
    raise ValueError(f"transformation type {kind!r} is not supported")


def _reorder(m: np.ndarray, have: list[str], want: list[str]) -> np.ndarray:
    """Rows of `m` (over `have` axes, plus the homogeneous row) in the order of `want`; an axis `want` lacks is zero."""
    if have == want:
        return m
    out = np.zeros((len(want) + 1, m.shape[1]))
    for i, a in enumerate(want):
        if a in have:
            out[i] = m[have.index(a)]
    out[-1] = m[-1]
    return out


def _pick(transforms: list[dict[str, Any]], cs: str, where: str) -> dict[str, Any]:
    named = [t for t in transforms if isinstance(t.get("output"), dict) and t["output"].get("name") == cs]
    if named:
        return named[0]
    systems = sorted({str(t.get("output", {}).get("name")) for t in transforms if isinstance(t.get("output"), dict)})
    if len(transforms) == 1 and not systems:
        return transforms[0]
    raise KeyError(f"{where}: no transformation into coordinate system {cs!r}; it has {systems or 'none'}. Set `coordinate_system:`")


def _xy(m: np.ndarray, in_axes: list[str], out_axes: list[str]) -> Affine:
    """The (x, y) part of a homogeneous matrix over named axes."""
    a = np.eye(3)
    for i, oa in enumerate(("x", "y")):
        if oa not in out_axes:
            continue
        r = out_axes.index(oa)
        for j, ia in enumerate(("x", "y")):
            if ia in in_axes:
                a[i, j] = m[r, in_axes.index(ia)]
        a[i, 2] = m[r, -1]
    return a


def element_affine(store: Path, kind: str, name: str, cs: str = "global") -> Affine:
    """The element's raw (x, y) -> coordinate system `cs` as a 3x3 affine. Images and labels: level 0's own scale and
    translation, then the multiscale's transformation into `cs`; shapes and points: the group's transformation."""
    path = Path(store) / kind / name
    attrs = node_attrs(path)
    where = f"{Path(store).name}/{kind}/{name}"
    if kind in ("images", "labels"):
        ms = (attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales") or [None])[0]
        if not ms:
            raise ValueError(f"{where}: not a multiscale image")
        axes = _axes_names(ms.get("axes")) or ["c", "y", "x"][-len(ms["datasets"][0].get("coordinateTransformations", [{}])[0].get("scale", [1, 1, 1])) :]
        m = np.eye(len(axes) + 1)
        for t in ms["datasets"][0].get("coordinateTransformations", []):
            sm, _, _ = _matrix(t, axes, axes)
            m = sm @ m
        outer = ms.get("coordinateTransformations") or []
        if outer:
            t = _pick(outer, cs, where)
            tm, t_in, t_out = _matrix(t, axes, axes)
            m = tm @ _reorder(m, axes, t_in)
            return _xy(m, axes, t_out)
        return _xy(m, axes, axes)
    axes = _axes_names(attrs.get("axes")) or ["x", "y"]
    transforms = attrs.get("coordinateTransformations") or []
    if not transforms:
        return np.eye(3)
    t = _pick(transforms, cs, where)
    m, t_in, t_out = _matrix(t, axes, axes)
    return _xy(m, t_in, t_out)


def coordinate_systems(store: Path, kind: str, name: str) -> list[str]:
    attrs = node_attrs(Path(store) / kind / name)
    if kind in ("images", "labels"):
        ms = (attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales") or [{}])[0]
        transforms = ms.get("coordinateTransformations") or []
    else:
        transforms = attrs.get("coordinateTransformations") or []
    return sorted({str(t["output"]["name"]) for t in transforms if isinstance(t.get("output"), dict) and "name" in t["output"]})


def affine_tuple(a: Affine) -> tuple[float, float, float, float, float, float]:
    """(a, b, c, d, e, f) for `polygons.affine` / `molecules.affine`: x' = a x + b y + c, y' = d x + e y + f."""
    return (float(a[0, 0]), float(a[0, 1]), float(a[0, 2]), float(a[1, 0]), float(a[1, 1]), float(a[1, 2]))


def is_scale_translation(a: Affine, tol: float = 1e-9) -> bool:
    return abs(a[0, 1]) <= tol and abs(a[1, 0]) <= tol and a[0, 0] > 0 and a[1, 1] > 0


def apply(a: Affine, xy: np.ndarray) -> np.ndarray:
    xy = np.asarray(xy, dtype=np.float64)
    return xy @ a[:2, :2].T + a[:2, 2]


# ---------------------------------------------------------------- shapes (GeoParquet)
@dataclass
class Shapes:
    ids: np.ndarray  # element index as strings
    kind: str  # "polygon" | "circle" | "point"
    centroids: np.ndarray  # (n, 2) in the element's own units
    radius: np.ndarray | None  # per shape, circles only
    polygons: tuple[np.ndarray, np.ndarray, np.ndarray] | None  # (ids per vertex, x, y), polygons only


def shapes_parquet(store: Path, name: str) -> Path:
    return Path(store) / "shapes" / name / "shapes.parquet"


def _wkb_geometries(blobs: list[bytes]) -> list[tuple[str, np.ndarray]]:
    """Each WKB blob as ("point" | "polygon", vertices (k, 2)): a polygon's exterior ring, a multipolygon's largest
    part; Z and M ordinates are skipped. Shapely does it faster when it is installed."""
    try:
        import shapely

        geoms = shapely.from_wkb(blobs)
        out: list[tuple[str, np.ndarray]] = []
        for g in geoms:
            if g is None or g.is_empty:
                out.append(("empty", np.zeros((0, 2))))
            elif g.geom_type == "Point":
                out.append(("point", np.asarray(g.coords)[:, :2]))
            elif g.geom_type == "Polygon":
                out.append(("polygon", np.asarray(g.exterior.coords)[:, :2]))
            elif g.geom_type == "MultiPolygon":
                big = max(g.geoms, key=lambda p: p.area)
                out.append(("polygon", np.asarray(big.exterior.coords)[:, :2]))
            else:
                out.append(("other", np.asarray(shapely.get_coordinates(g))[:, :2]))
        return out
    except ImportError:
        return [_wkb_one(b) for b in blobs]


def _wkb_one(b: bytes) -> tuple[str, np.ndarray]:
    def parse(off: int) -> tuple[str, np.ndarray, int]:
        little = b[off] == 1
        e = "<" if little else ">"
        (code,) = struct.unpack_from(e + "I", b, off + 1)
        off += 5
        base = code % 1000
        dims = 2 + (1 if code >= 1000 else 0) + (1 if code >= 3000 else 0)
        if code & 0x80000000:  # EWKB Z flag
            dims, base = 3, code & 0xFF
        fmt = e + f"{dims}d"
        step = 8 * dims

        def ring(o: int) -> tuple[np.ndarray, int]:
            (n,) = struct.unpack_from(e + "I", b, o)
            o += 4
            pts = np.frombuffer(b, dtype=e + "f8", count=n * dims, offset=o).reshape(n, dims)[:, :2]
            return pts.astype(np.float64), o + n * step

        if base == 1:
            pt = struct.unpack_from(fmt, b, off)
            return "point", np.array([pt[:2]], dtype=np.float64), off + step
        if base == 3:
            (nr,) = struct.unpack_from(e + "I", b, off)
            off += 4
            ext = None
            for k in range(nr):
                pts, off = ring(off)
                if k == 0:
                    ext = pts
            return "polygon", ext if ext is not None else np.zeros((0, 2)), off
        if base == 6:
            (n,) = struct.unpack_from(e + "I", b, off)
            off += 4
            best = np.zeros((0, 2))
            for _ in range(n):
                _k, pts, off = parse(off)
                if len(pts) > len(best):
                    best = pts
            return "polygon", best, off
        if base == 2:  # linestring: its vertices
            pts, off = ring(off)
            return "other", pts, off
        raise ValueError(f"WKB geometry type {code} is not supported (points, polygons and multipolygons are)")

    kind, pts, _ = parse(0)
    return kind, pts


def read_shapes(store: Path, name: str, *, max_vertices: int | None = None) -> Shapes:
    """A shapes element: ids, centroids (the point itself, or the polygon's vertex mean), radii for circles, and the
    polygons' rings as a long table for the shape writer."""
    import pyarrow.parquet as pq

    path = shapes_parquet(store, name)
    df = pq.read_table(path).to_pandas()
    if "geometry" not in df.columns:
        raise ValueError(f"{path}: no geometry column")
    ids = np.asarray(df.index.astype(str))
    geoms = _wkb_geometries([bytes(g) if g is not None else b"" for g in df["geometry"]])
    kinds = {k for k, _ in geoms if k != "empty"}
    radius = np.asarray(df["radius"], dtype=np.float64) if "radius" in df.columns else None
    if kinds <= {"point"}:
        centroids = np.array([pts[0] if len(pts) else (np.nan, np.nan) for _, pts in geoms], dtype=np.float64).reshape(-1, 2)
        return Shapes(ids, "circle" if radius is not None else "point", centroids, radius, None)
    cent = np.full((len(geoms), 2), np.nan)
    vid: list[np.ndarray] = []
    vx: list[np.ndarray] = []
    vy: list[np.ndarray] = []
    for i, (_kind, pts) in enumerate(geoms):
        if not len(pts):
            continue
        ring = pts[:-1] if len(pts) > 1 and np.allclose(pts[0], pts[-1]) else pts
        cent[i] = ring.mean(axis=0)
        if max_vertices and len(ring) > max_vertices:
            ring = ring[np.linspace(0, len(ring) - 1, max_vertices).astype(int)]
        vid.append(np.full(len(ring), ids[i], dtype=object))
        vx.append(ring[:, 0])
        vy.append(ring[:, 1])
    polys = (np.concatenate(vid).astype(str), np.concatenate(vx), np.concatenate(vy)) if vid else (np.array([], dtype=str), np.array([]), np.array([]))
    return Shapes(ids, "polygon", cent, None, polys)


# ---------------------------------------------------------------- labels
def labels_array(store: Path, name: str) -> Path:
    """Level 0 of a labels element, the array `polygons.labels` traces."""
    path = Path(store) / "labels" / name
    attrs = node_attrs(path)
    ms = (attrs.get("multiscales") or attrs.get("ome", {}).get("multiscales") or [{}])[0]
    first = (ms.get("datasets") or [{"path": "0"}])[0]["path"]
    return path / first


def label_centroids(store: Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Each label's id (as a string) and centroid (x, y) in pixels, pixel centres on whole numbers."""
    import zarr
    from skimage.measure import regionprops

    arr = np.squeeze(np.asarray(zarr.open_array(str(labels_array(store, name)), mode="r")[:]))
    if arr.ndim != 2:
        raise ValueError(f"labels {name!r}: expected a 2-D mask, got shape {arr.shape}")
    props = regionprops(arr.astype(np.int64, copy=False))
    ids = np.array([str(p.label) for p in props], dtype=str)
    cent = np.array([(p.centroid[1], p.centroid[0]) for p in props], dtype=np.float64).reshape(-1, 2)
    return ids, cent


# ---------------------------------------------------------------- points
@dataclass
class PointsInfo:
    path: Path  # the points.parquet directory (or file)
    feature_key: str | None
    instance_key: str | None
    columns: list[str]


def points_info(store: Path, name: str) -> PointsInfo:
    from .tables import table_columns

    d = Path(store) / "points" / name
    path = d / "points.parquet"
    if not path.exists():
        cands = [p for p in d.iterdir() if p.suffix == ".parquet"]
        if not cands:
            raise FileNotFoundError(f"{d}: no points.parquet")
        path = cands[0]
    sa = node_attrs(d).get("spatialdata_attrs") or {}
    return PointsInfo(path, sa.get("feature_key"), sa.get("instance_key"), table_columns(path))


# ---------------------------------------------------------------- images
@dataclass
class ImageInfo:
    name: str
    path: Path
    channels: int
    dtype: np.dtype
    affine: Affine  # pixel (x, y) -> coordinate system


def image_infos(store: Path, cs: str = "global") -> list[ImageInfo]:
    """The store's images that reach the coordinate system, with their pixel -> system affine."""
    from .images import ome_zarr_info

    out: list[ImageInfo] = []
    for name in elements(store)["images"]:
        if cs not in coordinate_systems(store, "images", name):
            continue
        p = Path(store) / "images" / name
        info = ome_zarr_info(p)
        if info is None:
            continue
        out.append(ImageInfo(name, p, info.channels, info.dtype, element_affine(store, "images", name, cs)))
    return out


# ---------------------------------------------------------------- matching table rows to an element
def match_instances(obs: pd.DataFrame, instance_key: str | None, element_ids: np.ndarray) -> np.ndarray:
    """For each table row, the position of its instance in the element (-1 when absent): by the instance column
    when the table has one, else by obs names. Numeric ids match their decimal strings."""
    keys = obs[instance_key] if instance_key and instance_key in obs.columns else obs.index
    k = pd.Index(np.asarray(keys).astype(str))
    k = k.str.replace(r"\.0$", "", regex=True) if pd.api.types.is_float_dtype(np.asarray(keys).dtype) else k
    lookup = pd.Index(element_ids.astype(str))
    pos = lookup.get_indexer(k)
    if (pos < 0).all() and len(k):  # ids like "cell_1" against "1": the trailing number
        tail = k.str.extract(r"(\d+)$")[0]
        if tail.notna().all():
            pos = lookup.get_indexer(pd.Index(tail))
    return np.asarray(pos)


def read_shapes_file(path: Path, *, max_vertices: int | None = None) -> Shapes:
    """`read_shapes` for a shapes.parquet given by path (a `polygons.path` / `segmentations.path` in a store)."""
    path = Path(path)
    return read_shapes(path.parent.parent.parent, path.parent.name, max_vertices=max_vertices)


# ---------------------------------------------------------------- a sample of a store, resolved
def table_link_on_disk(store: Path, table: str | None) -> TableLink:
    """The table's region attributes without loading it."""
    import zarr
    from anndata.io import read_elem

    g = zarr.open_group(str(table_dir(store, table)), mode="r")
    attrs = dict(g.attrs)
    if "region" in attrs or "region_key" in attrs:  # zarr v3 stores repeat them at the group root
        region = attrs.get("region")
        if isinstance(region, list | tuple):
            region = [str(r) for r in region]
            region = region[0] if len(region) == 1 else region
        return TableLink(region, attrs.get("region_key"), attrs.get("instance_key"))
    if "uns" in g and "spatialdata_attrs" in g["uns"]:
        sa = read_elem(g["uns"]["spatialdata_attrs"])

        class _A:
            uns = {"spatialdata_attrs": sa}

        return table_link(_A())
    return TableLink(None, None, None)


def resolve_sample(spec):
    """A `samples:` entry whose `path` is a SpatialData store, completed from the store's own metadata: the region
    element the table annotates (coordinates from its centroids, its polygons as cell shapes, a Visium circle's
    radius as the spot size), the points element as molecules, other polygon elements as segmentations to compare
    with; all in the entry's coordinate system. Entries that set a key keep it. Reads attributes and one Parquet
    column, never the matrix or the images."""
    from .config import MicronsSpec, MoleculesSpec, PolygonSpec, SubsetSpec

    store = Path(spec.path)
    if not is_spatialdata(store) or spec.kind != "spatial":
        return spec
    cs = spec.coordinate_system
    els = elements(store)
    upd: dict[str, Any] = {}
    link = table_link_on_disk(store, spec.table)
    region = spec.region
    if region is None:
        if isinstance(link.region, list):
            raise ValueError(f"sample {spec.id}: the table annotates {len(link.region)} elements ({', '.join(link.region[:6])}{', ...' if len(link.region) > 6 else ''}); set `region:` to the one this sample shows")
        region = link.region
    if region is not None and isinstance(link.region, list) and spec.subset is None and link.region_key:
        upd["subset"] = SubsetSpec(column=link.region_key, values=[region])
    set_ = spec.model_fields_set
    kind = "shapes" if region in els["shapes"] else "labels" if region in els["labels"] else None
    if region is not None and kind is None:
        raise KeyError(f"sample {spec.id}: the table's region {region!r} is not a shapes or labels element of the store (shapes: {els['shapes']}, labels: {els['labels']})")
    if kind is not None:
        aff = element_affine(store, kind, region, cs)
        tup = None if np.allclose(aff, np.eye(3)) else affine_tuple(aff)
        if "coords" not in set_:
            upd["coords"] = f"{kind}/{region}"
        if kind == "shapes":
            geo = _shapes_kind(store, region)
            if geo == "polygon" and spec.polygons is None:
                upd["polygons"] = PolygonSpec(path=shapes_parquet(store, region), affine=tup)
            if geo == "circle" and spec.platform == "visium" and spec.microns == MicronsSpec():
                r = _circle_radius(store, region)
                if r is not None and r > 0:
                    sx = float(np.hypot(aff[0, 0], aff[1, 0]))
                    upd["microns"] = MicronsSpec(spot_diameter_fullres=2 * r * sx)
        elif spec.polygons is None:
            upd["polygons"] = PolygonSpec(labels=labels_array(store, region), affine=tup)
    if spec.molecules is None and spec.points is not False:
        cands = [n for n in els["points"] if cs in coordinate_systems(store, "points", n)]
        name = spec.points if isinstance(spec.points, str) else cands[0] if len(cands) == 1 else None
        if isinstance(spec.points, str) and spec.points not in els["points"]:
            raise KeyError(f"sample {spec.id}: no points element {spec.points!r} (the store has {els['points']})")
        if name is not None:
            pi = points_info(store, name)
            aff = element_affine(store, "points", name, cs)
            cols = set(pi.columns)
            feat = pi.feature_key or next((c for c in ("feature_name", "gene", "target") if c in cols), None)
            if feat and {"x", "y"} <= cols:
                upd["molecules"] = MoleculesSpec(
                    path=pi.path,
                    feature_column=feat,
                    x_column="x",
                    y_column="y",
                    qv_column="qv" if "qv" in cols else None,
                    cell_column=pi.instance_key if pi.instance_key in cols else ("cell_id" if "cell_id" in cols else None),
                    nucleus_column="overlaps_nucleus" if "overlaps_nucleus" in cols else None,
                    affine=None if np.allclose(aff, np.eye(3)) else affine_tuple(aff),
                )
        elif len(cands) > 1 and spec.points is None:
            upd["points"] = False  # several: none is drawn until `points:` names one (the log says so)
    return spec.model_copy(update=upd) if upd else spec


def _shapes_kind(store: Path, name: str) -> str:
    """"polygon", "circle" or "point", from the GeoParquet metadata and columns alone."""
    import pyarrow.parquet as pq

    schema = pq.read_schema(shapes_parquet(store, name))
    meta = schema.metadata or {}
    types: list[str] = []
    if b"geo" in meta:
        try:
            types = [str(t) for t in json.loads(meta[b"geo"]).get("columns", {}).get("geometry", {}).get("geometry_types", [])]
        except ValueError:
            types = []
    if not types:  # old stores without geometry types: look at one geometry
        t = pq.read_table(shapes_parquet(store, name), columns=["geometry"]).slice(0, 1)
        types = [_wkb_one(bytes(t.column(0)[0].as_py()))[0].capitalize()] if t.num_rows else []
    if all(t.startswith("Point") for t in types) and types:
        return "circle" if "radius" in schema.names else "point"
    return "polygon"


def _circle_radius(store: Path, name: str) -> float | None:
    import pyarrow.parquet as pq

    t = pq.read_table(shapes_parquet(store, name), columns=["radius"])
    r = t.column(0).to_numpy(zero_copy_only=False).astype(np.float64)
    r = r[np.isfinite(r)]
    return float(np.median(r)) if r.size else None


def store_images(spec) -> list:
    """`images: auto` for a store: every image that reaches the coordinate system, placed by its scale and
    translation; RGB when it has three 8-bit channels, multichannel otherwise."""
    from .config import ImageSpec

    out = []
    for info in image_infos(Path(spec.path), spec.coordinate_system):
        a = info.affine
        sx, sy = float(a[0, 0]), float(a[1, 1])
        if not is_scale_translation(a) or abs(sx - sy) > 1e-6 * max(abs(sx), abs(sy)):
            # the viewer places an image by one pixel size and an offset; a rotation, shear, mirror or unequal axis
            # scale would put it in the wrong place, so it is refused rather than approximated
            m = np.round(a[:2, :2], 6).tolist()
            raise ValueError(
                f"sample {spec.id}: image {info.name!r} reaches coordinate system {spec.coordinate_system!r} through a transformation the viewer "
                f"cannot place (matrix {m}: a rotation, shear, mirror or unequal axis scale). Rasterise it into that coordinate system first "
                f"(spatialdata.transform(sdata.images[{info.name!r}], to_coordinate_system={spec.coordinate_system!r}), then save) "
                f"or set `images: []` on the entry to leave it out"
            )
        rgb = info.channels == 3 and np.dtype(info.dtype) == np.uint8
        out.append(ImageSpec(id=_image_id(info.name), name=info.name, path=info.path, kind="rgb" if rgb else "multichannel", pixel_size="auto", pixels_per_unit=1.0 / sx if sx else 1.0, offset=(float(a[0, 2]), float(a[1, 2]))))
    return out


def _image_id(name: str) -> str:
    import re

    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return s or "image"


def store_segmentations(spec, region: str | None) -> list:
    """Other polygon elements of the store, drawn over the cells for comparison."""
    from .config import SegmentationSpec

    store = Path(spec.path)
    out = []
    for name in elements(store)["shapes"]:
        if name == region or spec.coordinate_system not in coordinate_systems(store, "shapes", name) or _shapes_kind(store, name) != "polygon":
            continue
        aff = element_affine(store, "shapes", name, spec.coordinate_system)
        out.append(SegmentationSpec(id=_image_id(name), name=name, path=shapes_parquet(store, name), affine=None if np.allclose(aff, np.eye(3)) else affine_tuple(aff)))
    return out


def region_centroids(store: Path, spec_coords: str, adata, instance_key: str | None, cs: str) -> tuple[np.ndarray, np.ndarray]:
    """Coordinates for `coords: shapes/<name>` or `labels/<name>`: the element's centroids in the coordinate system,
    one per table row through the instance key, NaN for rows with no instance (a cell whose mask has no pixel), and
    the mask of rows that have one."""
    kind, name = spec_coords.split("/", 1)
    if kind == "shapes":
        sh = read_shapes(store, name)
        ids, cent = sh.ids, sh.centroids
    elif kind == "labels":
        ids, cent = label_centroids(store, name)
    else:
        raise ValueError(f"coords {spec_coords!r}: expected shapes/<name> or labels/<name>")
    pos = match_instances(adata.obs, instance_key, ids)
    missing = int((pos < 0).sum())
    if missing == len(pos):
        raise ValueError(f"no row of the table matches an instance of {kind}/{name} (instance column {instance_key!r}, first ids {list(ids[:3])}, first keys {list(np.asarray(adata.obs.get(instance_key, adata.obs_names))[:3])})")
    xy = np.full((len(pos), 2), np.nan)
    xy[pos >= 0] = cent[pos[pos >= 0]]
    return apply(element_affine(store, kind, name, cs), xy), pos >= 0


def instance_strings(adata) -> list[str]:
    """Each table row's instance id as the element writes it: the instance column as text (integers without a
    decimal point), else the obs names."""
    key = table_link(adata).instance_key
    arr = np.asarray(adata.obs[key] if key and key in adata.obs.columns else adata.obs_names)
    if arr.dtype.kind == "f" and np.all(np.isfinite(arr)) and np.all(arr == np.round(arr)):
        arr = arr.astype(np.int64)
    return [str(v) for v in arr]
