"""Coordinate frames: source units -> microns, flips/rotations shared by points and images."""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from .config import SampleSpec
from .readers import SampleInput

VISIUM_SPOT_DIAMETER_UM = 55.0
VISIUM_SPOT_SPACING_UM = 100.0


def _scalar(v: Any) -> float:
    return float(np.asarray(v).ravel()[0])


def _from_scalefactors(sf: dict[str, Any]) -> float | None:
    if "microns_per_pixel" in sf:
        return float(sf["microns_per_pixel"])
    if "spot_diameter_fullres" in sf:
        return VISIUM_SPOT_DIAMETER_UM / float(sf["spot_diameter_fullres"])
    return None


def microns_per_unit(spec: SampleSpec, sinput: SampleInput) -> float:
    """Microns per coordinate unit of `sinput.coords`."""
    m = spec.microns
    if m.already_microns:
        return 1.0
    if m.microns_per_unit is not None:
        return float(m.microns_per_unit)
    if m.spot_diameter_fullres is not None:
        return VISIUM_SPOT_DIAMETER_UM / float(m.spot_diameter_fullres)
    if m.spot_spacing is not None:
        return VISIUM_SPOT_SPACING_UM / float(m.spot_spacing)
    if m.scalefactors_json is not None:
        with open(m.scalefactors_json) as fh:
            v = _from_scalefactors(json.load(fh))
        if v is None:
            raise ValueError(f"{m.scalefactors_json}: no microns_per_pixel / spot_diameter_fullres")
        return v
    # auto
    if spec.kind == "embedding":
        ext = np.ptp(sinput.coords, axis=0).max()
        return float(spec.extent / ext) if ext > 0 else 1.0
    if spec.platform in ("xenium", "merfish"):
        return 1.0
    uns = sinput.uns
    if "spot_nn_spacing_level0_px" in uns:
        return VISIUM_SPOT_SPACING_UM / _scalar(uns["spot_nn_spacing_level0_px"])
    spatial = uns.get("spatial")
    if isinstance(spatial, dict):
        for lib in spatial.values():
            if isinstance(lib, dict) and isinstance(lib.get("scalefactors"), dict):
                v = _from_scalefactors(lib["scalefactors"])
                if v is not None:
                    return v
    raise ValueError(
        f"sample {spec.id}: cannot infer microns per coordinate unit; set `microns:` "
        "(already_microns | microns_per_unit | spot_diameter_fullres | spot_spacing | scalefactors_json)"
    )


def default_point_radius(spec: SampleSpec, xy_um: np.ndarray) -> float:
    if spec.point_radius is not None:
        return float(spec.point_radius)
    if spec.kind == "embedding":
        return float(0.004 * np.ptp(xy_um, axis=0).max())
    if spec.platform == "visium":
        return VISIUM_SPOT_DIAMETER_UM / 2
    if spec.platform == "visium_hd":
        return max(1.0, 0.5 * _median_nn_distance(xy_um))
    return 5.0


def _median_nn_distance(xy: np.ndarray, sample: int = 2000, seed: int = 0) -> float:
    from scipy.spatial import cKDTree

    rng = np.random.default_rng(seed)
    idx = rng.choice(len(xy), size=min(sample, len(xy)), replace=False)
    tree = cKDTree(xy)
    d, _ = tree.query(xy[idx], k=2)
    return float(np.median(d[:, 1]))


def transform_points(xy: np.ndarray, width: float, height: float, flip: str, rotate: int) -> np.ndarray:
    """Apply flip then rotate in a frame of size (width, height). Mirrors transform_image."""
    x, y = xy[:, 0].copy(), xy[:, 1].copy()
    w, h = float(width), float(height)
    if flip == "x":
        x = w - x
    elif flip == "y":
        y = h - y
    if rotate == 90:  # counter-clockwise, like np.rot90(k=1) on a (y, x) image
        x, y = y, w - x
        w, h = h, w
    elif rotate == 180:
        x, y = w - x, h - y
    elif rotate == 270:
        x, y = h - y, x
        w, h = h, w
    return np.stack([x, y], axis=1)


def transform_image(img: np.ndarray, flip: str, rotate: int) -> np.ndarray:
    """img is (c, y, x). Same geometric operation as transform_points."""
    if flip == "x":
        img = img[:, :, ::-1]
    elif flip == "y":
        img = img[:, ::-1, :]
    k = {0: 0, 90: 1, 180: 2, 270: 3}[rotate]
    if k:
        img = np.rot90(img, k=k, axes=(1, 2))
    return np.ascontiguousarray(img)
