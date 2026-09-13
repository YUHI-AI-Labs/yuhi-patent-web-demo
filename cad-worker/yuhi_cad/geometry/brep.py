"""Deterministic B-Rep measurements and feature classification.

Every value here comes from OpenCascade. Confidence for a measured quantity is
1.0; confidence below 1.0 marks a classification that involves a threshold and
could be wrong, and each one records the method that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas.cad_analysis import BoundingBox, GeometryFeature


@dataclass
class CylinderInfo:
    radius: float
    axis_dir: tuple[float, float, float]
    axis_loc: tuple[float, float, float]
    internal: bool
    area: float


@dataclass
class ShapeMeasurements:
    volume: float | None
    surface_area: float | None
    bounding_box: BoundingBox | None
    solid_count: int
    shell_count: int
    face_count: int
    edge_count: int
    vertex_count: int
    face_types: dict[str, int] = field(default_factory=dict)
    cylinders: list[CylinderInfo] = field(default_factory=list)


def _explorer(shape: Any, kind: str) -> Any:
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    return TopExp_Explorer(shape, getattr(TopAbs_ShapeEnum, f"TopAbs_{kind}"))


def _count(shape: Any, kind: str) -> int:
    explorer = _explorer(shape, kind)
    seen = 0
    while explorer.More():
        seen += 1
        explorer.Next()
    return seen


def measure(shape: Any) -> ShapeMeasurements:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    volume_props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume_props)
    surface_props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, surface_props)

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    bounding_box: BoundingBox | None = None
    if not box.IsVoid():
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        bounding_box = BoundingBox(min=(xmin, ymin, zmin), max=(xmax, ymax, zmax))

    face_types, cylinders = classify_faces(shape)

    return ShapeMeasurements(
        volume=volume_props.Mass() or None,
        surface_area=surface_props.Mass() or None,
        bounding_box=bounding_box,
        solid_count=_count(shape, "SOLID"),
        shell_count=_count(shape, "SHELL"),
        face_count=_count(shape, "FACE"),
        edge_count=_count(shape, "EDGE"),
        vertex_count=_count(shape, "VERTEX"),
        face_types=face_types,
        cylinders=cylinders,
    )


def classify_faces(shape: Any) -> tuple[dict[str, int], list[CylinderInfo]]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_Orientation
    from OCP.TopoDS import TopoDS

    labels = {
        GeomAbs_SurfaceType.GeomAbs_Plane: "PLANAR_FACE",
        GeomAbs_SurfaceType.GeomAbs_Cylinder: "CYLINDRICAL_FACE",
        GeomAbs_SurfaceType.GeomAbs_Cone: "CONICAL_FACE",
        GeomAbs_SurfaceType.GeomAbs_Sphere: "SPHERICAL_FACE",
        GeomAbs_SurfaceType.GeomAbs_Torus: "TOROIDAL_FACE",
        GeomAbs_SurfaceType.GeomAbs_BSplineSurface: "FREEFORM_FACE",
    }

    counts: dict[str, int] = {}
    cylinders: list[CylinderInfo] = []

    explorer = _explorer(shape, "FACE")
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        surface_type = adaptor.GetType()
        label = labels.get(surface_type, "OTHER_FACE")
        counts[label] = counts.get(label, 0) + 1

        if label == "CYLINDRICAL_FACE":
            cylinder = adaptor.Cylinder()
            axis = cylinder.Axis()
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            cylinders.append(
                CylinderInfo(
                    radius=cylinder.Radius(),
                    axis_dir=(
                        axis.Direction().X(),
                        axis.Direction().Y(),
                        axis.Direction().Z(),
                    ),
                    axis_loc=(
                        axis.Location().X(),
                        axis.Location().Y(),
                        axis.Location().Z(),
                    ),
                    # A reversed cylindrical face has material on the outside,
                    # which is what a bore or hole looks like in a solid.
                    internal=face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED,
                    area=props.Mass(),
                )
            )
        explorer.Next()

    return counts, cylinders


def features_for_component(component_id: str, measurements: ShapeMeasurements) -> list[GeometryFeature]:
    """Emits per-component geometry features with honest confidence values."""
    out: list[GeometryFeature] = []
    index = 0

    for label, count in sorted(measurements.face_types.items()):
        if label in ("PLANAR_FACE", "CYLINDRICAL_FACE", "CONICAL_FACE", "SPHERICAL_FACE"):
            index += 1
            out.append(
                GeometryFeature(
                    id=f"{component_id}-f{index}",
                    component_id=component_id,
                    type=label,
                    metrics={"count": count},
                    confidence=1.0,  # measured by the CAD kernel, not inferred
                    method="BREP_SURFACE_TYPE",
                )
            )

    for cylinder in measurements.cylinders:
        index += 1
        out.append(
            GeometryFeature(
                id=f"{component_id}-f{index}",
                component_id=component_id,
                type="HOLE_CANDIDATE" if cylinder.internal else "SHAFT_CANDIDATE",
                metrics={
                    "radius": round(cylinder.radius, 4),
                    "axis_direction": [round(v, 4) for v in cylinder.axis_dir],
                    "axis_location": [round(v, 4) for v in cylinder.axis_loc],
                    "face_area": round(cylinder.area, 4),
                },
                # The radius and axis are measured; calling it a hole or a shaft
                # is a reading of the face orientation, so it stays below 1.0.
                confidence=0.8,
                method="BREP_CYLINDER_ORIENTATION",
            )
        )

    coaxial = group_coaxial(measurements.cylinders)
    for group in coaxial:
        index += 1
        out.append(
            GeometryFeature(
                id=f"{component_id}-f{index}",
                component_id=component_id,
                type="COAXIAL_GROUP",
                metrics={
                    "axis_direction": [round(v, 4) for v in group["axis"]],
                    "radii": [round(r, 4) for r in group["radii"]],
                    "count": len(group["radii"]),
                },
                confidence=0.9,
                method="BREP_AXIS_MATCH",
            )
        )
    return out


def group_coaxial(cylinders: list[CylinderInfo], tol: float = 1e-6) -> list[dict[str, Any]]:
    """Groups cylindrical faces that share an axis line (direction and position)."""
    groups: list[dict[str, Any]] = []
    for cylinder in cylinders:
        placed = False
        for group in groups:
            if _same_axis(group["axis"], group["point"], cylinder.axis_dir, cylinder.axis_loc, tol):
                group["radii"].append(cylinder.radius)
                placed = True
                break
        if not placed:
            groups.append(
                {"axis": cylinder.axis_dir, "point": cylinder.axis_loc, "radii": [cylinder.radius]}
            )
    return [g for g in groups if len(g["radii"]) > 1]


def _same_axis(
    dir_a: tuple[float, float, float],
    point_a: tuple[float, float, float],
    dir_b: tuple[float, float, float],
    point_b: tuple[float, float, float],
    tol: float,
) -> bool:
    dot = sum(a * b for a, b in zip(dir_a, dir_b))
    if abs(abs(dot) - 1.0) > 1e-4:
        return False
    delta = tuple(point_b[i] - point_a[i] for i in range(3))
    cross = (
        delta[1] * dir_a[2] - delta[2] * dir_a[1],
        delta[2] * dir_a[0] - delta[0] * dir_a[2],
        delta[0] * dir_a[1] - delta[1] * dir_a[0],
    )
    return sum(c * c for c in cross) ** 0.5 <= max(tol, 1e-6) * 1000
