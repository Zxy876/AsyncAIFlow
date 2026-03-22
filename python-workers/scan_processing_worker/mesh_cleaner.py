from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymeshlab


@dataclass
class MeshCleanConfig:
    target_faces: int = 20000
    isolated_piece_min_diameter_pct: float = 3.0


def _percentage_param(value: float):
    if hasattr(pymeshlab, "PercentageValue"):
        return pymeshlab.PercentageValue(float(value))
    if hasattr(pymeshlab, "Percentage"):
        return pymeshlab.Percentage(float(value))
    return float(value)


def _try_filters(mesh_set: pymeshlab.MeshSet, filter_calls: list[tuple[str, dict]]) -> str:
    last_error: Exception | None = None
    for name, kwargs in filter_calls:
        try:
            method = getattr(mesh_set, name, None)
            if callable(method):
                method(**kwargs)
                return name
        except Exception as exc:  # pragma: no cover - pymeshlab runtime variants
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("no compatible pymeshlab filter found")


def _save_mesh_with_fallback(mesh_set: pymeshlab.MeshSet, output_path: Path) -> tuple[Path, str]:
    try:
        mesh_set.save_current_mesh(str(output_path))
        return output_path, output_path.suffix.lower()
    except Exception:
        if output_path.suffix.lower() != ".glb":
            raise

    fallback_path = output_path.with_suffix(".obj")
    mesh_set.save_current_mesh(str(fallback_path))
    return fallback_path, fallback_path.suffix.lower()


def clean_scan_to_glb(
    input_path: str | Path,
    output_path: str | Path,
    config: MeshCleanConfig | None = None,
) -> dict:
    cfg = config or MeshCleanConfig()
    src = Path(input_path).expanduser().resolve()
    dst = Path(output_path).expanduser().resolve()

    if not src.exists():
        raise FileNotFoundError(f"input mesh not found: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(str(src))

    mesh = ms.current_mesh()
    input_vertices = int(mesh.vertex_number())
    input_faces = int(mesh.face_number())

    isolated_filter = _try_filters(
        ms,
        [
            (
                "remove_isolated_pieces_wrt_diameter",
                {"mincomponentdiag": _percentage_param(cfg.isolated_piece_min_diameter_pct)},
            ),
            (
                "meshing_remove_connected_component_by_diameter",
                {"mincomponentdiag": _percentage_param(cfg.isolated_piece_min_diameter_pct)},
            ),
        ],
    )

    duplicate_filter = _try_filters(
        ms,
        [
            ("remove_duplicate_vertices", {}),
            ("meshing_remove_duplicate_vertices", {}),
        ],
    )

    decimation_filter = _try_filters(
        ms,
        [
            (
                "simplification_quadric_edge_collapse_decimation",
                {
                    "targetfacenum": int(cfg.target_faces),
                    "preservenormal": True,
                    "preserveboundary": True,
                    "preservetopology": True,
                    "optimalplacement": True,
                },
            ),
            (
                "meshing_decimation_quadric_edge_collapse",
                {
                    "targetfacenum": int(cfg.target_faces),
                    "preservenormal": True,
                    "preserveboundary": True,
                    "preservetopology": True,
                    "optimalplacement": True,
                },
            ),
        ],
    )

    actual_output_path, output_format = _save_mesh_with_fallback(ms, dst)

    out_mesh = ms.current_mesh()
    output_vertices = int(out_mesh.vertex_number())
    output_faces = int(out_mesh.face_number())

    return {
        "inputPath": str(src),
        "outputPath": str(actual_output_path),
        "inputVertices": input_vertices,
        "inputFaces": input_faces,
        "outputVertices": output_vertices,
        "outputFaces": output_faces,
        "targetFaces": int(cfg.target_faces),
        "outputFormat": output_format,
        "filters": {
            "isolatedPieceRemoval": isolated_filter,
            "duplicateVertices": duplicate_filter,
            "decimation": decimation_filter,
        },
    }
