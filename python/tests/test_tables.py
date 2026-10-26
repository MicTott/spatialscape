"""Boundary and molecule tables in the formats other platforms write: CSV / TSV, gzipped or not, numeric cell ids,
compartment labels. The Parquet path and the CSV path must agree to the byte."""
import gzip

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pytest

from spatialscape import molecules as M
from spatialscape.polygons import read_polygon_table
from spatialscape.synthetic import make_synthetic
from spatialscape.tables import iter_batches, read_columns, table_columns


def _csv_copy(parquet, out, *, rename=None, sep=","):
    t = pq.read_table(parquet)
    if rename:
        t = t.rename_columns([rename.get(c, c) for c in t.column_names])
    pacsv.write_csv(t, out, write_options=pacsv.WriteOptions(delimiter=sep))
    return t


def test_csv_tsv_and_gzip_read_like_parquet(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=200, n_genes=6)
    pqt = tmp_path / "src" / "sampleA.polygons.parquet"
    csv = tmp_path / "b.csv"
    tsv = tmp_path / "b.tsv"
    _csv_copy(pqt, csv)
    _csv_copy(pqt, tsv, sep="\t")
    gz = tmp_path / "b.csv.gz"
    gz.write_bytes(gzip.compress(csv.read_bytes()))
    want = read_polygon_table(pqt, "cell_id", "vertex_x", "vertex_y")
    for p in (csv, tsv, gz):
        assert table_columns(p) == ["cell_id", "vertex_x", "vertex_y"]
        got = read_polygon_table(p, "cell_id", "vertex_x", "vertex_y")
        assert got[0].tolist() == want[0].tolist()
        assert np.allclose(got[1], want[1]) and np.allclose(got[2], want[2])
    # streaming gives the same rows in the same order
    streamed = pa.concat_tables(list(iter_batches(gz, ["vertex_x"])))
    assert streamed.column("vertex_x").to_pylist() == read_columns(pqt, ["vertex_x"]).column("vertex_x").to_pylist()


def test_missing_boundary_column_names_the_columns(tmp_path):
    make_synthetic(tmp_path / "src", n_cells=50, n_genes=4)
    with pytest.raises(KeyError, match="'cellID' not found; columns are"):
        read_polygon_table(tmp_path / "src" / "sampleA.polygons.parquet", "cellID", "vertex_x", "vertex_y")


def test_cosmx_style_molecule_csv(tmp_path):
    """NanoString columns: target, x_global_px, y_global_px, integer cell_ID (0 = no cell), CellComp labels,
    no quality column, NegPrb / SystemControl controls."""
    rng = np.random.default_rng(1)
    n = 4000
    genes = np.array(["SNAP25", "GAD1", "PENK", "NegPrb3", "SystemControl12"])
    target = genes[rng.integers(0, len(genes), n)]
    cell = rng.integers(0, 30, n)  # 0 means outside every cell
    comp = np.where(cell == 0, "0", rng.choice(["Nuclear", "Cytoplasm", "Membrane"], n))
    t = pa.table(
        {
            "fov": np.ones(n, dtype=np.int64),
            "cell_ID": cell,
            "x_global_px": rng.uniform(0, 4000, n),
            "y_global_px": rng.uniform(0, 3000, n),
            "target": target,
            "CellComp": comp,
        }
    )
    path = tmp_path / "Run1_tx_file.csv.gz"
    with gzip.open(path, "wb") as fh:
        pacsv.write_csv(t, fh)
    cols = {"feature": "target", "x": "x_global_px", "y": "y_global_px", "qv": "", "cell": "cell_ID", "nucleus": "CellComp"}
    logs: list[str] = []
    st = M.write_molecules(tmp_path / "out", path, to_frame=lambda a: a * 0.12, columns=cols, log=logs.append)
    controls = int(np.isin(target, ["NegPrb3", "SystemControl12"]).sum())
    assert st.read == n and st.low_quality == 0 and st.controls == controls and st.count == n - controls and st.genes == 3
    names, _gene, xy, flags = M.read_molecules(tmp_path / "out")
    assert names == ["GAD1", "PENK", "SNAP25"]
    keep = ~np.isin(target, ["NegPrb3", "SystemControl12"])
    assert (flags & 1).sum() == int((cell[keep] > 0).sum())  # assigned = cell id above 0
    assert ((flags & 2) > 0).sum() == int((comp[keep] == "Nuclear").sum())
    assert xy.max() < 4000 * 0.12 + 1  # the frame map (px -> um) was applied


def test_merscope_style_molecule_csv_without_cells(tmp_path):
    """Vizgen columns: gene, global_x, global_y, cell_id -1 for no cell, Blank-<n> controls, no quality column."""
    rng = np.random.default_rng(2)
    n = 3000
    gene = rng.choice(["Blank-4", "SST", "VIP"], n)
    cell = np.where(rng.random(n) < 0.3, -1, rng.integers(1, 20, n))
    t = pa.table({"barcode_id": np.arange(n), "global_x": rng.uniform(0, 500, n), "global_y": rng.uniform(0, 500, n), "gene": gene, "cell_id": cell})
    path = tmp_path / "detected_transcripts.csv"
    pacsv.write_csv(t, path)
    st = M.write_molecules(tmp_path / "out", path, to_frame=lambda a: a, columns={"feature": "gene", "x": "global_x", "y": "global_y", "qv": "", "cell": "cell_id", "nucleus": ""})
    assert st.controls == int((gene == "Blank-4").sum()) and st.genes == 2
    _, _, _, flags = M.read_molecules(tmp_path / "out")
    assert (flags & 1).sum() == int((cell[gene != "Blank-4"] > 0).sum()) and not ((flags & 2) > 0).any()
