from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

FORBIDDEN_3D_KEYS = {
    "vertices",
    "faces",
    "meshes",
    "mesh",
    "uv",
    "texturemap",
    "gltf",
    "glb",
    "obj",
    "pointcloud",
}


class DesignDslSchemaValidator:
    def __init__(self, schema_path: Path) -> None:
        self.schema_path = schema_path
        with schema_path.open("r", encoding="utf-8") as fp:
            schema = json.load(fp)
        self.validator = Draft202012Validator(schema)

    def validate_dsl(self, dsl: dict[str, Any]) -> list[str]:
        errors = [
            f"{err.json_path}: {err.message}"
            for err in sorted(self.validator.iter_errors(dsl), key=lambda e: e.path)
        ]
        errors.extend(self._semantic_errors(dsl))
        errors.extend(self._forbidden_3d_errors(dsl))
        return errors

    def _semantic_errors(self, dsl: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        components = dsl.get("components", [])
        topology = dsl.get("topology", [])
        if not isinstance(components, list) or not isinstance(topology, list):
            return ["components/topology must be arrays"]

        component_ids = [item.get("id") for item in components if isinstance(item, dict)]
        id_set = {cid for cid in component_ids if isinstance(cid, str) and cid}
        if len(component_ids) != len(id_set):
            errors.append("components contain duplicate or invalid id")

        degree: dict[str, int] = {cid: 0 for cid in id_set}
        seam_ids: set[str] = set()
        for i, edge in enumerate(topology):
            if not isinstance(edge, dict):
                errors.append(f"topology[{i}] must be object")
                continue
            seam_id = edge.get("id")
            if isinstance(seam_id, str) and seam_id:
                if seam_id in seam_ids:
                    errors.append(f"duplicate topology id: {seam_id}")
                seam_ids.add(seam_id)

            a = edge.get("componentA")
            b = edge.get("componentB")
            if a not in id_set:
                errors.append(f"topology[{i}] references unknown componentA: {a}")
            if b not in id_set:
                errors.append(f"topology[{i}] references unknown componentB: {b}")
            if a == b and isinstance(a, str):
                errors.append(f"topology[{i}] self-loop not allowed: {a}")

            if isinstance(a, str) and a in degree:
                degree[a] += 1
            if isinstance(b, str) and b in degree:
                degree[b] += 1

        isolated = [cid for cid, cnt in degree.items() if cnt == 0]
        if isolated:
            errors.append("isolated components: " + ", ".join(sorted(isolated)))

        return errors

    def _forbidden_3d_errors(self, obj: Any) -> list[str]:
        errors: list[str] = []

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    normalized = key.lower()
                    if normalized in FORBIDDEN_3D_KEYS:
                        errors.append(f"{path}.{key}: forbidden 3D field")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for idx, value in enumerate(node):
                    walk(value, f"{path}[{idx}]")

        walk(obj, "$")
        return errors
