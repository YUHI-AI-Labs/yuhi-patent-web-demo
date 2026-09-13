"""Assembles a CADAnalysis for a STEP file from the deterministic layers.

Order: parse -> measure -> classify -> relate -> tessellate -> render. Each stage
reports progress on stderr so the runtime can forward it to the job record.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from ..geometry import brep, interactions, tessellate
from ..parsers import step as step_parser
from ..schemas.cad_analysis import (
    AssemblyNode,
    CadAnalysis,
    CadComponent,
    CadModel,
    CadSource,
    CadWarning,
    Render,
)
from ..semantics.normalize import normalize_name


def _progress(step: str, percent: int, message_ja: str) -> None:
    sys.stderr.write(
        json.dumps({"progress": {"step": step, "percent": percent, "message_ja": message_ja}}) + "\n"
    )
    sys.stderr.flush()


def _now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def analyze_step(
    input_path: Path,
    output_dir: Path,
    job_id: str,
    source: CadSource,
    render: bool = True,
) -> CadAnalysis:
    _progress("PARSING", 10, "ファイルを読み取っています")
    document = step_parser.read(str(input_path))

    _progress("GEOMETRY", 35, "形状と構成を調べています")
    geometries: list[interactions.ComponentGeometry] = []
    components: list[CadComponent] = []
    features = []

    total_volume = 0.0
    total_area = 0.0
    counters = {"solid": 0, "shell": 0, "face": 0, "edge": 0, "vertex": 0}
    low = [float("inf")] * 3
    high = [float("-inf")] * 3

    for part in document.parts:
        measurements = brep.measure(part.shape)
        geometries.append(
            interactions.ComponentGeometry(
                id=part.id, name=part.name, shape=part.shape, measurements=measurements
            )
        )
        components.append(
            CadComponent(
                id=part.id,
                assembly_node_id=part.node_id,
                original_name=part.name,
                normalized_name=normalize_name(part.name),
                bounding_box=measurements.bounding_box,
                volume=measurements.volume,
                surface_area=measurements.surface_area,
                material=part.material,
                color=part.color,
                layer=part.layer,
                face_count=measurements.face_count,
                solid_count=measurements.solid_count,
            )
        )
        features.extend(brep.features_for_component(part.id, measurements))

        total_volume += measurements.volume or 0.0
        total_area += measurements.surface_area or 0.0
        counters["solid"] += measurements.solid_count
        counters["shell"] += measurements.shell_count
        counters["face"] += measurements.face_count
        counters["edge"] += measurements.edge_count
        counters["vertex"] += measurements.vertex_count
        if measurements.bounding_box is not None:
            for axis in range(3):
                low[axis] = min(low[axis], measurements.bounding_box.min[axis])
                high[axis] = max(high[axis], measurements.bounding_box.max[axis])

    _progress("RELATIONS", 55, "構成要素の関係を調べています")
    relationships = interactions.detect(geometries)

    _progress("TESSELLATION", 70, "3D表示用のデータを作成しています")
    meshes = [
        tessellate.tessellate(part.shape, part.id, part.name, part.color) for part in document.parts
    ]
    mesh_path = output_dir / f"mesh-{job_id}.json"
    mesh_path.write_text(
        json.dumps(tessellate.to_viewer_payload(meshes, document.units), ensure_ascii=False),
        encoding="utf-8",
    )

    renders: list[Render] = []
    warnings = [
        CadWarning(code=code, message_ja=message, severity="INFO")
        for code, message in document.warnings
    ]

    if render:
        _progress("RENDERING", 85, "各方向のプレビュー画像を作成しています")
        try:
            from ..renders import raster

            for camera, path, width, height in raster.render_all(
                meshes, output_dir / "renders"
            ):
                renders.append(
                    Render(
                        camera=camera,  # type: ignore[arg-type]
                        # Stored POSIX-style so a project written on Windows
                        # can be read on macOS and the other way round.
                        path=f"renders/{path.name}",
                        width=width,
                        height=height,
                    )
                )
        except Exception as exc:  # rendering is optional, analysis is not
            warnings.append(
                CadWarning(
                    code="RENDER_UNAVAILABLE",
                    message_ja="プレビュー画像を作成できませんでした。解析結果は利用できます。",
                    severity="WARN",
                )
            )
            sys.stderr.write(f"render failed: {type(exc).__name__}\n")

    if not any(component.original_name for component in components):
        warnings.append(
            CadWarning(
                code="NAMES_MISSING",
                message_ja="このファイルには部品名が含まれていませんでした。名称は空欄のままにしています。",
                severity="INFO",
            )
        )

    bounding_box = None
    if low[0] != float("inf"):
        from ..schemas.cad_analysis import BoundingBox

        bounding_box = BoundingBox(min=(low[0], low[1], low[2]), max=(high[0], high[1], high[2]))

    nodes = [
        AssemblyNode(
            id=node.id,
            parent_id=node.parent_id,
            name=node.name,
            transform=node.transform,
            children=node.children,
        )
        for node in document.nodes
    ]

    _progress("READY", 100, "解析が完了しました")
    return CadAnalysis(
        job_id=job_id,
        generated_at=_now(),
        source=source,
        model=CadModel(
            units=document.units,  # type: ignore[arg-type]
            bounding_box=bounding_box,
            volume=total_volume or None,
            surface_area=total_area or None,
            solid_count=counters["solid"],
            shell_count=counters["shell"],
            face_count=counters["face"],
            edge_count=counters["edge"],
            vertex_count=counters["vertex"],
        ),
        assemblies=nodes,
        components=components,
        geometry_features=features,
        relationships=relationships,
        renders=renders,
        warnings=warnings,
    )
