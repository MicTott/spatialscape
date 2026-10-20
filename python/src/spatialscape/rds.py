"""Read SpatialExperiment / SingleCellExperiment / Seurat objects straight from .rds / .rda files, without R.

Uses the rdata package to parse the serialized objects into plain Python structures, then picks out what the
viewer needs: assays (sparse or dense), colData, rowData, spatialCoords, reducedDims and imgData. For a Seurat
object: the layers of one assay, `meta.data`, the ident, the reductions, the other assays as prefixed feature
sets (ATAC peaks, gene activity, motif scores) and the fragment files a ChromatinAssay points at.
HDF5-backed assays (DelayedArray, BPCells) are not supported; realize them in R first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp

R_NA_INT = -2147483648


@dataclass
class RImage:
    sample_id: str
    image_id: str
    scale_factor: float
    rgb: np.ndarray | None  # (h, w, 3) uint8 for loaded images
    path: str | None = None  # for stored / remote images


@dataclass
class RFeatureSet:
    """Another assay of a Seurat object with its own features (ATAC peaks, gene activity, motif scores): drawn in
    the viewer as features named `<prefix><feature>` next to the genes."""

    name: str
    prefix: str  # "peak: ", "activity: ", "motif: ", or "<assay>: "
    var: pd.DataFrame
    assays: dict[str, Any]  # layer -> features x cells


@dataclass
class RFragments:
    """A fragment file a Signac ChromatinAssay was built from (the path as it was on the machine that built it)."""

    path: str
    cells: dict[str, str] | None  # cell name in the object -> barcode in the file; None when they are the same

    @property
    def run(self) -> str:
        """A short id for the run: the Cell Ranger sample folder (`<run>/outs/atac_fragments.tsv.gz`), else the file stem."""
        parts = self.path.replace("\\", "/").rstrip("/").split("/")
        if len(parts) >= 3 and parts[-2] == "outs":
            return parts[-3]
        name = parts[-1]
        for suffix in (".tsv.gz", ".tsv", ".bed.gz", ".bed", ".gz"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name


def fragment_columns(cells: list[str], fragments: list[RFragments]) -> tuple[pd.Series, pd.Series] | None:
    """Per cell, the run and the barcode its fragments carry, from the Fragment records (None when no record maps
    cells): the columns `tracks:` needs as `sample_column` and `barcode_column` for an object pooled from runs."""
    if not any(f.cells for f in fragments):
        return None
    run = pd.Series([None] * len(cells), index=pd.Index(cells), dtype=object)
    bc = pd.Series([None] * len(cells), index=pd.Index(cells), dtype=object)
    for f in fragments:
        if not f.cells:
            continue
        hit = run.index.intersection(list(f.cells))
        run[hit] = f.run
        bc[hit] = [f.cells[c] for c in hit]
    return pd.Series(pd.Categorical(run.to_numpy()), index=run.index), bc


@dataclass
class RExperiment:
    class_name: str
    assays: dict[str, Any]  # name -> scipy.sparse (genes x cells, CSC) or ndarray; for Seurat the layers of one assay
    obs: pd.DataFrame
    var: pd.DataFrame
    spatial: np.ndarray | None  # (n_cells, 2)
    reduced_dims: dict[str, np.ndarray] = field(default_factory=dict)
    images: list[RImage] = field(default_factory=list)
    feature_sets: list[RFeatureSet] = field(default_factory=list)  # Seurat: the other assays
    fragments: list[RFragments] = field(default_factory=list)  # Seurat: fragment files of a ChromatinAssay
    assay_name: str | None = None  # Seurat: the assay whose layers `assays` holds
    notes: list[str] = field(default_factory=list)  # what was left out, for the build log

    @property
    def n_obs(self) -> int:
        return len(self.obs)

    @property
    def n_vars(self) -> int:
        return len(self.var)


# ---------------------------------------------------------------- helpers over the parsed structure
def _attrs(o: Any) -> dict:
    return o.get("attributes") or {} if isinstance(o, dict) else {}


def _cls(o: Any) -> str | None:
    return o.get("class_name") if isinstance(o, dict) else None


def _is_null(o: Any) -> bool:
    return o is None or (isinstance(o, dict) and o.get("type") == "null")


def _strings(o: Any) -> list[str | None]:
    if _is_null(o):
        return []
    d = o.get("data", [])
    return [None if s is None else str(s) for s in d]  # NA_character_ arrives as None; "NA" can be a real label


def _named_list(o: Any) -> dict[str, Any]:
    """An R list/vector with a `names` attribute -> dict."""
    if _is_null(o):
        return {}
    names = _strings(_attrs(o).get("names"))
    data = o.get("data", [])
    return {str(n): v for n, v in zip(names, data, strict=False) if n is not None}


def _dframe(o: Any) -> tuple[list[str] | None, dict[str, Any]]:
    """S4 DFrame -> (rownames, columns)."""
    a = _attrs(o)
    rn = _strings(a.get("rownames")) if not _is_null(a.get("rownames")) else None
    return rn, _named_list(a.get("listData"))


def _vector_to_series(o: Any, n: int) -> pd.Series | None:
    """One colData column -> pandas Series (None for nested / unsupported columns)."""
    if _is_null(o):
        return None
    t = o.get("type")
    a = _attrs(o)
    cls = _strings(a.get("class")) if "class" in a else []
    data = o.get("data")
    if t == "integer" and "levels" in a:  # factor; NA codes arrive as NaN (or R's NA_integer_)
        raw = np.asarray(data, dtype=np.float64)
        na = np.isnan(raw) | (raw == R_NA_INT)
        codes = np.where(na, 0, raw).astype(np.int64) - 1
        levels = _strings(a["levels"])
        return pd.Series(pd.Categorical.from_codes(codes, categories=[str(x) for x in levels]))
    if t in ("integer", "double", "boolean"):
        arr = np.asarray(data)
        if arr.ndim != 1 or len(arr) != n:
            return None
        if t == "integer":
            na = arr == R_NA_INT
            if na.any():  # nullable integers: cluster ids stay integers instead of turning into 1.0, 2.0
                return pd.Series(pd.arrays.IntegerArray(np.where(na, 0, arr).astype(np.int64), na))
            return pd.Series(arr.astype(np.int64))
        if t == "boolean":
            if arr.dtype.kind == "f":  # NA logicals arrive as NaN
                return pd.Series(pd.array(np.where(np.isnan(arr), None, arr == 1), dtype="boolean"))
            if arr.dtype == object:  # or as None among bools
                return pd.Series(pd.array([None if v is None else bool(v) for v in arr], dtype="boolean"))
            return pd.Series(pd.array(arr.astype(bool), dtype="boolean"))
        return pd.Series(arr)
    if t == "string":
        vals = _strings(o)
        if len(vals) != n:
            return None
        return pd.Series(pd.Categorical(vals))
    if "Rle" in (cls or []) or _cls(o) == "Rle":
        return None
    return None


def _matrix(o: Any) -> Any:
    """dgCMatrix / dgRMatrix / dense numeric matrix -> scipy CSC (or ndarray). Raises for delayed arrays."""
    cls = _cls(o)
    a = _attrs(o)
    if cls in ("dgCMatrix", "dgRMatrix", "lgCMatrix"):
        i = np.asarray(a["i"]["data"], dtype=np.int32) if cls != "dgRMatrix" else np.asarray(a["j"]["data"], dtype=np.int32)
        p = np.asarray(a["p"]["data"], dtype=np.int64)
        x = np.asarray(a["x"]["data"], dtype=np.float32)
        dim = [int(v) for v in np.asarray(a["Dim"]["data"])]
        if cls == "dgRMatrix":
            return sp.csr_matrix((x, i, p), shape=(dim[0], dim[1])).tocsc()
        return sp.csc_matrix((x, i, p), shape=(dim[0], dim[1]))
    if cls and ("Delayed" in cls or "HDF5" in cls):
        raise ValueError(f"assay is a {cls}; realize it in R first (e.g. assay(x, name) <- as(assay(x, name), 'dgCMatrix'))")
    if o.get("type") in ("integer", "double") and "dim" in a:
        dim = [int(v) for v in np.asarray(a["dim"]["data"])]
        return np.asarray(o["data"], dtype=np.float32).reshape(dim, order="F")
    raise ValueError(f"unsupported assay class {cls or o.get('type')}")


def _dimnames(o: Any) -> tuple[list[str] | None, list[str] | None]:
    a = _attrs(o)
    dn = a.get("Dimnames") or a.get("dimnames")
    if _is_null(dn):
        return None, None
    parts = dn.get("data", [])
    out: list[list[str] | None] = []
    for p in parts[:2]:
        out.append(None if _is_null(p) else [str(s) for s in _strings(p)])
    while len(out) < 2:
        out.append(None)
    return out[0], out[1]


def _hex_to_rgb(colors: list[str | None], h: int, w: int) -> np.ndarray:
    """An R `raster` (dim = rows x columns of colour strings) as an (h, w, 3) uint8 array. Unlike every other R
    matrix, a raster is stored row by row (`as.raster` transposes on the way in), so the flat vector is C order."""
    arr = np.array([c if c else "#000000" for c in colors], dtype="U9")
    hexs = np.char.lstrip(arr, "#")
    rgb = np.zeros((len(arr), 3), dtype=np.uint8)
    for k in range(3):
        rgb[:, k] = [int(s[2 * k : 2 * k + 2], 16) if len(s) >= 6 else 0 for s in hexs]
    return rgb.reshape(h, w, 3)


def _images(int_metadata: dict[str, Any]) -> list[RImage]:
    imgdata = int_metadata.get("imgData")
    if _is_null(imgdata):
        return []
    _, cols = _dframe(imgdata)
    if not cols:
        return []
    sample_ids = _strings(cols.get("sample_id"))
    image_ids = _strings(cols.get("image_id"))
    scales = list(np.asarray(cols["scaleFactor"]["data"], dtype=float)) if "scaleFactor" in cols else [1.0] * len(sample_ids)
    data_col = cols.get("data")
    entries = []
    items = _attrs(data_col).get("listData", {}).get("data", []) if _cls(data_col) == "SimpleList" else data_col.get("data", []) if isinstance(data_col, dict) else []
    for k, (sid, iid) in enumerate(zip(sample_ids, image_ids, strict=False)):
        img = items[k] if k < len(items) else None
        rgb = None
        path = None
        cls = _cls(img)
        a = _attrs(img)
        if cls == "LoadedSpatialImage":
            raster = a.get("image")
            dim = [int(v) for v in np.asarray(_attrs(raster)["dim"]["data"])] if "dim" in _attrs(raster) else None
            if dim:
                rgb = _hex_to_rgb(_strings(raster), dim[0], dim[1])
        elif cls == "StoredSpatialImage":
            path = (_strings(a.get("path")) or [None])[0]
        elif cls == "RemoteSpatialImage":
            path = (_strings(a.get("url")) or [None])[0]
        entries.append(RImage(sample_id=str(sid), image_id=str(iid), scale_factor=float(scales[k]), rgb=rgb, path=path))
    return entries


# ---------------------------------------------------------------- parsing (rdata, mapped onto plain dicts)
# Every parsed value is a dict {"type", "class_name", "data", "attributes"}: "integer" / "double" / "boolean" /
# "string" vectors (numpy arrays; strings as lists with None for NA), "vector" for lists, "S4" with the class name,
# "null", and "unsupported" for closures, environments, language objects and bytecode (Seurat stores the
# functions it was called with in @commands; they are walked past, never needed).

R_LATIN1 = 1 << 2
R_UTF8 = 1 << 3


def _load_rdata():
    try:
        import rdata
        from rdata.parser import RObjectType
    except ImportError as e:  # pragma: no cover
        raise ImportError("reading R objects needs the rdata package: pip install rdata") from e
    return rdata, RObjectType


def _sym_name(node, T) -> str | None:
    """The name of a symbol node (a later use of a symbol is a reference to its first occurrence)."""
    while node is not None and node.info.type == T.REF:
        node = node.referenced_object
    if node is None or node.info.type != T.SYM:
        return None
    v = node.value
    while v is not None and v.info.type == T.REF:
        v = v.referenced_object
    return v.value.decode("utf-8", "replace") if isinstance(v.value, bytes) else (None if v.value is None else str(v.value))


def _pairs(node, T) -> list[tuple[str | None, Any]]:
    out = []
    while node is not None and node.info.type == T.LIST:
        car, cdr = node.value
        out.append((_sym_name(node.tag, T), car))
        node = cdr
    return out


def _char(node) -> str | None:
    v = node.value
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("latin-1" if node.info.gp & R_LATIN1 and not node.info.gp & R_UTF8 else "utf-8", "replace")
    return str(v)


def _convert(o, T) -> Any:
    """rdata's object tree -> the dict form the readers above work on."""
    if o is None:
        return {"type": "null"}
    t = o.info.type
    if t == T.REF:
        return _convert(o.referenced_object, T)
    if t in (T.NIL, T.NILVALUE):
        return {"type": "null"}
    attrs = {k: _convert(v, T) for k, v in _pairs(o.attributes, T) if k is not None} if o.attributes is not None else {}
    if t == T.S4:
        cls = attrs.get("class", {}).get("data") or [None]
        pkg = (attrs.get("class", {}).get("attributes", {}).get("package", {}).get("data") or [None])[0]
        return {"type": "S4", "class_name": cls[0], "package_name": pkg, "attributes": attrs}
    if t in (T.VEC, T.EXPR):
        return {"type": "vector", "class_name": "vector", "data": [_convert(x, T) for x in o.value], "attributes": attrs}
    if t == T.LIST:  # a pairlist used as data (rare): a named list
        items = _pairs(o, T)
        attrs["names"] = {"type": "string", "class_name": "string_vector", "data": [k for k, _ in items], "attributes": {}}
        return {"type": "vector", "class_name": "vector", "data": [_convert(v, T) for _, v in items], "attributes": attrs}
    if t == T.STR:
        return {"type": "string", "class_name": "string_vector", "data": [_char(c) for c in o.value], "attributes": attrs}
    if t == T.CHAR:
        return {"type": "string", "class_name": "string_vector", "data": [_char(o)], "attributes": attrs}
    if t == T.INT:
        v = o.value
        data = np.asarray(v.filled(R_NA_INT) if np.ma.isMaskedArray(v) else v, dtype=np.int32)
        return {"type": "integer", "class_name": "integer_vector", "data": data, "attributes": attrs}
    if t == T.LGL:
        v = o.value
        if np.ma.isMaskedArray(v):
            data = np.where(np.ma.getmaskarray(v), np.nan, v.filled(False).astype(np.float64))  # NA logicals as NaN
        else:
            data = np.asarray(v, dtype=bool)
        return {"type": "boolean", "class_name": "boolean_vector", "data": data, "attributes": attrs}
    if t == T.REAL:
        return {"type": "double", "class_name": "double_vector", "data": np.asarray(o.value, dtype=np.float64), "attributes": attrs}
    if t == T.CPLX:
        return {"type": "complex", "class_name": "complex_vector", "data": np.asarray(o.value), "attributes": attrs}
    if t == T.RAW:
        return {"type": "raw", "class_name": "raw_vector", "data": o.value, "attributes": attrs}
    return {"type": "unsupported", "class_name": t.name, "attributes": attrs}


def _parse(path: Path, object_name: str | None):
    """Parse an .rds (one object) or .rda / .RData (named objects -> dict) file."""
    rdata, T = _load_rdata()
    parsed = rdata.parser.parse_file(str(path))
    root = parsed.object
    if path.suffix.lower() in (".rda", ".rdata"):
        objs = {k: v for k, v in _pairs(root, T) if k is not None}
        if object_name is not None:
            if object_name not in objs:
                raise KeyError(f"{path}: no object named {object_name!r}; found {list(objs)}")
            return {object_name: _convert(objs[object_name], T)}
        return {k: _convert(v, T) for k, v in objs.items()}
    return _convert(root, T)


# ---------------------------------------------------------------- Seurat objects

PEAK_NAME = re.compile(r"^(chr)?[0-9A-Za-z_.]+[:-]\d+-\d+$")  # chr1-100-200 (Signac) or chr1:100-200


def _r_dataframe(o: Any) -> tuple[list[str] | None, dict[str, Any]]:
    """S3 data.frame (Seurat meta.data, meta.features) -> (rownames, columns). Compact row names c(NA, -n) mean 1..n."""
    if _is_null(o):
        return None, {}
    a = _attrs(o)
    rn = a.get("row.names")
    rownames = None
    if not _is_null(rn):
        if rn.get("type") == "string":
            rownames = [str(x) for x in _strings(rn)]
        else:
            vals = np.asarray(rn.get("data", []), dtype=np.float64)
            if len(vals) == 2 and (np.isnan(vals[0]) or vals[0] == R_NA_INT):
                rownames = [str(i) for i in range(1, int(abs(vals[1])) + 1)]
            else:
                rownames = [str(int(v)) for v in vals]
    return rownames, _named_list(o)


def _dense(o: Any) -> np.ndarray | None:
    """A numeric R matrix (double/integer with `dim`) as a float64 array, or None for anything else / empty."""
    if _is_null(o) or o.get("type") not in ("double", "integer") or "dim" not in _attrs(o):
        return None
    dim = [int(v) for v in np.asarray(_attrs(o)["dim"]["data"])]
    if not all(dim):
        return None
    return np.asarray(o["data"], dtype=np.float64).reshape(dim, order="F")


def _logmap(o: Any) -> tuple[list[str], dict[str, np.ndarray]]:
    """Seurat's LogMap (a logical matrix, rows x layers) -> (row names, {layer: mask})."""
    a = _attrs(o)
    dim = [int(v) for v in np.asarray(a["dim"]["data"])]
    rows, cols = _dimnames(o)
    data = np.asarray(o.get("data", []))
    mat = (np.where(np.isnan(data), 0, data) if data.dtype.kind == "f" else data).reshape(dim, order="F").astype(bool)
    return [str(r) for r in (rows or [])], {str(c): mat[:, j] for j, c in enumerate(cols or [])}


def _nonempty(m: Any) -> bool:
    if _is_null(m):
        return False
    a = _attrs(m)
    dim = a.get("Dim") or a.get("dim")
    return not _is_null(dim) and all(int(v) for v in np.asarray(dim["data"]))


def _layer_matrix(m: Any) -> Any:
    """A layer (dgCMatrix or dense) as features x cells CSC."""
    out = _matrix(m)
    return out if sp.issparse(out) else sp.csc_matrix(out)


def _align_cells(mat: Any, have: list[str] | None, want: list[str], what: str) -> Any:
    """Reorder the columns of a features x cells matrix from `have` to `want` (the object's cells)."""
    if have is None or list(have) == list(want):
        if mat.shape[1] != len(want):
            raise ValueError(f"{what}: {mat.shape[1]} cells, but the object has {len(want)}")
        return mat
    pos = {c: i for i, c in enumerate(have)}
    try:
        idx = np.fromiter((pos[c] for c in want), dtype=np.int64, count=len(want))
    except KeyError as e:
        raise ValueError(f"{what}: cell {e.args[0]!r} of the object is missing from the assay") from None
    return mat[:, idx]


def _seurat_assay(obj: Any, name: str, cells: list[str]) -> tuple[list[str], dict[str, Any], pd.DataFrame]:
    """One Seurat assay -> (features, {layer: features x cells CSC in the object's cell order}, feature data frame).
    `Assay` / `ChromatinAssay` / `SCTAssay` keep `counts` and `data`; `Assay5` joins split layers (`counts.run1`,
    `counts.run2`, ...) through its LogMaps. `scale.data` is never read."""
    a = _attrs(obj)
    cls = _cls(obj) or ""
    layers: dict[str, Any] = {}
    if cls == "Assay5":
        feat_names, feat_masks = _logmap(a["features"])
        cell_names, cell_masks = _logmap(a["cells"])
        groups: dict[str, list[str]] = {}
        for lname in _named_list(a["layers"]):
            base = lname.split(".")[0]
            if base == "scale":
                continue
            groups.setdefault(base, []).append(lname)
        pieces = _named_list(a["layers"])
        F, C = len(feat_names), len(cell_names)
        for base, names in groups.items():
            if len(names) == 1 and feat_masks[names[0]].all() and cell_masks[names[0]].all():
                m = _layer_matrix(pieces[names[0]])
                if m.shape != (F, C):
                    raise ValueError(f"assay {name}: layer {names[0]} is {m.shape}, expected {(F, C)}")
                layers[base] = m
                continue
            rows_all, cols_all, vals_all = [], [], []
            for lname in names:
                m = _layer_matrix(pieces[lname]).tocoo()
                fi = np.flatnonzero(feat_masks[lname])
                ci = np.flatnonzero(cell_masks[lname])
                if m.shape != (len(fi), len(ci)):
                    raise ValueError(f"assay {name}: layer {lname} is {m.shape}, but its maps cover {(len(fi), len(ci))} (join the layers in R with JoinLayers())")
                rows_all.append(fi[m.row])
                cols_all.append(ci[m.col])
                vals_all.append(m.data)
            layers[base] = sp.csc_matrix((np.concatenate(vals_all), (np.concatenate(rows_all), np.concatenate(cols_all))), shape=(F, C))
        have = cell_names
        features = feat_names
        _, fcols = _r_dataframe(a.get("meta.data"))
    else:  # Assay, ChromatinAssay, SCTAssay
        have = None
        features = None
        for lname in ("counts", "data"):
            m = a.get(lname)
            if _nonempty(m):
                layers[lname] = _layer_matrix(m)
                if features is None:
                    features, have = _dimnames(m)
        if features is None:
            rn, _ = _r_dataframe(a.get("meta.features"))
            features = rn
        _, fcols = _r_dataframe(a.get("meta.features"))
    if not layers:
        raise ValueError(f"assay {name}: no counts or data layer")
    n_feat = next(iter(layers.values())).shape[0]
    if features is None or len(features) != n_feat:
        features = [f"{name}_{i}" for i in range(n_feat)]
    layers = {k: _align_cells(v, have, cells, f"assay {name}, layer {k}") for k, v in layers.items()}
    var = pd.DataFrame(index=pd.Index([str(f) for f in features]))
    for cname, col in fcols.items():
        s = _vector_to_series(col, n_feat)
        if s is not None:
            var[cname] = s.to_numpy() if not isinstance(s.dtype, pd.CategoricalDtype) else s.astype(str).to_numpy()
    return [str(f) for f in features], layers, var


def _peak_like(features: list[str]) -> bool:
    sample = features[: min(len(features), 500)]
    return bool(sample) and sum(1 for f in sample if PEAK_NAME.match(f)) >= 0.9 * len(sample)


def _feature_prefix(name: str, cls: str, features: list[str]) -> str:
    low = name.lower()
    if cls == "ChromatinAssay" or _peak_like(features):
        return "peak: "
    if "activ" in low:
        return "activity: "
    if "chromvar" in low or "motif" in low:
        return "motif: "
    if low in ("adt", "protein", "cite"):
        return "protein: "
    return f"{name}: "


def _fragments_of(obj: Any) -> list[RFragments]:
    out = []
    for fr in _attrs(obj).get("fragments", {}).get("data", []) if not _is_null(_attrs(obj).get("fragments")) else []:
        fa = _attrs(fr)
        path = (_strings(fa.get("path")) or [None])[0]
        if not path:
            continue
        cells_obj = fa.get("cells")
        cells = None
        if not _is_null(cells_obj) and cells_obj.get("type") == "string":
            names = _strings(_attrs(cells_obj).get("names"))
            vals = _strings(cells_obj)
            if names and len(names) == len(vals):
                cells = {str(n): str(v) for n, v in zip(names, vals, strict=False) if n is not None and v is not None}
        out.append(RFragments(path=path, cells=cells))
    return out


def _read_seurat(root: Any, path: Path) -> RExperiment:
    a = _attrs(root)
    cells, cols = _r_dataframe(a.get("meta.data"))
    if not cells:
        raise ValueError(f"{path}: Seurat object without cell names in meta.data")
    n = len(cells)
    obs = pd.DataFrame(index=pd.Index(cells))
    for name, col in cols.items():
        s = _vector_to_series(col, n)
        if s is not None:
            obs[name] = s.to_numpy() if not isinstance(s.dtype, pd.CategoricalDtype) else s.values
    ident = a.get("active.ident")
    if not _is_null(ident) and "ident" not in obs:
        s = _vector_to_series(ident, n)
        names = _strings(_attrs(ident).get("names"))
        if s is not None:
            if names and len(names) == n and list(names) != cells:
                s = s.set_axis(names).reindex(cells)
            obs["ident"] = s.values

    assays = _named_list(a.get("assays"))
    if not assays:
        raise ValueError(f"{path}: Seurat object without assays")
    parsed = {name: (_cls(obj) or "", *_seurat_assay(obj, name, cells)) for name, obj in assays.items()}
    active = (_strings(a.get("active.assay")) or [None])[0]
    gene_like = [nm for nm, (cls, feats, _, _) in parsed.items() if cls != "ChromatinAssay" and not _peak_like(feats)]
    primary = active if active in gene_like else (gene_like[0] if gene_like else next(iter(parsed)))
    _pcls, pfeat, players, pvar = parsed[primary]
    notes: list[str] = []
    sets: list[RFeatureSet] = []
    primary_set = set(pfeat)
    for nm, (cls, feats, layers, var) in parsed.items():
        if nm == primary:
            continue
        shared = sum(1 for f in feats[:2000] if f in primary_set)
        if feats and shared >= 0.5 * min(len(feats), 2000):
            notes.append(f"assay {nm} left out: its features are the {primary} genes again")
            continue
        sets.append(RFeatureSet(name=nm, prefix=_feature_prefix(nm, cls, feats), var=var, assays=layers))
    fragments = [f for nm, obj in assays.items() if _cls(obj) == "ChromatinAssay" for f in _fragments_of(obj)]
    fcols = fragment_columns(cells, fragments)
    if fcols is not None:
        obs["fragment_run"], obs["fragment_barcode"] = fcols[0].to_numpy(), fcols[1].to_numpy()

    reduced: dict[str, np.ndarray] = {}
    for name, dr in _named_list(a.get("reductions")).items():
        emb = _dense(_attrs(dr).get("cell.embeddings"))
        if emb is None or emb.shape[0] != n:
            continue
        rows, _ = _dimnames(_attrs(dr).get("cell.embeddings"))
        if rows and list(rows) != cells:
            pos = {c: i for i, c in enumerate(rows)}
            emb = emb[[pos[c] for c in cells]] if all(c in pos for c in cells) else emb
        reduced[name] = emb
    if not _is_null(a.get("images")) and a["images"].get("data"):
        notes.append("Seurat spatial images are not read yet; export a SpatialExperiment for spatial samples")
    return RExperiment(
        class_name="Seurat", assays=players, obs=obs, var=pvar, spatial=None, reduced_dims=reduced, images=[],
        feature_sets=sets, fragments=fragments, assay_name=primary, notes=notes,
    )


# ---------------------------------------------------------------- public API
def read_experiment(path: str | Path, object_name: str | None = None) -> RExperiment:
    """Parse a SpatialExperiment / SingleCellExperiment / SummarizedExperiment / Seurat object from .rds or .rda/.RData."""
    path = Path(path)
    if path.suffix.lower() in (".rda", ".rdata"):
        objs = _parse(path, object_name)
        if not isinstance(objs, dict):
            raise ValueError(f"{path}: could not read the .rda file")
        candidates = {k: v for k, v in objs.items() if _cls(v) in SUPPORTED_CLASSES}
        if object_name:
            if object_name not in objs:
                raise KeyError(f"{path}: no object named {object_name!r}; found {list(objs)}")
            root = objs[object_name]
        elif len(candidates) == 1:
            root = next(iter(candidates.values()))
        else:
            raise ValueError(f"{path}: contains {list(objs)}; pick one with --object")
    else:
        root = _parse(path, None)
    cls = _cls(root)
    if cls == "Seurat":
        return _read_seurat(root, path)
    if cls not in SUPPORTED_CLASSES:
        raise ValueError(f"{path}: expected a SpatialExperiment / SingleCellExperiment / Seurat object, got {cls}")
    a = _attrs(root)

    # assays
    assays_list = _attrs(_attrs(a["assays"]).get("data")).get("listData")
    assays = {name: _matrix(m) for name, m in _named_list(assays_list).items()}
    if not assays:
        raise ValueError(f"{path}: no assays")
    first = next(iter(assays.values()))
    n_vars, n_obs = first.shape

    # names: rowRanges partitioning NAMES (RangedSE) or NAMES slot; colData rownames; else Dimnames
    rownames = None
    rr = a.get("rowRanges")
    if not _is_null(rr):
        part = _attrs(rr).get("partitioning")
        if not _is_null(part) and not _is_null(_attrs(part).get("NAMES")):
            rownames = _strings(_attrs(part)["NAMES"])
    if rownames is None and not _is_null(a.get("NAMES")):
        rownames = _strings(a["NAMES"])
    col_rn, col_cols = _dframe(a["colData"])
    dn_rows, dn_cols = _dimnames(_named_list(assays_list)[next(iter(assays))])
    if rownames is None:
        rownames = dn_rows
    colnames = col_rn if col_rn else dn_cols
    if rownames is None or len(rownames) != n_vars:
        rownames = [f"gene{i}" for i in range(n_vars)]
    if colnames is None or len(colnames) != n_obs:
        colnames = [f"cell{i}" for i in range(n_obs)]

    # colData
    obs = pd.DataFrame(index=pd.Index([str(c) for c in colnames], name=None))
    for name, col in col_cols.items():
        s = _vector_to_series(col, n_obs)
        if s is not None:
            obs[name] = s.to_numpy() if not isinstance(s.dtype, pd.CategoricalDtype) else s.values
    # rowData: elementMetadata of rowRanges (RangedSE) or of the object
    var = pd.DataFrame(index=pd.Index([str(r) for r in rownames]))
    em = _attrs(rr).get("elementMetadata") if not _is_null(rr) else None
    if _is_null(em):
        em = a.get("elementMetadata")
    if not _is_null(em):
        _, rcols = _dframe(em)
        for name, col in rcols.items():
            s = _vector_to_series(col, n_vars)
            if s is not None:
                var[name] = s.to_numpy() if not isinstance(s.dtype, pd.CategoricalDtype) else s.astype(str).to_numpy()

    # int_colData: reducedDims, spatialCoords
    spatial = None
    reduced: dict[str, np.ndarray] = {}
    icd = a.get("int_colData")
    if not _is_null(icd):
        _, icols = _dframe(icd)
        sc = icols.get("spatialCoords")
        if not _is_null(sc) and "dim" in _attrs(sc):
            dim = [int(v) for v in np.asarray(_attrs(sc)["dim"]["data"])]
            spatial = np.asarray(sc["data"], dtype=np.float64).reshape(dim, order="F")[:, :2]
        rd = icols.get("reducedDims")
        if not _is_null(rd):
            _, rcols = _dframe(rd)
            for name, m in rcols.items():
                if isinstance(m, dict) and "dim" in _attrs(m) and m.get("type") in ("double", "integer"):
                    dim = [int(v) for v in np.asarray(_attrs(m)["dim"]["data"])]
                    reduced[name] = np.asarray(m["data"], dtype=np.float64).reshape(dim, order="F")
    images = _images(_named_list(a.get("int_metadata"))) if not _is_null(a.get("int_metadata")) else []
    return RExperiment(class_name=cls or "", assays=assays, obs=obs, var=var, spatial=spatial, reduced_dims=reduced, images=images)


SUPPORTED_CLASSES = {"SpatialExperiment", "SingleCellExperiment", "SummarizedExperiment", "RangedSummarizedExperiment", "Seurat"}
