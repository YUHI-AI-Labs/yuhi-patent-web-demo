"""Fixed camera set used for every model so renders are comparable.

Rendering itself lands in Gate D (trimesh + pillow, offscreen, light background).
Directions live here so the schema, the viewer and the renderer agree.
"""

from __future__ import annotations

CAMERAS: dict[str, tuple[float, float, float]] = {
    "front": (0.0, -1.0, 0.0),
    "rear": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0),
    "bottom": (0.0, 0.0, -1.0),
    "isometric_1": (1.0, -1.0, 1.0),
    "isometric_2": (-1.0, -1.0, 1.0),
}

BACKGROUND = "#F5F7FA"
LINE = "#666A73"
SIZE = (1024, 768)
