"""Read R's serialization format (.rds, and .rda / .RData) without R.

Why our own reader: the C++ one (rds2py) aborts on any closure inside an object, and Seurat records the functions it
was called with; the pure-Python one (rdata) builds one object per string, so an H&E raster of a few million colour
strings takes minutes and tens of GB. This reader streams the file once (gzip, bzip2, xz or plain; XDR format,
versions 2 and 3), keeps vectors as numpy arrays, decodes uniform string vectors in bulk, and walks past closures,
environments, promises, language objects and bytecode without building them. Slots named in `skip` are walked
past too, which is how a Seurat object's scaled data and graphs stay out of memory.

Every value comes back as a dict the readers in rds.py work on:
    {"type": "integer" | "double" | "boolean" | "string" | "complex" | "raw" | "vector" | "S4" | "null" |
             "symbol" | "unsupported" | "skipped",
     "class_name": the S4 class, or "<type>_vector" / "vector",
     "data": numpy array (numbers; strings as a `U` array when uniform) or a list (lists; strings),
     "attributes": {name: value}}
"""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import struct
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

R_NA_INT = -2147483648
UTF8_MASK = 1 << 3
LATIN1_MASK = 1 << 2

# SEXP types and the serialization-only pseudo types (R's serialize.c)
NILSXP, SYMSXP, LISTSXP, CLOSXP, ENVSXP, PROMSXP, LANGSXP, SPECIALSXP, BUILTINSXP, CHARSXP = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
LGLSXP, INTSXP, REALSXP, CPLXSXP, STRSXP, DOTSXP, VECSXP, EXPRSXP, BCODESXP = 10, 13, 14, 15, 16, 17, 19, 20, 21
EXTPTRSXP, WEAKREFSXP, RAWSXP, S4SXP = 22, 23, 24, 25
REFSXP, NILVALUE_SXP, GLOBALENV_SXP, UNBOUNDVALUE_SXP, MISSINGARG_SXP = 255, 254, 253, 252, 251
BASENAMESPACE_SXP, NAMESPACESXP, PACKAGESXP, PERSISTSXP = 250, 249, 248, 247
CLASSREFSXP, GENERICREFSXP, BCREPDEF, BCREPREF, EMPTYENV_SXP, BASEENV_SXP = 246, 245, 244, 243, 242, 241
ATTRLANGSXP, ATTRLISTSXP, ALTREP_SXP = 240, 239, 238

PAIRLIKE = (LISTSXP, LANGSXP, CLOSXP, PROMSXP, DOTSXP)
SKIP_PLACEHOLDER = {"type": "skipped"}
NULL = {"type": "null"}


class RdsError(ValueError):
    pass


def _open(path: Path) -> io.BufferedReader:
    with open(path, "rb") as fh:
        magic = fh.read(6)
    if magic[:2] == b"\x1f\x8b":
        return io.BufferedReader(gzip.open(path, "rb"), buffer_size=1 << 23)  # type: ignore[arg-type]
    if magic[:3] == b"BZh":
        return io.BufferedReader(bz2.open(path, "rb"), buffer_size=1 << 23)  # type: ignore[arg-type]
    if magic[:6] == b"\xfd7zXZ\x00":
        return io.BufferedReader(lzma.open(path, "rb"), buffer_size=1 << 23)  # type: ignore[arg-type]
    return open(path, "rb", buffering=1 << 23)


class Reader:
    def __init__(self, fh: io.BufferedReader, skip: Iterable[str] = ()):
        self.fh = fh
        self.skip = frozenset(skip)
        self.refs: list[Any] = []  # symbols, environments, namespaces, ... in order of first appearance
        self.discard = 0  # > 0 while walking something nobody needs
        self.pending = b""  # bytes read ahead of their use (a string vector guessed uniform that was not)
        self.path: list[str] = []  # slot / attribute names being read, for error messages

    # ------------------------------------------------------------ raw reads
    def read(self, n: int) -> bytes:
        if self.pending:
            head, self.pending = self.pending[:n], self.pending[n:]
            if len(head) == n:
                return head
            rest = self.fh.read(n - len(head))
            if len(rest) != n - len(head):
                raise RdsError(f"unexpected end of file ({len(head) + len(rest)} of {n} bytes)")
            return head + rest
        b = self.fh.read(n)
        if len(b) != n:
            raise RdsError(f"unexpected end of file ({len(b)} of {n} bytes)")
        return b

    def read_upto(self, n: int) -> bytes:
        """Up to n bytes (fewer at the end of the file)."""
        head, self.pending = self.pending[:n], self.pending[n:]
        return head if len(head) == n else head + self.fh.read(n - len(head))

    def i32(self) -> int:
        return struct.unpack(">i", self.read(4))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]

    def length(self) -> int:
        n = self.i32()
        if n == -1:  # a long vector: two more ints
            return (self.u32() << 32) + self.u32()
        return n

    # ------------------------------------------------------------ entry
    def header(self) -> tuple[int, bool]:
        """Reads the stream header; (format version, rda) where rda means the stream holds named objects."""
        magic = self.read(2)
        rda = False
        if magic in (b"RD", b"RB", b"RA"):
            rest = self.read(3)  # "X2\n" / "X3\n"
            if rest[:1] != b"X":
                raise RdsError("only XDR-format .rda files are supported (saved with ascii = FALSE)")
            rda = True
            magic = self.read(2)
        if magic != b"X\n":
            raise RdsError("not an XDR-serialized R object (ascii or native-binary serialization is not supported)")
        version = self.u32()
        self.u32()  # R version that wrote it
        self.u32()  # minimal R version to read it
        if version == 3:
            n = self.u32()
            self.read(n)  # native encoding name
        elif version != 2:
            raise RdsError(f"unsupported serialization version {version}")
        return version, rda

    # ------------------------------------------------------------ items
    def item(self) -> Any:
        return self.item_flags(self.u32())

    def item_flags(self, flags: int) -> Any:
        """An item whose flags word has already been read."""
        t = flags & 0xFF
        levels = flags >> 12
        has_attr = bool(flags & 0x200)
        has_tag = bool(flags & 0x400)

        if t in (NILVALUE_SXP, NILSXP):
            return NULL
        if t == REFSXP:
            idx = flags >> 8
            if idx == 0:
                idx = self.u32()
            return self.refs[idx - 1]
        if t in (EMPTYENV_SXP, BASEENV_SXP, GLOBALENV_SXP, UNBOUNDVALUE_SXP, MISSINGARG_SXP, BASENAMESPACE_SXP):
            return {"type": "unsupported", "class_name": "environment"}
        if t == PERSISTSXP:
            names = self.string_vec_plain()
            obj = {"type": "unsupported", "class_name": "persistent", "data": names}
            self.refs.append(obj)
            return obj
        if t in (NAMESPACESXP, PACKAGESXP):
            names = self.string_vec_plain()
            obj = {"type": "unsupported", "class_name": "namespace" if t == NAMESPACESXP else "package", "data": names}
            self.refs.append(obj)
            return obj
        if t == SYMSXP:
            name = self.charsxp()
            obj = NULL if name == "\x01NULL\x01" else {"type": "symbol", "data": [name]}  # an S4 slot holding NULL
            self.refs.append(obj)
            return obj
        if t == ENVSXP:
            obj = {"type": "unsupported", "class_name": "environment"}
            self.refs.append(obj)  # before its contents, which may refer back to it
            self.u32()  # locked
            self.discard += 1
            try:
                self.item()  # enclos
                self.item()  # frame
                self.item()  # hashtab
                self.item()  # attrib
            finally:
                self.discard -= 1
            return obj
        if t in PAIRLIKE:
            return self.pairlist(t, has_attr, has_tag)
        if t == ATTRLISTSXP:
            return self.pairlist(LISTSXP, True, has_tag)
        if t == ATTRLANGSXP:
            return self.pairlist(LANGSXP, True, has_tag)
        if t == EXTPTRSXP:
            obj = {"type": "unsupported", "class_name": "externalptr"}
            self.refs.append(obj)
            self.discard += 1
            try:
                self.item()  # prot
                self.item()  # tag
            finally:
                self.discard -= 1
            if has_attr:
                self.item()
            return obj
        if t == WEAKREFSXP:
            obj = {"type": "unsupported", "class_name": "weakref"}
            self.refs.append(obj)
            if has_attr:
                self.item()
            return obj
        if t in (SPECIALSXP, BUILTINSXP):
            n = self.i32()
            name = self.read(n).decode("latin-1")
            return {"type": "unsupported", "class_name": "builtin", "data": [name]}
        if t == CHARSXP:
            return {"type": "string", "class_name": "string_vector", "data": [self.charsxp_body(levels)], "attributes": {}}
        if t == BCODESXP:
            self.bytecode()
            obj: dict = {"type": "unsupported", "class_name": "bytecode"}
            if has_attr:
                self.item()
            return obj
        if t == ALTREP_SXP:
            return self.altrep()
        if t == S4SXP:
            attrs = self.attributes() if has_attr else {}
            cls = attrs.get("class", {}).get("data")
            cls_attrs = attrs.get("class", {}).get("attributes", {})
            pkg = cls_attrs.get("package", {}).get("data")
            return {
                "type": "S4", "class_name": str(cls[0]) if cls is not None and len(cls) else None,
                "package_name": str(pkg[0]) if pkg is not None and len(pkg) else None, "attributes": attrs,
            }

        # vectors
        if t == STRSXP:
            n = self.length()
            data = self.strings(n)
            obj = {"type": "string", "class_name": "string_vector", "data": data}
        elif t in (VECSXP, EXPRSXP):
            n = self.length()
            items = []
            for i in range(n):
                self.path.append(f"[{i}]")
                try:
                    items.append(self.item())
                finally:
                    self.path.pop()
            obj = {"type": "vector", "class_name": "vector", "data": items}
        elif t == LGLSXP:
            obj = {"type": "boolean", "class_name": "boolean_vector", "data": self.logicals(self.length())}
        elif t == INTSXP:
            obj = {"type": "integer", "class_name": "integer_vector", "data": self.numbers(self.length(), ">i4", np.int32)}
        elif t == REALSXP:
            obj = {"type": "double", "class_name": "double_vector", "data": self.numbers(self.length(), ">f8", np.float64)}
        elif t == CPLXSXP:
            obj = {"type": "complex", "class_name": "complex_vector", "data": self.numbers(self.length(), ">c16", np.complex128)}
        elif t == RAWSXP:
            n = self.length()
            obj = {"type": "raw", "class_name": "raw_vector", "data": self.read(n) if not self.discard else self.skip_bytes(n)}
        else:
            raise RdsError(f"unsupported SEXP type {t} at {'/'.join(self.path) or 'top'}")
        obj["attributes"] = self.attributes() if has_attr else {}
        if self.discard:
            return SKIP_PLACEHOLDER
        return obj

    # ------------------------------------------------------------ pieces
    def pairlist(self, t: int, has_attr: bool, has_tag: bool) -> Any:
        """A dotted pair chain. As attributes it is returned as a dict elsewhere; as data, a named list. For
        closures, promises and calls the pieces are walked and dropped."""
        if t != LISTSXP:
            self.discard += 1
            try:
                if has_attr:
                    self.item()
                if has_tag:
                    self.item()
                self.item()  # car (formals / value / function)
                self.item()  # cdr (body / expression / arguments)
            finally:
                self.discard -= 1
            return {"type": "unsupported", "class_name": {CLOSXP: "closure", PROMSXP: "promise", LANGSXP: "language", DOTSXP: "dots"}[t]}
        names: list[str | None] = []
        values: list[Any] = []
        attrs: dict = {}
        first = True
        while True:
            if first:
                a, g = has_attr, has_tag
                first = False
            else:
                flags = self.u32()
                tt = flags & 0xFF
                if tt in (NILVALUE_SXP, NILSXP):
                    break
                if tt == REFSXP:  # a shared tail, unusual
                    idx = flags >> 8
                    if idx == 0:
                        idx = self.u32()
                    tail = self.refs[idx - 1]
                    if isinstance(tail, dict) and tail.get("type") == "vector":
                        values.extend(tail["data"])
                        names.extend(tail.get("attributes", {}).get("names", {}).get("data", [None] * len(tail["data"])))
                    break
                if tt not in (LISTSXP, ATTRLISTSXP):  # a dotted pair: the tail is a plain value (an ALTREP state, for one)
                    values.append(self.item_flags(flags))
                    names.append(None)
                    break
                a, g = bool(flags & 0x200) or tt == ATTRLISTSXP, bool(flags & 0x400)
            node_attrs = self.attributes() if a else {}
            if not attrs:
                attrs = node_attrs
            tag = None
            if g:
                sym = self.item()
                tag = sym["data"][0] if isinstance(sym, dict) and sym.get("type") == "symbol" else None
            self.path.append(tag if tag is not None else f"({len(values)})")
            try:
                if tag is not None and tag in self.skip and not self.discard:
                    self.discard += 1
                    try:
                        self.item()
                    finally:
                        self.discard -= 1
                    values.append(SKIP_PLACEHOLDER)
                else:
                    values.append(self.item())
            finally:
                self.path.pop()
            names.append(tag)
        if self.discard:
            return SKIP_PLACEHOLDER
        out = {"type": "vector", "class_name": "vector", "data": values, "attributes": dict(attrs)}
        if any(n is not None for n in names):
            out["attributes"]["names"] = {"type": "string", "class_name": "string_vector", "data": [n or "" for n in names], "attributes": {}}
        return out

    def attributes(self) -> dict:
        """The attribute pairlist that follows an object -> {name: value}."""
        node = self.item()
        if node is NULL or node is SKIP_PLACEHOLDER or not isinstance(node, dict):
            return {}
        if node.get("type") != "vector":
            return {}
        names = node.get("attributes", {}).get("names", {}).get("data", [])
        return {str(n): v for n, v in zip(names, node["data"], strict=False) if n}

    def charsxp(self) -> str | None:
        flags = self.u32()
        if (flags & 0xFF) != CHARSXP:
            raise RdsError("expected a CHARSXP")
        return self.charsxp_body(flags >> 12)

    def charsxp_body(self, levels: int) -> str | None:
        n = self.i32()
        if n == -1:
            return None
        b = self.read(n)
        return b.decode("latin-1") if (levels & LATIN1_MASK and not levels & UTF8_MASK) else b.decode("utf-8", "replace")

    def string_vec_plain(self) -> list[str | None]:
        """InStringVec: used for namespace / package / persistent names."""
        if self.u32() != 0:
            raise RdsError("malformed string vector")
        n = self.i32()
        return [self.charsxp() for _ in range(n)]

    def strings(self, n: int) -> Any:
        """A STRSXP body. Vectors whose strings all have the same length and encoding (hex colours of a raster,
        barcodes) are read in one go and come back as a numpy `U` array; anything else as a list with None for NA."""
        if n == 0:
            return []
        if self.discard:
            for _ in range(n):
                flags = self.u32()
                m = self.i32()
                if m > 0:
                    self.skip_bytes(m)
            return []
        first_flags = self.u32()
        m = self.i32()
        if m < 0 or m > 64 or n < 64:
            first = None if m < 0 else self._decode(self.read(m), first_flags >> 12)
            out = [first]
            out.extend(self.charsxp() for _ in range(n - 1))
            return out
        first_bytes = self.read(m)
        stride = 8 + m
        buf = self.read_upto(stride * (n - 1))
        if len(buf) == stride * (n - 1):
            arr = np.frombuffer(buf, dtype=np.dtype([("flags", ">u4"), ("len", ">i4"), ("s", f"S{m}")]))
            if np.all(arr["flags"] == first_flags) and np.all(arr["len"] == m):
                s = np.concatenate([np.array([first_bytes], dtype=f"S{m}"), arr["s"]])
                try:
                    return s.astype(f"U{m}") if not (first_flags >> 12) & LATIN1_MASK else np.array([x.decode("latin-1") for x in s])
                except UnicodeDecodeError:
                    return [x.decode("utf-8", "replace") for x in s]
        # not uniform after all: parse the buffered bytes item by item, reading on from the stream when an item runs
        # past them, and hand back whatever is left over (it belongs to the next object)
        pos = 0
        total = len(buf)

        def take(k: int) -> bytes:
            nonlocal pos
            if pos + k <= total:
                piece = buf[pos : pos + k]
                pos += k
                return piece
            piece = buf[pos:]
            pos = total
            return piece + self.read(k - len(piece))

        out: list[str | None] = [self._decode(first_bytes, first_flags >> 12)]
        for _ in range(n - 1):
            flags, m2 = struct.unpack(">Ii", take(8))
            out.append(None if m2 < 0 else self._decode(take(m2), flags >> 12))
        if pos < total:
            self.pending = buf[pos:] + self.pending
        return out

    @staticmethod
    def _decode(b: bytes, levels: int) -> str:
        return b.decode("latin-1") if (levels & LATIN1_MASK and not levels & UTF8_MASK) else b.decode("utf-8", "replace")

    def numbers(self, n: int, dtype: str, native: Any) -> np.ndarray:
        size = np.dtype(dtype).itemsize
        if self.discard:
            self.skip_bytes(n * size)
            return np.zeros(0, dtype=native)
        return np.frombuffer(self.read(n * size), dtype=dtype).astype(native)

    def logicals(self, n: int) -> np.ndarray:
        raw = self.numbers(n, ">i4", np.int32)
        if self.discard:
            return raw
        na = raw == R_NA_INT
        if na.any():  # NA logicals as NaN among 0/1 (what the readers expect)
            out = raw.astype(np.float64)
            out[na] = np.nan
            return out
        return raw.astype(bool)

    def skip_bytes(self, n: int) -> bytes:
        if self.pending:
            head, self.pending = self.pending[:n], self.pending[n:]
            n -= len(head)
        while n > 0:
            chunk = self.fh.read(min(n, 1 << 24))
            if not chunk:
                raise RdsError("unexpected end of file")
            n -= len(chunk)
        return b""

    # ------------------------------------------------------------ ALTREP and bytecode
    def altrep(self) -> Any:
        info = self.item()
        state = self.item()
        attr = self.item()
        attrs: dict = {}
        if isinstance(attr, dict) and attr.get("type") == "vector":
            names = attr.get("attributes", {}).get("names", {}).get("data", [])
            attrs = {str(k): v for k, v in zip(names, attr["data"], strict=False) if k}
        cls = ""
        if isinstance(info, dict) and info.get("type") == "vector" and info["data"]:
            head = info["data"][0]
            cls = head["data"][0] if isinstance(head, dict) and head.get("type") == "symbol" else ""
        if self.discard:
            return SKIP_PLACEHOLDER
        if cls in ("compact_intseq", "compact_realseq"):
            n, start, step = (float(v) for v in state["data"][:3])
            arr = start + step * np.arange(int(n))
            if cls == "compact_intseq":
                return {"type": "integer", "class_name": "integer_vector", "data": arr.astype(np.int32), "attributes": attrs}
            return {"type": "double", "class_name": "double_vector", "data": arr.astype(np.float64), "attributes": attrs}
        if cls == "deferred_string":
            arg = state["data"][0] if isinstance(state, dict) and state.get("type") == "vector" else state
            vals = arg.get("data", []) if isinstance(arg, dict) else []
            strs = [None if (isinstance(v, (int, np.integer)) and int(v) == R_NA_INT) or (isinstance(v, float) and np.isnan(v)) else (str(int(v)) if float(v).is_integer() else repr(float(v))) for v in vals]
            return {"type": "string", "class_name": "string_vector", "data": strs, "attributes": attrs}
        if cls.startswith("wrap_"):
            inner = state["data"][0] if isinstance(state, dict) and state.get("type") == "vector" else state
            if isinstance(inner, dict):
                inner = dict(inner)
                inner["attributes"] = {**inner.get("attributes", {}), **attrs}
            return inner
        raise RdsError(f"unsupported ALTREP class {cls!r}")

    def bytecode(self) -> None:
        reps = self.i32()
        self._bc_reps: list[Any] = [None] * max(reps, 0)
        self.discard += 1
        try:
            self.bytecode1()
        finally:
            self.discard -= 1

    def bytecode1(self) -> None:
        self.item()  # the code (an integer vector)
        n = self.i32()
        for _ in range(n):
            t = self.i32()
            if t == BCODESXP:
                self.bytecode1()
            elif t in (LANGSXP, LISTSXP, BCREPDEF, BCREPREF, ATTRLANGSXP, ATTRLISTSXP):
                self.bc_lang(t)
            else:
                self.item()

    def bc_lang(self, t: int) -> None:
        if t == BCREPREF:
            self.i32()
            return
        if t in (BCREPDEF, LANGSXP, LISTSXP, ATTRLANGSXP, ATTRLISTSXP):
            if t == BCREPDEF:
                self.i32()  # position
                t = self.i32()
            if t in (ATTRLANGSXP, ATTRLISTSXP):
                self.item()  # attributes
            self.item()  # tag
            self.bc_lang(self.i32())  # car
            self.bc_lang(self.i32())  # cdr
            return
        self.item()


def read_rds(path: Path | str, *, skip: Iterable[str] = ()) -> Any:
    """One object from an .rds file."""
    with _open(Path(path)) as fh:
        r = Reader(fh, skip)
        _, rda = r.header()
        if rda:
            raise RdsError(f"{path}: an .rda file; use read_rda")
        try:
            return r.item()
        except (RdsError, struct.error) as e:
            raise RdsError(f"{path}: {e} (while reading {'/'.join(r.path) or 'the top-level object'})") from None


def read_rda(path: Path | str, *, skip: Iterable[str] = (), only: str | None = None) -> dict[str, Any]:
    """The named objects of an .rda / .RData file -> {name: object}. With `only`, the others are walked past."""
    with _open(Path(path)) as fh:
        r = Reader(fh, skip)
        _, rda = r.header()
        if not rda:
            raise RdsError(f"{path}: an .rds file; use read_rds")
        out: dict[str, Any] = {}
        node_flags = r.u32()
        while (node_flags & 0xFF) in (LISTSXP, ATTRLISTSXP):
            has_attr = bool(node_flags & 0x200) or (node_flags & 0xFF) == ATTRLISTSXP
            has_tag = bool(node_flags & 0x400)
            if has_attr:
                r.attributes()
            name = None
            if has_tag:
                sym = r.item()
                name = sym["data"][0] if isinstance(sym, dict) and sym.get("type") == "symbol" else None
            if only is not None and name != only:
                r.discard += 1
                try:
                    r.item()
                finally:
                    r.discard -= 1
            else:
                out[str(name)] = r.item()
            node_flags = r.u32()
        return out
