from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from asyncaiflow_client import AsyncAiFlowClient, AsyncAiFlowConfig
from mesh_cleaner import MeshCleanConfig, clean_scan_to_glb

ACTION_TYPE = "process_raw_scan"
WORKER_VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scan-processing-worker")


def _read_payload(payload_raw: str) -> dict[str, Any]:
    if not payload_raw or not payload_raw.strip():
        raise ValueError("payload is empty")
    payload = json.loads(payload_raw)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def _resolve_input_mesh(payload: dict[str, Any]) -> Path:
    scan = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    candidate = (
        scan.get("rawModelPath")
        or scan.get("inputPath")
        or payload.get("rawModelPath")
        or payload.get("inputPath")
    )
    if not candidate:
        raise ValueError("payload missing raw model path (scan.rawModelPath / inputPath)")
    path = Path(str(candidate)).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"raw scan file not found: {path}")
    return path


def _resolve_output_glb(payload: dict[str, Any], input_path: Path) -> Path:
    scan = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    explicit_output = (
        scan.get("outputGlbPath")
        or scan.get("outputPath")
        or payload.get("outputGlbPath")
        or payload.get("outputPath")
    )
    if explicit_output:
        return Path(str(explicit_output)).expanduser().resolve()

    output_dir = (
        scan.get("outputDir")
        or payload.get("outputDir")
        or os.getenv("SCAN_OUTPUT_DIR")
        or str(input_path.parent)
    )
    output_root = Path(str(output_dir)).expanduser().resolve()
    return output_root / f"{input_path.stem}.web.glb"


def _join_http_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _build_model_url(payload: dict[str, Any], scan: dict[str, Any], server_url: str, output_path: Path) -> str:
    explicit = scan.get("outputModelUrl") or payload.get("outputModelUrl")
    if explicit:
        return str(explicit)
    return _join_http_url(server_url, f"scan-models/{output_path.name}")


def process_raw_scan(payload_raw: str, server_url: str) -> dict[str, Any]:
    payload = _read_payload(payload_raw)
    input_mesh = _resolve_input_mesh(payload)
    output_glb = _resolve_output_glb(payload, input_mesh)

    scan = payload.get("scan") if isinstance(payload.get("scan"), dict) else {}
    target_faces = int(scan.get("targetFaces") or payload.get("targetFaces") or 20000)
    min_diameter_pct = float(
        scan.get("isolatedPieceMinDiameterPct")
        or payload.get("isolatedPieceMinDiameterPct")
        or 3.0
    )

    stats = clean_scan_to_glb(
        input_path=input_mesh,
        output_path=output_glb,
        config=MeshCleanConfig(
            target_faces=target_faces,
            isolated_piece_min_diameter_pct=min_diameter_pct,
        ),
    )

    actual_output_path = Path(stats["outputPath"]).expanduser().resolve()

    model_url = _build_model_url(payload, scan, server_url, actual_output_path)

    return {
        "valid": True,
        "modelUrl": model_url,
        "glbPath": str(actual_output_path),
        "scanStats": stats,
        "meta": {
            "workerVersion": WORKER_VERSION,
            "actionType": ACTION_TYPE,
        },
    }


def run_worker() -> None:
    server_url = os.getenv("ASYNCAIFLOW_SERVER_BASE_URL", "http://localhost:8080")
    worker_id = os.getenv("ASYNCAIFLOW_WORKER_ID", "scan-processing-worker-py")
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
                result = process_raw_scan(payload_raw, server_url)
                logger.info(
                    "action_id=%s output=%s faces_in=%s faces_out=%s",
                    action_id,
                    result["glbPath"],
                    result["scanStats"]["inputFaces"],
                    result["scanStats"]["outputFaces"],
                )
                client.submit_result(
                    action_id=action_id,
                    status="SUCCEEDED",
                    result=result,
                    error_message=None,
                )
            except Exception as exc:
                logger.exception("scan processing failed for action_id=%s", action_id)
                client.submit_result(
                    action_id=action_id,
                    status="FAILED",
                    result={"error": "scan processing failed"},
                    error_message=str(exc),
                )

        except Exception as exc:
            logger.warning("Worker loop error: %s - retrying in %.1fs", exc, poll_interval)
            time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()
