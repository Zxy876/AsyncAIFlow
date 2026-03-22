from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("assembly-builder")


def _load_base_geometry(base_model_path: str | None) -> tuple[trimesh.Scene, dict]:
    scene = trimesh.Scene()
    stats = {
        "baseModelLoaded": False,
        "baseGeometryCount": 0,
    }

    if not base_model_path:
        return scene, stats

    base_path = Path(base_model_path).expanduser().resolve()
    if not base_path.exists():
        stats["baseModelMissing"] = str(base_path)
        return scene, stats

    loaded = trimesh.load(str(base_path), force="scene")
    if isinstance(loaded, trimesh.Scene):
        for name, geom in loaded.geometry.items():
            scene.add_geometry(geom, geom_name=f"base_{name}")
    else:
        scene.add_geometry(loaded, geom_name="base_mesh")

    stats["baseModelLoaded"] = True
    stats["baseGeometryCount"] = len(scene.geometry)
    stats["baseModelPath"] = str(base_path)
    return scene, stats


def _bounds(scene: trimesh.Scene) -> tuple[np.ndarray, np.ndarray]:
    if scene.geometry:
        bounds = scene.bounds
        return np.array(bounds[0], dtype=float), np.array(bounds[1], dtype=float)
    return np.array([-0.25, -0.25, -0.25], dtype=float), np.array([0.25, 0.25, 0.25], dtype=float)


def _is_attachable(component: dict) -> bool:
    cid = str(component.get("id", "")).lower()
    category = str(component.get("category", "")).lower()
    panel_role = str(component.get("panelRole", "")).lower()
    keywords = ("pocket", "collar", "lapel", "cuff", "sleeve", "hood", "panel")
    text = " ".join([cid, category, panel_role])
    return any(keyword in text for keyword in keywords)


def _module_extents(component: dict, base_max_extent: float) -> tuple[float, float, float]:
    category = str(component.get("category", "")).lower()
    base_unit = max(0.08, float(base_max_extent * 0.15))
    if "pocket" in category:
        return (base_unit * 0.95, base_unit * 0.45, base_unit * 0.85)
    if "collar" in category or "lapel" in category:
        return (base_unit * 1.2, base_unit * 0.35, base_unit * 0.65)
    if "sleeve" in category:
        return (base_unit * 1.35, base_unit * 0.5, base_unit * 0.7)
    return (base_unit * 0.9, base_unit * 0.4, base_unit * 0.7)


def build_assembly_scene(
    task_id: str,
    dsl: dict,
    base_model_path: str | None,
    output_dir: str | Path,
) -> dict:
    scene, stats = _load_base_geometry(base_model_path)

    min_bound, max_bound = _bounds(scene)
    center = (min_bound + max_bound) / 2
    extents = np.maximum(max_bound - min_bound, np.array([0.4, 0.4, 0.4]))

    components = dsl.get("components") if isinstance(dsl, dict) else []
    if not isinstance(components, list):
        components = []

    logger.info("DSL components length=%d", len(components))
    logger.info("DSL components payload=%s", json.dumps(components, ensure_ascii=False, default=str))
    if not components:
        logger.warning(
            "DSL components are empty; upstream GPT may not have produced modular components. task_id=%s",
            task_id,
        )

    attachable = [component for component in components if isinstance(component, dict) and _is_attachable(component)]
    if not attachable:
        attachable = [component for component in components if isinstance(component, dict)][:5]

    module_count = 0
    base_max_extent = float(max(extents[0], extents[1], extents[2]))
    base_radius = max(0.35, base_max_extent * 0.55)
    radial_offset = max(0.25, base_max_extent * 0.45)
    explode_radius = base_radius + radial_offset
    vertical_step = max(0.12, float(extents[1] * 0.35))

    for index, component in enumerate(attachable):
        ext = _module_extents(component, base_max_extent)
        mesh = trimesh.creation.box(extents=ext)

        angle = (2 * math.pi * index) / max(1, len(attachable))
        ring = index % 2
        ring_radius = explode_radius + ring * base_max_extent * 0.25
        x = center[0] + math.cos(angle) * ring_radius
        z = center[2] + math.sin(angle) * ring_radius
        y = center[1] + ((index % 3) - 1) * vertical_step

        transform = np.eye(4)
        transform[:3, 3] = np.array([x, y, z])
        mesh.apply_transform(transform)

        mesh.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[255, 20, 147, 255]
            )
        )

        component_id = str(component.get("id") or f"module_{index}")
        scene.add_geometry(mesh, geom_name=f"module_{component_id}")
        module_count += 1

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"final_assembly_{task_id}.glb"

    glb_data = scene.export(file_type="glb")
    output_path.write_bytes(glb_data)

    stats.update(
        {
            "moduleCount": module_count,
            "totalGeometryCount": len(scene.geometry),
            "outputPath": str(output_path),
            "baseExtents": extents.tolist(),
            "baseCenter": center.tolist(),
            "explodeRadius": explode_radius,
        }
    )

    return {
        "outputPath": str(output_path),
        "stats": stats,
    }
