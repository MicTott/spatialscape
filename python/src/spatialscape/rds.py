"""Read SpatialExperiment / SingleCellExperiment objects straight from .rds / .rda files, without R.

Uses rds2py to parse the serialized S4 object into plain Python structures, then picks out what the
viewer needs: assays (sparse or dense), colData, rowData, spatialCoords, reducedDims and imgData.
HDF5-backed assays (DelayedArray) are not supported; realize them in R first.
"""
from __future__ import annotations

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
class RExperiment:
    class_name: str
    assays: dict[str, Any]  # name -> scipy.sparse (genes x cells, CSC) or ndarray
    obs: pd.DataFrame
    var: pd.DataFrame
    spatial: np.ndarray | None  # (n_cells, 2)
    reduced_dims: dict[str, np.ndarray] = field(default_factory=dict)
    images: list[RImage] = field(default_factory=list)

    @property
    def n_obs(self) -> int:
        return len(self.obs)

    @property
    def n_vars(self) -> int:
        return len(self.var)


# ---------------------------------------------------------------- helpers over rds2py's generic structure
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
    return [None if (s is None or s == "NA") else str(s) for s in d]


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
            arr = arr.astype(np.float64)
            arr[arr == R_NA_INT] = np.nan
        elif t == "boolean":
            if arr.dtype.kind == "f":  # NA logicals arrive as NaN
                return pd.Series(pd.array(np.where(np.isnan(arr), None, arr == 1), dtype="boolean"))
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
    arr = np.array([c if c else "#000000" for c in colors], dtype="U9")
    hexs = np.char.lstrip(arr, "#")
    rgb = np.zeros((len(arr), 3), dtype=np.uint8)
    for k in range(3):
        rgb[:, k] = [int(s[2 * k : 2 * k + 2], 16) if len(s) >= 6 else 0 for s in hexs]
    return rgb.reshape(w, h, 3).transpose(1, 0, 2)  # raster is stored column-major (h x w)


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


# ---------------------------------------------------------------- parsing (rds2py, with string attributes kept)
def _load_rds2py():
    """Import rds2py quietly: it prints a line per optional BiocPy package it cannot find."""
    import contextlib
    import io

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import rds2py
            from rds2py import PyRdaReader, PyRdsReader
    except ImportError as e:  # pragma: no cover
        raise ImportError("reading R objects needs the rds2py package: pip install rds2py") from e
    return rds2py, PyRdsReader, PyRdaReader


def _parse(path: Path, object_name: str | None):
    """rds2py's generic parse, except that string vectors keep their attributes (raster images need `dim`)."""
    _rds2py, PyRdsReader, PyRdaReader = _load_rds2py()

    class _Parser(PyRdsReader.PyRdsParser):
        def _process_object(self, obj):
            res = super()._process_object(obj)
            if res.get("type") == "string" and "attributes" not in res:
                try:
                    attrs = self._process_attributes(obj)
                except Exception:
                    attrs = {}
                if attrs:
                    res["attributes"] = attrs
            return res

    if path.suffix.lower() in (".rda", ".rdata"):

        class _Helper(_Parser):
            def __init__(self):  # PyRdsParser.__init__ opens a file; the rda helper must not
                pass

        previous = PyRdaReader._RdsProcessorHelper
        PyRdaReader._RdsProcessorHelper = _Helper  # the rda parser instantiates this module global per object
        try:
            parser = PyRdaReader.PyRdaParser(str(path))
            names = list(parser.get_object_names())
            if object_name is not None:
                if object_name not in names:
                    raise KeyError(f"{path}: no object named {object_name!r}; found {names}")
                return {object_name: parser.parse_object(object_name)}
            return {n: parser.parse_object(n) for n in names}
        finally:
            PyRdaReader._RdsProcessorHelper = previous
    return _Parser(str(path)).parse()


# ---------------------------------------------------------------- public API
def read_experiment(path: str | Path, object_name: str | None = None) -> RExperiment:
    """Parse a SpatialExperiment / SingleCellExperiment / SummarizedExperiment from .rds or .rda/.RData."""
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
    if cls not in SUPPORTED_CLASSES:
        raise ValueError(f"{path}: expected a SpatialExperiment / SingleCellExperiment, got {cls}")
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


SUPPORTED_CLASSES = {"SpatialExperiment", "SingleCellExperiment", "SummarizedExperiment", "RangedSummarizedExperiment"}
