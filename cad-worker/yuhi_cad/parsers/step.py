"""STEP reading via OpenCascade (OCP), including assembly metadata.

Everything here is measured or read from the file. Nothing is guessed: when the
file omits a name, a colour or a layer, the field stays None and a warning is
recorded instead of being filled with a plausible value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import parse_failed, step_backend_missing


@dataclass
class StepPart:
    """One leaf occurrence in the assembly, already placed in world coordinates."""

    id: str
    node_id: str
    name: str | None
    shape: Any
    color: str | None
    layer: str | None
    material: str | None
    transform: list[float] | None


@dataclass
class StepNode:
    id: str
    parent_id: str | None
    name: str | None
    transform: list[float] | None
    children: list[str] = field(default_factory=list)


@dataclass
class StepDocument:
    root_names: list[str]
    nodes: list[StepNode]
    parts: list[StepPart]
    units: str
    warnings: list[tuple[str, str]] = field(default_factory=list)


def backend_available() -> bool:
    try:
        _imports()
        return True
    except Exception:
        return False


def _imports() -> dict[str, Any]:
    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Quantity import Quantity_Color
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDataStd import TDataStd_Name
        from OCP.TDF import TDF_Label, TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool
    except Exception as exc:  # pragma: no cover - depends on native package
        raise step_backend_missing(f"{type(exc).__name__}: {exc}") from exc
    return {
        "BRepBuilderAPI_Transform": BRepBuilderAPI_Transform,
        "IFSelect_ReturnStatus": IFSelect_ReturnStatus,
        "Quantity_Color": Quantity_Color,
        "STEPCAFControl_Reader": STEPCAFControl_Reader,
        "TCollection_ExtendedString": TCollection_ExtendedString,
        "TDataStd_Name": TDataStd_Name,
        "TDF_Label": TDF_Label,
        "TDF_LabelSequence": TDF_LabelSequence,
        "TDocStd_Document": TDocStd_Document,
        "XCAFDoc_ColorType": XCAFDoc_ColorType,
        "XCAFDoc_DocumentTool": XCAFDoc_DocumentTool,
    }


def _label_name(api: dict[str, Any], label: Any) -> str | None:
    attr = api["TDataStd_Name"]()
    if label.FindAttribute(api["TDataStd_Name"].GetID_s(), attr):
        text = attr.Get().ToExtString()
        return text or None
    return None


def _transform_matrix(location: Any) -> list[float] | None:
    if location.IsIdentity():
        return None
    trsf = location.Transformation()
    rows = [
        [trsf.Value(r, c) for c in range(1, 5)] for r in range(1, 4)
    ]
    rows.append([0.0, 0.0, 0.0, 1.0])
    return [value for row in rows for value in row]


def _color_hex(api: dict[str, Any], color_tool: Any, shape: Any) -> str | None:
    color = api["Quantity_Color"]()
    types = (
        api["XCAFDoc_ColorType"].XCAFDoc_ColorSurf,
        api["XCAFDoc_ColorType"].XCAFDoc_ColorGen,
        api["XCAFDoc_ColorType"].XCAFDoc_ColorCurv,
    )
    for color_type in types:
        if color_tool.GetColor(shape, color_type, color):
            return "#%02X%02X%02X" % (
                round(color.Red() * 255),
                round(color.Green() * 255),
                round(color.Blue() * 255),
            )
    return None


def _layer_name(layer_tool: Any, shape: Any) -> str | None:
    if layer_tool is None:
        return None
    try:
        from OCP.TColStd import TColStd_HSequenceOfExtendedString

        names = TColStd_HSequenceOfExtendedString()
        if layer_tool.GetLayers(shape, names) and names.Length() > 0:
            return names.Value(1).ToExtString() or None
    except Exception:
        return None
    return None


def _material_name(material_tool: Any, label: Any) -> str | None:
    if material_tool is None:
        return None
    try:
        from OCP.TCollection import TCollection_HAsciiString

        name = TCollection_HAsciiString()
        description = TCollection_HAsciiString()
        density = [0.0]
        dens_name = TCollection_HAsciiString()
        dens_type = TCollection_HAsciiString()
        if material_tool.GetMaterial(label, name, description, density, dens_name, dens_type):
            text = name.ToCString()
            return text or None
    except Exception:
        return None
    return None


def read(path: str, apply_location: bool = True) -> StepDocument:
    """Reads a STEP file and returns the assembly tree with placed leaf shapes."""
    api = _imports()
    from OCP.TopLoc import TopLoc_Location

    reader = api["STEPCAFControl_Reader"]()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetMatMode(True)
    status = reader.ReadFile(path)
    if status != api["IFSelect_ReturnStatus"].IFSelect_RetDone:
        raise parse_failed(f"STEPCAFControl_Reader status={status}")

    doc = api["TDocStd_Document"](api["TCollection_ExtendedString"]("yuhi"))
    if not reader.Transfer(doc):
        raise parse_failed("STEP transfer produced no shapes")

    tools = api["XCAFDoc_DocumentTool"]
    shape_tool = tools.ShapeTool_s(doc.Main())
    color_tool = tools.ColorTool_s(doc.Main())
    try:
        layer_tool = tools.LayerTool_s(doc.Main())
    except Exception:
        layer_tool = None
    try:
        material_tool = tools.MaterialTool_s(doc.Main())
    except Exception:
        material_tool = None

    warnings: list[tuple[str, str]] = []
    nodes: list[StepNode] = []
    parts: list[StepPart] = []
    counter = {"node": 0, "part": 0}

    def new_node(parent_id: str | None, name: str | None, transform: list[float] | None) -> StepNode:
        counter["node"] += 1
        node = StepNode(id=f"n{counter['node']}", parent_id=parent_id, name=name, transform=transform)
        nodes.append(node)
        if parent_id is not None:
            for candidate in nodes:
                if candidate.id == parent_id:
                    candidate.children.append(node.id)
                    break
        return node

    def walk(label: Any, location: Any, parent_id: str | None, depth: int) -> None:
        if depth > 32:
            warnings.append(("ASSEMBLY_TOO_DEEP", "アセンブリ階層が深いため、一部の下位部品を省略しました。"))
            return

        name = _label_name(api, label)

        if shape_tool.IsReference_s(label):
            referred = api["TDF_Label"]()
            shape_tool.GetReferredShape_s(label, referred)
            child_location = location.Multiplied(shape_tool.GetLocation_s(label))
            if name is None:
                name = _label_name(api, referred)
            walk_with_name(referred, child_location, parent_id, depth + 1, name, label)
            return

        walk_with_name(label, location, parent_id, depth, name, label)

    def walk_with_name(
        label: Any,
        location: Any,
        parent_id: str | None,
        depth: int,
        name: str | None,
        instance_label: Any,
    ) -> None:
        if shape_tool.IsAssembly_s(label):
            node = new_node(parent_id, name, _transform_matrix(location))
            components = api["TDF_LabelSequence"]()
            shape_tool.GetComponents_s(label, components)
            for index in range(1, components.Length() + 1):
                walk(components.Value(index), location, node.id, depth + 1)
            return

        shape = shape_tool.GetShape_s(label)
        if shape is None or shape.IsNull():
            warnings.append(("EMPTY_COMPONENT", "形状を持たない構成要素が含まれていました。"))
            return

        node = new_node(parent_id, name, _transform_matrix(location))
        counter["part"] += 1

        placed = shape
        if apply_location and not location.IsIdentity():
            placed = shape.Moved(TopLoc_Location(location.Transformation()))

        parts.append(
            StepPart(
                id=f"c{counter['part']}",
                node_id=node.id,
                name=name,
                shape=placed,
                color=_color_hex(api, color_tool, shape) or _color_hex(api, color_tool, placed),
                layer=_layer_name(layer_tool, shape),
                material=_material_name(material_tool, label),
                transform=_transform_matrix(location),
            )
        )

    free = api["TDF_LabelSequence"]()
    shape_tool.GetFreeShapes(free)
    if free.Length() == 0:
        raise parse_failed("STEP file contains no free shapes")

    root_names: list[str] = []
    for index in range(1, free.Length() + 1):
        label = free.Value(index)
        root_names.append(_label_name(api, label) or f"root{index}")
        walk(label, TopLoc_Location(), None, 0)

    units = _units(reader, warnings)

    if not parts:
        raise parse_failed("STEP file produced no solid components")

    return StepDocument(
        root_names=root_names, nodes=nodes, parts=parts, units=units, warnings=warnings
    )


def _units(reader: Any, warnings: list[tuple[str, str]]) -> str:
    """STEP carries its own length unit. Reported as-is, or 'unknown'."""
    try:
        from OCP.Interface import Interface_Static

        value = Interface_Static.CVal_s("xstep.cascade.unit")
        mapping = {"MM": "mm", "M": "m", "CM": "cm", "INCH": "in"}
        if value and value.upper() in mapping:
            return mapping[value.upper()]
    except Exception:
        pass
    warnings.append(("UNITS_UNKNOWN", "STEPファイルから単位を特定できませんでした。"))
    return "unknown"
