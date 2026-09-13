"""Offscreen orthographic renderer for the eight fixed cameras.

Deliberately dependency-light: numpy for the z-buffer, pillow to write PNG. No
GPU, no display server, no VTK window - the worker runs headless inside the app.
Background is near-white and shading is flat, matching the product's look and
keeping the images useful as VLM input later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

from ..geometry.tessellate import ComponentMesh, bounds
from .cameras import BACKGROUND, CAMERAS, SIZE

LIGHT_DIRECTION = np.array([0.35, -0.6, 0.72])
BASE_COLOR = (0x9A, 0xA3, 0xB0)
MARGIN = 0.12


def _hex_to_rgb(value: str | None) -> tuple[int, int, int]:
    if not value or not value.startswith("#") or len(value) != 7:
        return BASE_COLOR
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def _basis(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    forward = direction / np.linalg.norm(direction)
    world_up = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(forward, world_up))) > 0.99:
        world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(world_up, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    return right, up, forward


def render_all(
    meshes: list[ComponentMesh],
    output_dir: Path,
    size: tuple[int, int] = SIZE,
) -> list[tuple[str, Path, int, int]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    low, high = bounds(meshes)
    center = np.array([(low[i] + high[i]) / 2 for i in range(3)])
    extent = max(max(high[i] - low[i] for i in range(3)), 1e-6)

    written: list[tuple[str, Path, int, int]] = []
    for camera_name, direction in CAMERAS.items():
        image = _render_one(meshes, np.array(direction, dtype=float), center, extent, size)
        target = output_dir / f"{camera_name}.png"
        image.save(target, format="PNG", optimize=True)
        written.append((camera_name, target, size[0], size[1]))
    return written


def _render_one(
    meshes: Iterable[ComponentMesh],
    direction: np.ndarray,
    center: np.ndarray,
    extent: float,
    size: tuple[int, int],
) -> Image.Image:
    width, height = size
    right, up, forward = _basis(-direction)

    background = np.array(_hex_to_rgb(BACKGROUND), dtype=np.float32)
    frame = np.tile(background, (height, width, 1))
    depth = np.full((height, width), np.inf, dtype=np.float32)

    scale = (1.0 - MARGIN * 2) * min(width, height) / extent
    origin = np.array([width / 2, height / 2])

    for mesh in meshes:
        if not mesh.indices:
            continue
        vertices = np.asarray(mesh.positions, dtype=np.float32).reshape(-1, 3) - center
        faces = np.asarray(mesh.indices, dtype=np.int32).reshape(-1, 3)

        screen_x = vertices @ right * scale + origin[0]
        screen_y = -(vertices @ up) * scale + origin[1]
        view_depth = vertices @ forward

        color = np.array(_hex_to_rgb(mesh.color), dtype=np.float32)
        _rasterize(frame, depth, faces, screen_x, screen_y, view_depth, vertices, color)

    return Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8), mode="RGB")


def _rasterize(
    frame: np.ndarray,
    depth: np.ndarray,
    faces: np.ndarray,
    screen_x: np.ndarray,
    screen_y: np.ndarray,
    view_depth: np.ndarray,
    vertices: np.ndarray,
    color: np.ndarray,
) -> None:
    height, width = depth.shape

    for face in faces:
        i0, i1, i2 = face
        x0, x1, x2 = screen_x[i0], screen_x[i1], screen_x[i2]
        y0, y1, y2 = screen_y[i0], screen_y[i1], screen_y[i2]
        z0, z1, z2 = view_depth[i0], view_depth[i1], view_depth[i2]

        min_x = max(int(np.floor(min(x0, x1, x2))), 0)
        max_x = min(int(np.ceil(max(x0, x1, x2))), width - 1)
        min_y = max(int(np.floor(min(y0, y1, y2))), 0)
        max_y = min(int(np.ceil(max(y0, y1, y2))), height - 1)
        if min_x > max_x or min_y > max_y:
            continue

        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue

        normal = np.cross(vertices[i1] - vertices[i0], vertices[i2] - vertices[i0])
        norm = np.linalg.norm(normal)
        if norm < 1e-12:
            continue
        lambert = abs(float(np.dot(normal / norm, LIGHT_DIRECTION)))
        shade = 0.45 + 0.55 * lambert
        shaded = np.clip(color * shade + 40.0 * (1.0 - shade), 0, 255)

        xs = np.arange(min_x, max_x + 1)
        ys = np.arange(min_y, max_y + 1)
        grid_x, grid_y = np.meshgrid(xs + 0.5, ys + 0.5)

        w0 = ((x1 - x0) * (grid_y - y0) - (grid_x - x0) * (y1 - y0)) / area
        w1 = ((grid_x - x0) * (y2 - y0) - (x2 - x0) * (grid_y - y0)) / area
        inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
        if not inside.any():
            continue

        w2 = 1.0 - w0 - w1
        pixel_depth = w2 * z0 + w1 * z1 + w0 * z2
        window = depth[min_y : max_y + 1, min_x : max_x + 1]
        closer = inside & (pixel_depth < window)
        if not closer.any():
            continue

        window[closer] = pixel_depth[closer]
        target = frame[min_y : max_y + 1, min_x : max_x + 1]
        target[closer] = shaded
