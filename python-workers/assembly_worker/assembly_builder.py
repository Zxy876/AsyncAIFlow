from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("assembly-builder")

ASSET_MAP = {
    "pocket": ("cyber_pocket.glb",),
    "collar": ("tech_collar.obj", "tech_collar.glb"),
    "buckle": ("buckle.glb",),
    "belt": ("buckle.glb",),
}


def _assets_dir() -> Path:
    configured = os.getenv("ASSEMBLY_ASSETS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "assets").resolve()


def _apply_pink_pbr(mesh: trimesh.Trimesh) -> None:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[255, 20, 147, 255]
        )
    )


def _apply_cyber_pbr(mesh: trimesh.Trimesh) -> None:
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[40, 45, 50, 255],
            metallicFactor=0.8,
            roughnessFactor=0.3,
        )
    )


def _create_fallback_box(extents: tuple[float, float, float], position: np.ndarray) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    _apply_pink_pbr(mesh)
    mesh.apply_translation(position)
    return mesh


def _resolve_asset_file(component: dict, assets_dir: Path) -> Path | None:
    searchable = json.dumps(component, ensure_ascii=False, default=str).lower()
    for keyword, file_names in ASSET_MAP.items():
        if keyword in searchable:
            for file_name in file_names:
                candidate = assets_dir / file_name
                if candidate.exists():
                    return candidate
            # Return the first expected file for clearer warning messages when all are missing.
            return assets_dir / file_names[0]
    return None


def _extract_mesh(loaded: object) -> trimesh.Trimesh:
    if isinstance(loaded, trimesh.Trimesh):
        return loaded.copy()

    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError("asset scene has no geometry")

        dumped = loaded.dump(concatenate=True)
        if isinstance(dumped, trimesh.Trimesh):
            return dumped

        if isinstance(dumped, list):
            meshes = [item for item in dumped if isinstance(item, trimesh.Trimesh) and not item.is_empty]
            if not meshes:
                raise ValueError("asset scene dump contains no mesh")
            return trimesh.util.concatenate(meshes)

    raise ValueError(f"unsupported asset type: {type(loaded).__name__}")


def _load_asset_mesh(component: dict, target_size: float, assets_dir: Path) -> trimesh.Trimesh | None:
    asset_file = _resolve_asset_file(component, assets_dir)
    if asset_file is None:
        logger.warning("No asset mapping matched for component=%s; fallback box will be used", component)
        return None

    if not asset_file.exists():
        logger.warning("Mapped asset file is missing: %s; fallback box will be used", asset_file)
        return None

    try:
        loaded = trimesh.load(str(asset_file), force="scene")
        mesh = _extract_mesh(loaded)
        if mesh.is_empty:
            raise ValueError("loaded asset mesh is empty")

        # Force asset geometry to local origin before any scale/placement to avoid offset drift.
        mesh.vertices -= np.array(mesh.bounding_box.centroid, dtype=float)
        _apply_cyber_pbr(mesh)

        max_extent = float(np.max(mesh.extents))
        if max_extent <= 0:
            raise ValueError("loaded asset has non-positive extents")

        scale_factor = float(target_size) / max_extent
        mesh.apply_scale(scale_factor)
        return mesh
    except Exception as exc:
        logger.warning("Failed to load/scale asset for component=%s file=%s; fallback to box. reason=%s", component, asset_file, exc)
        return None


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
    assets_dir = _assets_dir()

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
        target_size = float(max(ext))

        angle = (2 * math.pi * index) / max(1, len(attachable))
        ring = index % 2
        ring_radius = explode_radius + ring * base_max_extent * 0.25
        x = center[0] + math.cos(angle) * ring_radius
        z = center[2] + math.sin(angle) * ring_radius
        y = center[1] + ((index % 3) - 1) * vertical_step
        position = np.array([x, y, z], dtype=float)

        mesh = _load_asset_mesh(component, target_size=target_size, assets_dir=assets_dir)
        if mesh is None:
            mesh = _create_fallback_box(ext, position)
        else:
            try:
                centroid = np.array(mesh.bounding_box.centroid, dtype=float)
                mesh.apply_translation(position - centroid)
            except Exception as exc:
                logger.warning("Failed to place asset mesh for component=%s; fallback to box. reason=%s", component, exc)
                mesh = _create_fallback_box(ext, position)

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
            "assetsDir": str(assets_dir),
        }
    )

    return {
        "outputPath": str(output_path),
        "stats": stats,
    }
