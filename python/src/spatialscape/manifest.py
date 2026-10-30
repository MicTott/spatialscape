"""Output schema: manifest.json written into every bundle.

Field names are camelCase on purpose so the JSON matches the TypeScript types in
app/src/data/manifest.ts one-to-one.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION = 1

Platform = Literal["visium", "visium_hd", "xenium", "merfish", "snrnaseq", "other"]
SampleKind = Literal["spatial", "embedding"]
LayoutMode = Literal["grid", "strip"]
BUILTIN_COLORMAPS = ["viridis", "magma", "inferno", "plasma", "cividis", "turbo", "greys", "rdbu"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vocabulary(_Model):
    categories: list[str]
    colors: list[str]
    aliases: dict[str, str] = Field(default_factory=dict)


class CategoricalField(_Model):
    id: str
    name: str
    type: Literal["categorical"] = "categorical"
    vocabulary: str
    description: str | None = None


class ContinuousField(_Model):
    id: str
    name: str
    type: Literal["continuous"] = "continuous"
    range: tuple[float, float] | None = None
    colormap: str | None = None
    description: str | None = None


ObsField = Annotated[CategoricalField | ContinuousField, Field(discriminator="type")]


class ColorSpec(_Model):
    kind: Literal["gene", "field"]
    gene: str | None = None
    field: str | None = None


class Layout(_Model):
    mode: LayoutMode = "grid"
    gutterFraction: float = 0.1
    order: list[str] = Field(default_factory=list)
    columns: int | None = None  # grid: a fixed number of columns


class ImageChannel(_Model):
    name: str
    color: str
    window: tuple[float, float]


class SampleImage(_Model):
    id: str
    name: str
    path: str
    kind: Literal["rgb", "multichannel"] = "rgb"
    pixelSize: float
    translate: tuple[float, float] = (0.0, 0.0)
    size: tuple[int, int]  # level-0 (height, width) in pixels
    channels: list[ImageChannel] | None = None
    defaultOpacity: float = 1.0


class ExprSpec(_Model):
    kind: Literal["u8", "csc"] = "u8"
    sharded: bool = True
    shardGenes: int = 512
    normalized: Literal["lognorm", "log1p_cp10k"] | None = None  # as stored by the source, or log1p(CP10k) applied by the build


class PolygonInfo(_Model):
    """Whole-sample polygons of bundles built before cell shapes were tiled (read by the viewer, never written)."""

    path: str = "polygons"  # polygons.i16 + polygons.offsets.u32
    cells: int = 0  # cells that have a polygon
    vertices: int = 0
    scale: float = 0.1  # µm per int16 unit (deltas from the cell centroid)


class ShapesInfo(_Model):
    """Cell boundary shapes in spatial tiles: shapes.json (the index) plus shapes.bin or shapes/<ix>_<iy>.bin."""

    path: str = "shapes"
    cells: int = 0  # cells that have a shape
    vertices: int = 0
    tile: int = 0  # tile size, um
    tiles: int = 0  # non-empty tiles
    bytes: int = 0  # compressed size of all tiles
    medianArea: float | None = None  # um2


class SegmentationInfo(ShapesInfo):
    """Another boundary set of the section, at segmentations/<id>/shapes.*; its rings are numbered, not tied to cells."""

    id: str = ""
    name: str = ""


class MoleculesInfo(_Model):
    """Individual molecules in spatial tiles: molecules.json (the index, with the gene names) plus molecules.bin
    or molecules/<ix>_<iy>.bin."""

    path: str = "molecules"
    count: int = 0
    genes: int = 0
    tile: int = 0  # tile size, um
    tiles: int = 0
    bytes: int = 0


class TrackSet(_Model):
    field: str
    categories: dict[str, str]  # category label -> bigWig path relative to the sample folder


class TracksInfo(_Model):
    """Genome tracks of an ATAC sample (see tracks.py): bigWigs of insertions per million per category."""

    genome: str
    bin: int
    all: str | None = None  # bigWig of every cell: built from fragments, or given with bigwigs
    units: str = "insertions per million"  # what the tracks measure, for the panel's scale
    by: list[TrackSet] = Field(default_factory=list)
    peaks: str | None = None  # BED of the sample's peak features
    genes: str | None = None  # folder of gene models: index.json (names per chromosome) + <chrom>.json (see genes.py)
    links: str | None = None  # BEDPE of peak-gene links
    chromSizes: str = "tracks/chrom.sizes"


class MetaKey(_Model):
    """A sample metadata key (condition, subject, ...): display name and the order of its levels."""

    id: str
    name: str
    levels: list[str] = Field(default_factory=list)


class Sample(_Model):
    id: str
    name: str
    platform: Platform
    kind: SampleKind = "spatial"
    group: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)  # sample-level metadata; keys are declared in Manifest.meta
    nObs: int
    nGenes: int
    bbox: tuple[float, float, float, float]
    toDataset: list[float] = Field(default_factory=lambda: [1, 0, 0, 0, 1, 0, 0, 0, 1])
    pointRadius: float
    expr: ExprSpec = Field(default_factory=ExprSpec)
    hasF16: bool = False
    fields: list[str] = Field(default_factory=list)
    images: list[SampleImage] = Field(default_factory=list)
    polygons: PolygonInfo | None = None  # legacy, see PolygonInfo
    shapes: ShapesInfo | None = None
    molecules: MoleculesInfo | None = None
    segmentations: list[SegmentationInfo] = Field(default_factory=list)
    idBlock: int = 65536
    suggestedGene: str | None = None  # most variable gene in this sample; the dataset's default when none is configured
    tracks: TracksInfo | None = None  # genome tracks (ATAC samples)

    @model_validator(mode="before")
    @classmethod
    def _drop_outlines(cls, data):
        """Bundles built before 0.5.1 listed traced annotation boundaries here; the key is ignored and the folders go on the next build."""
        if isinstance(data, dict) and "outlines" in data:
            data = {k: v for k, v in data.items() if k != "outlines"}
        return data


class FeatureGroup(_Model):
    id: str
    name: str
    units: str | None = None
    count: int = 0


class PopulationInfo(_Model):
    field: str
    value: str


class FacetInfo(_Model):
    column: str  # the results column whose levels the comparison is split by ("{level}" when one file per level)
    field: str | None = None  # the categorical field whose categories the levels are, when they match one


class LevelInfo(_Model):
    """One level of a comparison: a cluster's markers, one cell type's contrast; `levels/<id>/` under the comparison."""

    id: str  # folder name
    name: str  # the level's label in the table ("all" for a comparison without a facet)
    path: str  # levels/<id>, relative to the comparison
    nGenes: int
    nSignificant: int  # padj (or p) below 0.05
    nUnmatched: int
    nReplicates: int = 0
    hasPseudobulk: bool = False
    population: PopulationInfo | None = None  # the level as a category of the facet field, for the map filter


class ComparisonInfo(_Model):
    """A differential expression result stored under comparisons/<id>/ (see comparisons.py for the files)."""

    id: str
    kind: Literal["contrast", "markers"] = "contrast"
    name: str
    description: str | None = None
    path: str  # comparisons/<id>, relative to the bundle
    groups: list[str]  # pane and plotting order; the contrast is the last against the first
    contrast: str | None = None  # "<last group> vs <first group>": the direction a positive effect means
    effect: str = "log2FC"  # what the effect column measures: log2FC, or the column's name (estimate, beta, ...)
    units: str | None = None  # axis label of the replicate values
    population: PopulationInfo | None = None
    split: str | None = None  # sample meta key whose levels are the groups
    link: str | None = None  # sample meta key that holds the replicate ids
    facet: FacetInfo | None = None
    levels: list[LevelInfo] = Field(default_factory=list)  # one for a plain comparison, one per facet level otherwise
    nGenes: int  # rows over every level
    nReplicates: int  # distinct replicate ids over every level
    nUnmatched: int  # genes of the table that no sample measures
    hasEffect: bool = True  # false for a ranked list (cluster, gene) without statistics
    hasP: bool = True
    hasPadj: bool = True
    hasMean: bool = False
    hasPct: bool = False  # pct_in / pct_out (Seurat pct.1 / pct.2, scanpy pct_nz_group / pct_nz_reference)
    hasScore: bool = False
    hasPseudobulk: bool = False
    nMatrixGenes: int = 0  # distinct genes over every level: the rows of matrix.zarr


class Manifest(_Model):
    formatVersion: Literal[1] = FORMAT_VERSION
    id: str
    name: str
    description: str | None = None
    defaultGene: str | None = None
    defaultColor: ColorSpec
    layout: Layout = Field(default_factory=Layout)
    colormaps: list[str] = Field(default_factory=lambda: list(BUILTIN_COLORMAPS))
    vocabularies: dict[str, Vocabulary] = Field(default_factory=dict)
    fields: list[ObsField] = Field(default_factory=list)
    featureGroups: list[FeatureGroup] = Field(default_factory=list)
    samples: list[Sample] = Field(default_factory=list)
    thumbnailSample: str | None = None  # sample drawn on the dataset thumbnail (default: first spatial sample in layout order)
    meta: list[MetaKey] = Field(default_factory=list)  # the sample metadata keys the viewer can split the canvas by
    comparisons: list[ComparisonInfo] = Field(default_factory=list)

    def field_by_id(self, fid: str) -> CategoricalField | ContinuousField | None:
        for f in self.fields:
            if f.id == fid:
                return f
        return None
