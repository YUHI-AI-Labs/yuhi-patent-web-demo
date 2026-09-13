"""Deterministic relationship inference from component bounding boxes.

These are candidates, not conclusions: every relationship carries the method
that produced it, an evidence string a human can check, and a confidence that
is never 1.0 for anything inferred rather than measured.
"""

from __future__ import annotations

from ..schemas.cad_analysis import BoundingBox, CadComponent, Relationship

TOUCH_TOLERANCE = 0.5  # mm
AXIS_TOLERANCE = 0.05  # relative


def _overlap(a: BoundingBox, b: BoundingBox, axis: int) -> float:
    return min(a.max[axis], b.max[axis]) - max(a.min[axis], b.min[axis])


def _contains(outer: BoundingBox, inner: BoundingBox, tol: float = TOUCH_TOLERANCE) -> bool:
    return all(
        outer.min[i] - tol <= inner.min[i] and inner.max[i] <= outer.max[i] + tol
        for i in range(3)
    )


def _volume(box: BoundingBox) -> float:
    sx, sy, sz = box.size()
    return max(sx, 0.0) * max(sy, 0.0) * max(sz, 0.0)


def detect(components: list[CadComponent]) -> list[Relationship]:
    out: list[Relationship] = []
    boxed = [c for c in components if c.bounding_box is not None]

    for i, a in enumerate(boxed):
        for b in boxed[i + 1 :]:
            box_a, box_b = a.bounding_box, b.bounding_box
            assert box_a and box_b

            if _contains(box_a, box_b) and _volume(box_a) > _volume(box_b):
                out.append(
                    Relationship(
                        id=f"rel-{a.id}-{b.id}-inside",
                        type="INSIDE",
                        source_component=b.id,
                        target_component=a.id,
                        confidence=0.7,
                        evidence=f"{b.id} のバウンディングボックスが {a.id} の内側に収まっています",
                        method="BBOX_CONTAINMENT",
                    )
                )
                continue
            if _contains(box_b, box_a) and _volume(box_b) > _volume(box_a):
                out.append(
                    Relationship(
                        id=f"rel-{b.id}-{a.id}-inside",
                        type="INSIDE",
                        source_component=a.id,
                        target_component=b.id,
                        confidence=0.7,
                        evidence=f"{a.id} のバウンディングボックスが {b.id} の内側に収まっています",
                        method="BBOX_CONTAINMENT",
                    )
                )
                continue

            gaps = [_overlap(box_a, box_b, axis) for axis in range(3)]
            touching = [g for g in gaps if abs(g) <= TOUCH_TOLERANCE]
            overlapping = [g for g in gaps if g > TOUCH_TOLERANCE]
            if len(touching) >= 1 and len(overlapping) >= 2:
                out.append(
                    Relationship(
                        id=f"rel-{a.id}-{b.id}-contact",
                        type="CONTACTS",
                        source_component=a.id,
                        target_component=b.id,
                        confidence=0.55,
                        evidence="2軸で重なり、残る1軸で境界が接しています（バウンディングボックス判定）",
                        method="FACE_CONTACT",
                    )
                )
            elif all(g > -TOUCH_TOLERANCE * 4 for g in gaps):
                out.append(
                    Relationship(
                        id=f"rel-{a.id}-{b.id}-adjacent",
                        type="ADJACENT_TO",
                        source_component=a.id,
                        target_component=b.id,
                        confidence=0.4,
                        evidence="バウンディングボックスが近接しています（接触は未確認）",
                        method="CENTROID_DISTANCE",
                    )
                )
    return out


def detect_coaxial(components: list[CadComponent]) -> list[Relationship]:
    """Coaxial candidates: bounding boxes whose centres coincide on two axes and
    whose cross-section on those axes is close to square, which is what a
    rotationally symmetric part looks like through a bounding box. Short rings
    (bearings) and long shafts both satisfy this, so no elongation is required.
    """
    out: list[Relationship] = []
    boxed = [c for c in components if c.bounding_box is not None]
    for i, a in enumerate(boxed):
        for b in boxed[i + 1 :]:
            box_a, box_b = a.bounding_box, b.bounding_box
            assert box_a and box_b
            for axis in range(3):
                others = [x for x in range(3) if x != axis]
                reference = max(
                    box_a.size()[others[0]],
                    box_a.size()[others[1]],
                    box_b.size()[others[0]],
                    box_b.size()[others[1]],
                )
                if reference <= 0:
                    continue
                aligned = all(
                    abs(box_a.center()[o] - box_b.center()[o]) <= AXIS_TOLERANCE * reference
                    for o in others
                )
                round_section = all(
                    abs(box.size()[others[0]] - box.size()[others[1]])
                    <= AXIS_TOLERANCE * 2 * max(box.size()[others[0]], box.size()[others[1]], 1e-9)
                    for box in (box_a, box_b)
                )
                if aligned and round_section:
                    out.append(
                        Relationship(
                            id=f"rel-{a.id}-{b.id}-coaxial-{axis}",
                            type="COAXIAL_WITH",
                            source_component=a.id,
                            target_component=b.id,
                            confidence=0.6,
                            evidence=(
                                f"軸{'XYZ'[axis]}に対して断面がほぼ正方形で、"
                                "他2軸の中心が一致しています（バウンディングボックス判定）"
                            ),
                            method="AXIS_ALIGNMENT",
                        )
                    )
                    break
    return out
