"""Output schema: manifest.json written into every bundle.

Field names are camelCase on purpose so the JSON matches the TypeScript types in
app/src/data/manifest.ts one-to-one.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

FORMAT_VERSION = 1

Platform = Literal["visium", "visium_hd", "xenium", "merfish", "snrnaseq", "other"]
SampleKind = Literal["spatial", "embedding"]
LayoutMode = Literal["grid", "strip"]
BUILTIN_COLORMAPS = ["viridis", "magma", "inferno", "plasma", "cividis", "turbo", "greys"]


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


class PolygonInfo(_Model):
    path: str = "polygons"  # polygons.i16 + polygons.offsets.u32
    cells: int = 0  # cells that have a polygon
    vertices: int = 0
    scale: float = 0.1  # µm per int16 unit (deltas from the cell centroid)


class Sample(_Model):
    id: str
    name: str
    platform: Platform
    kind: SampleKind = "spatial"
    group: str | None = None
    nObs: int
    nGenes: int
    bbox: tuple[float, float, float, float]
    toDataset: list[float] = Field(default_factory=lambda: [1, 0, 0, 0, 1, 0, 0, 0, 1])
    pointRadius: float
    expr: ExprSpec = Field(default_factory=ExprSpec)
    hasF16: bool = False
    fields: list[str] = Field(default_factory=list)
    images: list[SampleImage] = Field(default_factory=list)
    outlines: list[str] = Field(default_factory=list)  # categorical field ids with outlines/<field>.json
    polygons: PolygonInfo | None = None
    idBlock: int = 65536
    suggestedGene: str | None = None  # most variable gene in this sample; the dataset's default when none is configured


class FeatureGroup(_Model):
    id: str
    name: str
    units: str | None = None
    count: int = 0


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

    def field_by_id(self, fid: str) -> CategoricalField | ContinuousField | None:
        for f in self.fields:
            if f.id == fid:
                return f
        return None
