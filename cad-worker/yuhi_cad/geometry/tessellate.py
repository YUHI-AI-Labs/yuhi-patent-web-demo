"""Tessellation shared by the viewer payload and the local renders.

One triangulation per component, computed once and reused so the 3D view in the
app and the PNG renders always show the same geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_LINEAR_DEFLECTION = 0.35
DEFAULT_ANGULAR_DEFLECTION = 0.35


@dataclass
class ComponentMesh:
    id: str
    name: str | None
    color: str | None
    positions: list[float] = field(default_factory=list)  # xyz triples
    indices: list[int] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


def tessellate(
    shape: Any,
    component_id: str,
    name: str | None,
    color: str | None,
    linear: float = DEFAULT_LINEAR_DEFLECTION,
    angular: float = DEFAULT_ANGULAR_DEFLECTION,
) -> ComponentMesh:
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, linear, False, angular, True)
    mesh = ComponentMesh(id=component_id, name=name, color=color)

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            explorer.Next()
            continue

        transformation = location.Transformation()
        offset = len(mesh.positions) // 3
        for node_index in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(node_index).Transformed(transformation)
            mesh.positions.extend((round(point.X(), 4), round(point.Y(), 4), round(point.Z(), 4)))

        reversed_face = face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
        for triangle_index in range(1, triangulation.NbTriangles() + 1):
            a, b, c = triangulation.Triangle(triangle_index).Get()
            if reversed_face:
                a, c = c, a
            mesh.indices.extend((offset + a - 1, offset + b - 1, offset + c - 1))

        explorer.Next()

    return mesh


def bounds(meshes: list[ComponentMesh]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for mesh in meshes:
        for i in range(0, len(mesh.positions), 3):
            for axis in range(3):
                value = mesh.positions[i + axis]
                low[axis] = min(low[axis], value)
                high[axis] = max(high[axis], value)
    if low[0] == float("inf"):
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (low[0], low[1], low[2]), (high[0], high[1], high[2])


def to_viewer_payload(meshes: list[ComponentMesh], units: str) -> dict[str, Any]:
    """Compact payload for the React viewer. Stays inside the app data directory."""
    low, high = bounds(meshes)
    return {
        "schema_version": "1",
        "units": units,
        "bounds": {"min": list(low), "max": list(high)},
        "components": [
            {
                "id": mesh.id,
                "name": mesh.name,
                "color": mesh.color,
                "positions": mesh.positions,
                "indices": mesh.indices,
                "triangles": mesh.triangle_count,
            }
            for mesh in meshes
        ],
    }
