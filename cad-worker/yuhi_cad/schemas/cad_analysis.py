"""Versioned CADAnalysis contract. Mirrors packages/shared/src/schemas/cad-analysis.ts.

Deterministic facts only. Anything a model inferred belongs to the AI layer with
source="ai"; this worker never emits an assertion it did not measure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .. import SCHEMA_VERSION, __version__

SemanticLevel = Literal["FULL", "PLANAR", "MESH_ONLY", "IMAGE"]
CameraName = Literal[
    "front", "rear", "left", "right", "top", "bottom", "isometric_1", "isometric_2"
]


@dataclass
class BoundingBox:
    min: tuple[float, float, float]
    max: tuple[float, float, float]

    def size(self) -> tuple[float, float, float]:
        return tuple(self.max[i] - self.min[i] for i in range(3))  # type: ignore[return-value]

    def center(self) -> tuple[float, float, float]:
        return tuple((self.max[i] + self.min[i]) / 2 for i in range(3))  # type: ignore[return-value]


@dataclass
class CadSource:
    filename: str
    format: Literal["STEP", "DXF", "STL", "IMAGE", "PDF"]
    sha256: str
    size_bytes: int
    semantic_level: SemanticLevel


@dataclass
class CadModel:
    units: Literal["mm", "cm", "m", "in", "unknown"]
    bounding_box: BoundingBox | None
    volume: float | None
    surface_area: float | None
    solid_count: int = 0
    shell_count: int = 0
    face_count: int = 0
    edge_count: int = 0
    vertex_count: int = 0


@dataclass
class AssemblyNode:
    id: str
    parent_id: str | None
    name: str | None
    transform: list[float] | None
    children: list[str] = field(default_factory=list)


@dataclass
class CadComponent:
    id: str
    assembly_node_id: str | None = None
    original_name: str | None = None
    normalized_name: str | None = None
    bounding_box: BoundingBox | None = None
    volume: float | None = None
    surface_area: float | None = None
    material: str | None = None
    color: str | None = None
    layer: str | None = None
    face_count: int = 0
    solid_count: int = 0


@dataclass
class GeometryFeature:
    id: str
    component_id: str
    type: str
    metrics: dict[str, Any]
    confidence: float
    method: str


@dataclass
class Relationship:
    id: str
    type: str
    source_component: str
    target_component: str
    confidence: float
    evidence: str
    method: str


@dataclass
class Render:
    camera: CameraName
    path: str
    width: int
    height: int


@dataclass
class CadWarning:
    code: str
    message_ja: str
    severity: Literal["INFO", "WARN", "ERROR"] = "WARN"


@dataclass
class CadAnalysis:
    job_id: str
    generated_at: str
    source: CadSource
    model: CadModel
    schema_version: str = SCHEMA_VERSION
    worker_version: str = __version__
    assemblies: list[AssemblyNode] = field(default_factory=list)
    components: list[CadComponent] = field(default_factory=list)
    geometry_features: list[GeometryFeature] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    renders: list[Render] = field(default_factory=list)
    warnings: list[CadWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


REQUIRED_KEYS = (
    "schema_version",
    "job_id",
    "generated_at",
    "worker_version",
    "source",
    "model",
    "assemblies",
    "components",
    "geometry_features",
    "relationships",
    "renders",
    "warnings",
)


def validate_analysis(payload: dict[str, Any]) -> None:
    """Fails loudly rather than emitting unversioned or partial JSON."""
    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        raise ValueError(f"CADAnalysis missing keys: {', '.join(missing)}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {payload['schema_version']}")
    for rel in payload["relationships"]:
        if not rel.get("evidence"):
            raise ValueError(f"relationship {rel.get('id')} has no evidence")
        if not 0.0 <= float(rel["confidence"]) <= 1.0:
            raise ValueError(f"relationship {rel.get('id')} confidence out of range")
