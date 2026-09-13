"""Inter-component relationships measured on the real B-Rep.

The minimal distance between two solids comes from OpenCascade, so CONTACTS and
ADJACENT_TO are backed by a number, not a bounding-box guess. Every relationship
records method, evidence and a confidence that reflects the threshold involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schemas.cad_analysis import BoundingBox, Relationship
from .brep import CylinderInfo, ShapeMeasurements, _same_axis

CONTACT_TOL = 0.05  # mm - surfaces this close are treated as touching
NEAR_TOL = 5.0  # mm - "近接" band, reported with lower confidence
MAX_PAIRS = 120  # keeps the exact distance computation bounded


@dataclass
class ComponentGeometry:
    id: str
    name: str | None
    shape: Any
    measurements: ShapeMeasurements


def _bbox_gap(a: BoundingBox, b: BoundingBox) -> float:
    """Lower bound of the distance between two boxes; 0 when they overlap."""
    total = 0.0
    for axis in range(3):
        gap = max(a.min[axis] - b.max[axis], b.min[axis] - a.max[axis], 0.0)
        total += gap * gap
    return total**0.5


def _contains(outer: BoundingBox, inner: BoundingBox, tol: float = CONTACT_TOL) -> bool:
    return all(
        outer.min[i] - tol <= inner.min[i] and inner.max[i] <= outer.max[i] + tol for i in range(3)
    )


def _exact_distance(shape_a: Any, shape_b: Any) -> float | None:
    try:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape

        calculator = BRepExtrema_DistShapeShape(shape_a, shape_b)
        calculator.Perform()
        if not calculator.IsDone():
            return None
        return calculator.Value()
    except Exception:
        return None


def detect(components: list[ComponentGeometry]) -> list[Relationship]:
    out: list[Relationship] = []
    pairs = 0

    for i, a in enumerate(components):
        for b in components[i + 1 :]:
            box_a = a.measurements.bounding_box
            box_b = b.measurements.bounding_box
            if box_a is None or box_b is None:
                continue

            lower_bound = _bbox_gap(box_a, box_b)
            if lower_bound > NEAR_TOL:
                continue  # too far apart for any of the relationships below

            distance: float | None = None
            if pairs < MAX_PAIRS:
                distance = _exact_distance(a.shape, b.shape)
                pairs += 1

            label_a = a.name or a.id
            label_b = b.name or b.id

            if distance is not None and distance <= CONTACT_TOL:
                out.append(
                    Relationship(
                        id=f"rel-{a.id}-{b.id}-contact",
                        type="CONTACTS",
                        source_component=a.id,
                        target_component=b.id,
                        confidence=0.95,
                        evidence=(
                            f"{label_a} と {label_b} の最小距離が {distance:.3f} mm です"
                            "（CADカーネルによる実測）"
                        ),
                        method="FACE_CONTACT",
                    )
                )
            elif distance is not None and distance <= NEAR_TOL:
                out.append(
                    Relationship(
                        id=f"rel-{a.id}-{b.id}-adjacent",
                        type="ADJACENT_TO",
                        source_component=a.id,
                        target_component=b.id,
                        confidence=0.7,
                        evidence=(
                            f"{label_a} と {label_b} の最小距離が {distance:.2f} mm です"
                            f"（{NEAR_TOL:.0f} mm 以内を近接と判定）"
                        ),
                        method="FACE_CONTACT",
                    )
                )

            # Containment is judged on bounding boxes, so it stays a candidate.
            inner, outer = None, None
            if _contains(box_a, box_b) and _volume(box_a) > _volume(box_b):
                inner, outer = b, a
            elif _contains(box_b, box_a) and _volume(box_b) > _volume(box_a):
                inner, outer = a, b
            if inner is not None and outer is not None:
                out.append(
                    Relationship(
                        id=f"rel-{inner.id}-{outer.id}-inside",
                        type="INSIDE",
                        source_component=inner.id,
                        target_component=outer.id,
                        confidence=0.75,
                        evidence=(
                            f"{inner.name or inner.id} の外形範囲が {outer.name or outer.id} の"
                            "外形範囲に収まっています（バウンディングボックス判定）"
                        ),
                        method="BBOX_CONTAINMENT",
                    )
                )

    out.extend(_coaxial(components))
    return out


def _volume(box: BoundingBox) -> float:
    sx, sy, sz = box.size()
    return max(sx, 0.0) * max(sy, 0.0) * max(sz, 0.0)


def _coaxial(components: list[ComponentGeometry]) -> list[Relationship]:
    """Two components are coaxial when a cylindrical face of each shares an axis."""
    out: list[Relationship] = []
    for i, a in enumerate(components):
        for b in components[i + 1 :]:
            match = _matching_axis(a.measurements.cylinders, b.measurements.cylinders)
            if match is None:
                continue
            radius_a, radius_b = match
            out.append(
                Relationship(
                    id=f"rel-{a.id}-{b.id}-coaxial",
                    type="COAXIAL_WITH",
                    source_component=a.id,
                    target_component=b.id,
                    confidence=0.9,
                    evidence=(
                        f"{a.name or a.id} の円筒面（半径 {radius_a:.1f} mm）と "
                        f"{b.name or b.id} の円筒面（半径 {radius_b:.1f} mm）が同一軸線上にあります"
                    ),
                    method="AXIS_ALIGNMENT",
                )
            )
    return out


def _matching_axis(
    cylinders_a: list[CylinderInfo], cylinders_b: list[CylinderInfo]
) -> tuple[float, float] | None:
    for cylinder_a in cylinders_a:
        for cylinder_b in cylinders_b:
            if _same_axis(
                cylinder_a.axis_dir,
                cylinder_a.axis_loc,
                cylinder_b.axis_dir,
                cylinder_b.axis_loc,
                1e-6,
            ):
                return cylinder_a.radius, cylinder_b.radius
    return None
