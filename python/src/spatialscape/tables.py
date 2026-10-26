"""Long-format tables (cell boundaries, molecules) as Arrow, whatever the file: Parquet, or CSV / TSV, plain or
gzipped. Parquet is read a row group at a time, CSV a block at a time, so a table is never held whole."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

CSV_BLOCK = 64 << 20  # bytes of text per batch


def _kind(path: Path) -> str:
    name = path.name.lower()
    for ext in (".gz", ".bz2", ".zst", ".zstd", ".xz"):
        name = name.removesuffix(ext)
    if name.endswith((".csv", ".txt")):
        return "csv"
    if name.endswith(".tsv"):
        return "tsv"
    return "parquet"


def _csv_options(path: Path, columns: list[str] | None):
    kind = _kind(path)
    parse = pacsv.ParseOptions(delimiter="\t" if kind == "tsv" else ",")
    convert = pacsv.ConvertOptions(include_columns=columns) if columns else pacsv.ConvertOptions()
    return parse, convert


def table_columns(path: Path) -> list[str]:
    """The table's column names, from the Parquet schema or the CSV header line."""
    path = Path(path)
    if _kind(path) == "parquet":
        return list(pq.ParquetFile(path).schema_arrow.names)
    parse, _ = _csv_options(path, None)
    with pacsv.open_csv(path, read_options=pacsv.ReadOptions(block_size=1 << 16), parse_options=parse) as rd:
        return list(rd.schema.names)


def read_columns(path: Path, columns: list[str]) -> pa.Table:
    """The named columns of a whole table."""
    path = Path(path)
    if _kind(path) == "parquet":
        return pq.read_table(path, columns=columns)
    parse, convert = _csv_options(path, columns)
    return pacsv.read_csv(path, parse_options=parse, convert_options=convert)


def iter_batches(path: Path, columns: list[str]) -> Iterator[pa.Table]:
    """The named columns, one row group (Parquet) or one block of text (CSV) at a time."""
    path = Path(path)
    if _kind(path) == "parquet":
        pf = pq.ParquetFile(path)
        for i in range(pf.num_row_groups):
            yield pf.read_row_group(i, columns=columns)
        return
    parse, convert = _csv_options(path, columns)
    with pacsv.open_csv(path, read_options=pacsv.ReadOptions(block_size=CSV_BLOCK), parse_options=parse, convert_options=convert) as rd:
        for batch in rd:
            yield pa.Table.from_batches([batch])
