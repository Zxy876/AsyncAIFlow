from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_FABRIC_WIDTH_MM = 1500
DEFAULT_GAP_MM = 10

_CATEGORY_DIMENSIONS_MM: dict[str, tuple[int, int]] = {
    "body": (620, 780),
    "sleeve": (280, 620),
    "collar": (220, 110),
    "cuff": (240, 120),
    "pocket": (180, 220),
    "placket": (90, 420),
    "hood": (420, 500),
    "waistband": (520, 140),
    "leg": (360, 920),
    "skirt": (760, 860),
    "other": (320, 320),
}


@dataclass(frozen=True)
class PieceSpec:
    component_id: str
    name: str
    category: str
    width_mm: int
    height_mm: int
    allow_rotation: bool
    area_mm2: int
    dimension_source: str


def extract_piece_specs(dsl: dict[str, Any]) -> tuple[list[PieceSpec], list[dict[str, Any]]]:
    pieces: list[PieceSpec] = []
    warnings: list[dict[str, Any]] = []
    for component in dsl.get("components", []):
        width_mm, height_mm, source = _resolve_dimensions(component)
        allow_rotation = _resolve_allow_rotation(component)
        piece = PieceSpec(
            component_id=str(component.get("id") or ""),
            name=str(component.get("name") or component.get("id") or ""),
            category=str(component.get("category") or "other"),
            width_mm=width_mm,
            height_mm=height_mm,
            allow_rotation=allow_rotation,
            area_mm2=width_mm * height_mm,
            dimension_source=source,
        )
        pieces.append(piece)
        if source == "category-estimate":
            warnings.append(
                {
                    "code": "ESTIMATED_BOUNDING_BOX",
                    "componentId": piece.component_id,
                    "message": (
                        f"Component '{piece.component_id}' has no explicit geometry. "
                        f"Used category-based estimate {width_mm}x{height_mm} mm."
                    ),
                }
            )
    return pieces, warnings


def resolve_fabric_width_mm(payload: dict[str, Any], dsl: dict[str, Any]) -> int:
    value = _first_defined(
        payload.get("fabricWidthMm"),
        ((dsl.get("constraints") or {}).get("optimization") or {}).get("fabricWidthMm"),
        (dsl.get("metadata") or {}).get("fabricWidthMm"),
        DEFAULT_FABRIC_WIDTH_MM,
    )
    return _positive_int(value, DEFAULT_FABRIC_WIDTH_MM)


def resolve_gap_mm(payload: dict[str, Any], dsl: dict[str, Any]) -> int:
    value = _first_defined(
        payload.get("gapMm"),
        ((dsl.get("constraints") or {}).get("optimization") or {}).get("layoutGapMm"),
        (dsl.get("metadata") or {}).get("layoutGapMm"),
        DEFAULT_GAP_MM,
    )
    return _non_negative_int(value, DEFAULT_GAP_MM)


def _resolve_dimensions(component: dict[str, Any]) -> tuple[int, int, str]:
    explicit = _extract_explicit_box(component)
    if explicit is not None:
        return explicit[0], explicit[1], explicit[2]

    polygon_box = _extract_polygon_box(component)
    if polygon_box is not None:
        return polygon_box[0], polygon_box[1], polygon_box[2]

    category = str(component.get("category") or "other")
    width_mm, height_mm = _CATEGORY_DIMENSIONS_MM.get(category, _CATEGORY_DIMENSIONS_MM["other"])
    return width_mm, height_mm, "category-estimate"


def _extract_explicit_box(component: dict[str, Any]) -> tuple[int, int, str] | None:
    candidates: list[tuple[str, Any]] = [
        ("boundingBoxMm", component.get("boundingBoxMm")),
        ("layoutHint.boundingBoxMm", (component.get("layoutHint") or {}).get("boundingBoxMm")),
        ("pattern.boundingBoxMm", (component.get("pattern") or {}).get("boundingBoxMm")),
        ("dimensionsMm", component.get("dimensionsMm")),
    ]
    for source, value in candidates:
        if not isinstance(value, dict):
            continue
        width = value.get("width") or value.get("widthMm")
        height = value.get("height") or value.get("heightMm")
        if width is None or height is None:
            continue
        return _positive_int(width, 0), _positive_int(height, 0), source

    width = component.get("widthMm")
    height = component.get("heightMm")
    if width is not None and height is not None:
        return _positive_int(width, 0), _positive_int(height, 0), "component.widthMm"
    return None


def _extract_polygon_box(component: dict[str, Any]) -> tuple[int, int, str] | None:
    point_collections = [
        ("outlinePointsMm", component.get("outlinePointsMm")),
        ("polygonMm", component.get("polygonMm")),
        ("layoutHint.outlinePointsMm", (component.get("layoutHint") or {}).get("outlinePointsMm")),
    ]
    for source, points in point_collections:
        normalized = _normalize_points(points)
        if not normalized:
            continue
        xs = [point[0] for point in normalized]
        ys = [point[1] for point in normalized]
        width_mm = _positive_int(max(xs) - min(xs), 0)
        height_mm = _positive_int(max(ys) - min(ys), 0)
        if width_mm > 0 and height_mm > 0:
            return width_mm, height_mm, source
    return None


def _normalize_points(points: Any) -> list[tuple[float, float]]:
    if not isinstance(points, list):
        return []
    normalized: list[tuple[float, float]] = []
    for point in points:
        if isinstance(point, dict):
            x_value = point.get("x")
            y_value = point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            x_value = point[0]
            y_value = point[1]
        else:
            continue
        try:
            normalized.append((float(x_value), float(y_value)))
        except (TypeError, ValueError):
            continue
    return normalized


def _resolve_allow_rotation(component: dict[str, Any]) -> bool:
    if "allowRotation" in component:
        return bool(component.get("allowRotation"))

    layout_hint = component.get("layoutHint") or {}
    if isinstance(layout_hint, dict) and "allowRotation" in layout_hint:
        return bool(layout_hint.get("allowRotation"))

    grainline = component.get("grainline")
    if isinstance(grainline, dict):
        if "allowRotation" in grainline:
            return bool(grainline.get("allowRotation"))
        return False

    if component.get("grainlineRequired") is True:
        return False
    return True


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _non_negative_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None