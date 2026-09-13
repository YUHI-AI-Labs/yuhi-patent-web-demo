"""CLI contract:

    yuhi-cad analyze --input <file> --output <derived-dir> --job-id <uuid>
    yuhi-cad capabilities

stdout carries exactly one JSON document. Diagnostics go to stderr. Exit code 0
means the JSON is a CADAnalysis; exit code 2 means the JSON is an error object.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

from . import SCHEMA_VERSION, __version__
from .errors import CadWorkerError, parse_failed, unsupported
from .geometry import relationships as rel
from .parsers import step as step_backend
from .parsers import stl as stl_parser
from .schemas.cad_analysis import (
    BoundingBox,
    CadAnalysis,
    CadComponent,
    CadModel,
    CadSource,
    CadWarning,
    GeometryFeature,
    validate_analysis,
)

SEMANTIC_LEVEL = {
    ".step": "FULL",
    ".stp": "FULL",
    ".dxf": "PLANAR",
    ".stl": "MESH_ONLY",
    ".pdf": "IMAGE",
    ".png": "IMAGE",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE",
}

FORMAT = {
    ".step": "STEP",
    ".stp": "STEP",
    ".dxf": "DXF",
    ".stl": "STL",
    ".pdf": "PDF",
    ".png": "IMAGE",
    ".jpg": "IMAGE",
    ".jpeg": "IMAGE",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def analyze(input_path: Path, output_dir: Path, job_id: str, render: bool = True) -> CadAnalysis:
    ext = input_path.suffix.lower()
    if ext not in FORMAT:
        raise unsupported(ext)
    if not input_path.is_file():
        raise parse_failed(f"input not found: {input_path.name}")

    output_dir.mkdir(parents=True, exist_ok=True)
    source = CadSource(
        filename=input_path.name,
        format=FORMAT[ext],  # type: ignore[arg-type]
        sha256=_sha256(input_path),
        size_bytes=input_path.stat().st_size,
        semantic_level=SEMANTIC_LEVEL[ext],  # type: ignore[arg-type]
    )

    if ext == ".stl":
        return _analyze_stl(input_path, source, job_id)
    if ext in (".step", ".stp"):
        from .analyzers.step_analyzer import analyze_step

        return analyze_step(input_path, output_dir, job_id, source, render=render)
    raise unsupported(ext)


def _analyze_stl(path: Path, source: CadSource, job_id: str) -> CadAnalysis:
    try:
        mesh = stl_parser.parse(path.read_bytes())
    except Exception as exc:
        raise parse_failed(f"{type(exc).__name__}: {exc}") from exc

    low, high = mesh.bounds()
    box = BoundingBox(min=low, max=high)
    component = CadComponent(
        id="c1",
        original_name=None,
        normalized_name=None,
        bounding_box=box,
        volume=mesh.volume(),
        surface_area=mesh.surface_area(),
        face_count=mesh.triangle_count,
        solid_count=1,
    )
    analysis = CadAnalysis(
        job_id=job_id,
        generated_at=_now(),
        source=source,
        model=CadModel(
            units="unknown",
            bounding_box=box,
            volume=mesh.volume(),
            surface_area=mesh.surface_area(),
            solid_count=1,
            shell_count=1,
            face_count=mesh.triangle_count,
            edge_count=mesh.triangle_count * 3,
            vertex_count=mesh.unique_vertex_count(),
        ),
        components=[component],
        geometry_features=[
            GeometryFeature(
                id="f1",
                component_id="c1",
                type="SYMMETRY_CANDIDATE",
                metrics={"bbox_size": list(box.size())},
                confidence=0.3,
                method="BBOX_ASPECT",
            )
        ],
        relationships=rel.detect([component]) + rel.detect_coaxial([component]),
        warnings=[
            CadWarning(
                code="MESH_ONLY_INPUT",
                message_ja=(
                    "STLは形状情報のみを解析します。部品名やアセンブリ情報は含まれない場合があります。"
                    "より詳しく調べる場合はSTEPをお使いください。"
                ),
                severity="INFO",
            ),
            CadWarning(
                code="UNITS_UNKNOWN",
                message_ja="STLには単位情報が含まれないため、寸法の単位は推定できません。",
                severity="INFO",
            ),
        ],
    )
    return analysis


def _render_available() -> bool:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401

        return True
    except Exception:
        return False


def capabilities() -> dict:
    return {
        "worker_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "formats": {
            "STEP": {"available": step_backend.backend_available(), "semantic_level": "FULL"},
            "STL": {"available": True, "semantic_level": "MESH_ONLY"},
            "DXF": {"available": False, "semantic_level": "PLANAR", "note": "not implemented yet"},
        },
        "renders": {"available": _render_available(), "cameras": 8},
        "network": "disabled",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yuhi-cad")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = sub.add_parser("analyze")
    analyze_cmd.add_argument("--input", required=True)
    analyze_cmd.add_argument("--output", required=True)
    analyze_cmd.add_argument("--job-id", required=True)
    analyze_cmd.add_argument(
        "--no-render", action="store_true", help="skip the eight local preview renders"
    )

    sub.add_parser("capabilities")

    args = parser.parse_args(argv)

    try:
        if args.command == "capabilities":
            print(json.dumps(capabilities(), ensure_ascii=False))
            return 0

        result = analyze(
            Path(args.input), Path(args.output), args.job_id, render=not args.no_render
        )
        payload = result.to_dict()
        validate_analysis(payload)
        out_file = Path(args.output) / f"cad-analysis-{args.job_id}.json"
        out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except CadWorkerError as err:
        print(json.dumps(err.to_dict(), ensure_ascii=False))
        return 2
    except Exception as exc:  # unexpected: still structured, still no raw content
        print(
            json.dumps(
                {
                    "error": {
                        "code": "INTERNAL",
                        "message_ja": "解析処理を完了できませんでした。もう一度お試しください。",
                        "detail": f"{type(exc).__name__}",
                    }
                },
                ensure_ascii=False,
            )
        )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
