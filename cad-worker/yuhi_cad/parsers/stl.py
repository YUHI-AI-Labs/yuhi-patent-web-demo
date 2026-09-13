"""Pure-Python STL reader.

STL is a mesh format: no part names, no assembly, no B-Rep faces. The worker
says so in a warning rather than pretending the result is equivalent to STEP.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

Triangle = tuple[
    tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
]


@dataclass
class Mesh:
    triangles: list[Triangle]

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def unique_vertex_count(self) -> int:
        seen: set[tuple[float, float, float]] = set()
        for tri in self.triangles:
            seen.update(tri)
        return len(seen)

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        xs = [v[0] for t in self.triangles for v in t]
        ys = [v[1] for t in self.triangles for v in t]
        zs = [v[2] for t in self.triangles for v in t]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def surface_area(self) -> float:
        total = 0.0
        for a, b, c in self.triangles:
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
            cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            total += 0.5 * (cx * cx + cy * cy + cz * cz) ** 0.5
        return total

    def volume(self) -> float:
        """Signed tetrahedron sum. Meaningful only for closed meshes."""
        total = 0.0
        for a, b, c in self.triangles:
            total += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
        return abs(total)


def _is_binary(data: bytes) -> bool:
    if len(data) < 84:
        return False
    if data[:5].lower().startswith(b"solid"):
        # An ASCII header is not proof: check the declared triangle count.
        count = struct.unpack_from("<I", data, 80)[0]
        return len(data) == 84 + count * 50
    return True


def parse(data: bytes) -> Mesh:
    if _is_binary(data):
        return _parse_binary(data)
    return _parse_ascii(data.decode("utf-8", errors="replace"))


def _parse_binary(data: bytes) -> Mesh:
    count = struct.unpack_from("<I", data, 80)[0]
    expected = 84 + count * 50
    if len(data) < expected:
        raise ValueError(f"binary STL truncated: expected {expected} bytes, got {len(data)}")
    triangles: list[Triangle] = []
    offset = 84
    for _ in range(count):
        values = struct.unpack_from("<12fH", data, offset)
        triangles.append(
            (
                (values[3], values[4], values[5]),
                (values[6], values[7], values[8]),
                (values[9], values[10], values[11]),
            )
        )
        offset += 50
    return Mesh(triangles)


def _parse_ascii(text: str) -> Mesh:
    triangles: list[Triangle] = []
    current: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "vertex" and len(parts) >= 4:
            current.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(current) == 3:
                triangles.append((current[0], current[1], current[2]))
                current = []
    if not triangles:
        raise ValueError("no triangles found in ASCII STL")
    return Mesh(triangles)
