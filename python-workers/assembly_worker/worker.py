from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from assembly_builder import build_assembly_scene
from asyncaiflow_client import AsyncAiFlowClient, AsyncAiFlowConfig

ACTION_TYPE = "3d_assembly_render"
WORKER_VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("assembly-worker")


def _read_payload(payload_raw: str) -> dict[str, Any]:
    if not payload_raw or not payload_raw.strip():
        raise ValueError("payload is empty")
    payload = json.loads(payload_raw)
    if not isinstance(payload, dict):
        raise ValueError("payload must be JSON object")
    return payload


def _resolve_dsl(payload: dict[str, Any]) -> dict[str, Any]:
    dsl = payload.get("dsl")
    if isinstance(dsl, dict):
        return dsl
    return {}


def _resolve_output_dir(payload: dict[str, Any]) -> Path:
    output_dir = payload.get("outputDir") or os.getenv("ASSEMBLY_OUTPUT_DIR") or "/tmp/asyncaiflow-assembly-output"
    return Path(str(output_dir)).expanduser().resolve()


def _resolve_base_model_path(payload: dict[str, Any]) -> str | None:
    candidate = payload.get("baseModelPath")
    if not candidate:
        return None
    return str(candidate)


def _join_http_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _build_model_url(payload: dict[str, Any], server_url: str, output_path: str) -> str:
    explicit = payload.get("outputModelUrl")
    if explicit:
        return str(explicit)
    file_name = Path(output_path).name
    return _join_http_url(server_url, f"models/{file_name}")


def process_assembly(payload_raw: str, server_url: str) -> dict[str, Any]:
    payload = _read_payload(payload_raw)
    task_id = str(payload.get("taskId") or "unknown_task")

    dsl = _resolve_dsl(payload)
    base_model_path = _resolve_base_model_path(payload)
    output_dir = _resolve_output_dir(payload)

    assembly = build_assembly_scene(
        task_id=task_id,
        dsl=dsl,
        base_model_path=base_model_path,
        output_dir=output_dir,
    )

    output_path = assembly["outputPath"]
    model_url = _build_model_url(payload, server_url, output_path)
    thumbnail_url = payload.get("outputThumbnailUrl")

    result = {
        "taskId": task_id,
        "modelUrl": model_url,
        "thumbnailUrl": thumbnail_url,
        "assemblyPath": output_path,
        "baseModelPath": base_model_path,
        "meta": {
            "workerVersion": WORKER_VERSION,
            "actionType": ACTION_TYPE,
            "stats": assembly["stats"],
        },
    }
    return result


def run_worker() -> None:
    server_url = os.getenv("ASYNCAIFLOW_SERVER_BASE_URL", "http://localhost:8080")
    worker_id = os.getenv("ASYNCAIFLOW_WORKER_ID", "assembly-worker-py")
    capabilities = [
        cap.strip()
        for cap in os.getenv("ASYNCAIFLOW_CAPABILITIES", ACTION_TYPE).split(",")
        if cap.strip()
    ]
    poll_interval = float(os.getenv("ASYNCAIFLOW_POLL_INTERVAL_SECONDS", "1.0"))

    client = AsyncAiFlowClient(AsyncAiFlowConfig(server_url, worker_id, capabilities))
    client.register_worker()
    logger.info(
        "Registered worker_id=%s capabilities=%s server=%s",
        worker_id,
        capabilities,
        server_url,
    )

    while True:
        try:
            client.heartbeat()
            assignment = client.poll_action()
            if not assignment:
                time.sleep(poll_interval)
                continue

            action_type = assignment.get("type")
            action_id = assignment.get("actionId")
            payload_raw = assignment.get("payload") or ""

            if action_type != ACTION_TYPE:
                client.submit_result(
                    action_id=action_id,
                    status="FAILED",
                    result={"reason": "unsupported action type", "actionType": action_type},
                    error_message=f"unsupported action type: {action_type}",
                )
                continue

            logger.info("Claimed action_id=%s type=%s", action_id, action_type)

            try:
                result = process_assembly(payload_raw, server_url)
                logger.info(
                    "action_id=%s assembled model=%s modules=%s",
                    action_id,
                    result["assemblyPath"],
                    result["meta"]["stats"].get("moduleCount"),
                )
                client.submit_result(
                    action_id=action_id,
                    status="SUCCEEDED",
                    result=result,
                    error_message=None,
                )
            except Exception as exc:
                logger.exception("assembly failed for action_id=%s", action_id)
                client.submit_result(
                    action_id=action_id,
                    status="FAILED",
                    result={"error": "assembly failed"},
                    error_message=str(exc),
                )

        except Exception as exc:
            logger.warning("Worker loop error: %s - retrying in %.1fs", exc, poll_interval)
            time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()
