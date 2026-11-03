"""Writes tiny_sdata_v3.zarr (run with spatialdata >= 0.5) or tiny_sdata_v2.zarr (spatialdata 0.3 on Python 3.12): a
SpatialData store with every element kind. Usage: python make_tiny_sdata.py <out.zarr>"""
import sys

import anndata as ad
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from spatialdata import SpatialData
from spatialdata.models import Image2DModel, Labels2DModel, PointsModel, ShapesModel, TableModel
from spatialdata.transformations import Identity, Scale

rng = np.random.default_rng(0)
out = sys.argv[1]
n = 40
cx = rng.uniform(5, 95, n)  # microns in "global"
cy = rng.uniform(5, 95, n)
# polygons: hexagon-ish cells of radius ~3 um
ang = np.linspace(0, 2 * np.pi, 7)[:-1]
polys = [shapely.Polygon(np.c_[x + 3 * np.cos(ang), y + 3 * np.sin(ang)]) for x, y in zip(cx, cy, strict=True)]
cells = gpd.GeoDataFrame({"geometry": polys}, index=pd.Index([f"cell_{i}" for i in range(n)]))
cells = ShapesModel.parse(cells, transformations={"global": Identity()})
# circles (Visium-like) with a radius, in a pixel frame scaled 0.5 um/px -> global
circ = gpd.GeoDataFrame({"geometry": [shapely.Point(x * 2, y * 2) for x, y in zip(cx, cy, strict=True)], "radius": [5.0] * n}, index=pd.Index([f"spot_{i}" for i in range(n)]))
circ = ShapesModel.parse(circ, transformations={"global": Scale([0.5, 0.5], axes=("x", "y"))})
# image: 3 x 200 x 200 px, 0.5 um/px
img = (rng.uniform(0, 255, (3, 200, 200))).astype(np.uint8)
img[0, :, :] = np.linspace(0, 255, 200)[None, :].astype(np.uint8)  # a gradient, so the placement is visible
image = Image2DModel.parse(img, dims=("c", "y", "x"), scale_factors=[2, 2], transformations={"global": Scale([0.5, 0.5], axes=("y", "x"))}, c_coords=["r", "g", "b"])
# labels: 200 x 200 px, same frame
lab = np.zeros((200, 200), dtype=np.int32)
for i, (x, y) in enumerate(zip(cx, cy, strict=True)):
    lab[int(y * 2) - 2 : int(y * 2) + 2, int(x * 2) - 2 : int(x * 2) + 2] = i + 1
labels = Labels2DModel.parse(lab, dims=("y", "x"), transformations={"global": Scale([0.5, 0.5], axes=("y", "x"))})
# points: 600 molecules, 5 genes, assigned to a cell or not
m = 600
genes = np.array(["GeneA", "GeneB", "GeneC", "GeneD", "GeneE"])
owner = rng.integers(-1, n, m)
px = np.where(owner >= 0, cx[np.clip(owner, 0, n - 1)] + rng.normal(0, 1.5, m), rng.uniform(0, 100, m))
py = np.where(owner >= 0, cy[np.clip(owner, 0, n - 1)] + rng.normal(0, 1.5, m), rng.uniform(0, 100, m))
pts = pd.DataFrame({"x": px, "y": py, "feature_name": pd.Categorical(genes[rng.integers(0, 5, m)]), "cell_id": np.where(owner >= 0, np.array([f"cell_{i}" for i in range(n)])[np.clip(owner, 0, n - 1)], "UNASSIGNED")})
points = PointsModel.parse(pts, coordinates={"x": "x", "y": "y"}, feature_key="feature_name", instance_key="cell_id", transformations={"global": Identity()})
# table annotating the polygons: counts, obs with region/instance keys, NO obsm spatial
X = rng.poisson(1.0, (n, 5)).astype(np.float32)
obs = pd.DataFrame({"region": pd.Categorical(["cells"] * n), "cell_id": [f"cell_{i}" for i in range(n)], "cluster": pd.Categorical(rng.choice(["A", "B", "C"], n)), "area": rng.uniform(20, 40, n)}, index=pd.Index([f"cell_{i}" for i in range(n)]))
table = ad.AnnData(X=X, obs=obs, var=pd.DataFrame(index=pd.Index(genes)))
table = TableModel.parse(table, region="cells", region_key="region", instance_key="cell_id")
# a second table annotating the circles, with obsm spatial
obs2 = pd.DataFrame({"region": pd.Categorical(["spots"] * n), "spot_id": [f"spot_{i}" for i in range(n)], "domain": pd.Categorical(rng.choice(["L1", "L2"], n))}, index=pd.Index([f"spot_{i}" for i in range(n)]))
t2 = ad.AnnData(X=X.copy(), obs=obs2, var=pd.DataFrame(index=pd.Index(genes)), obsm={"spatial": np.c_[cx * 2, cy * 2]})
t2 = TableModel.parse(t2, region="spots", region_key="region", instance_key="spot_id")
# a third table annotating the labels (instance = label number)
obs3 = pd.DataFrame({"region": pd.Categorical(["seg"] * n), "label": np.arange(1, n + 1), "cluster": obs["cluster"].to_numpy()}, index=pd.Index([f"lab_{i}" for i in range(n)]))
t3 = ad.AnnData(X=X.copy(), obs=obs3, var=pd.DataFrame(index=pd.Index(genes)))
t3 = TableModel.parse(t3, region="seg", region_key="region", instance_key="label")
sdata = SpatialData(images={"he": image}, labels={"seg": labels}, shapes={"cells": cells, "spots": circ}, points={"transcripts": points}, tables={"table": table, "spots_table": t2, "labels_table": t3})
sdata.write(out, overwrite=True)
print(sdata)
