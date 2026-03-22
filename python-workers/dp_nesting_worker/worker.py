from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from asyncaiflow_client import AsyncAiFlowClient, AsyncAiFlowConfig
from geometry_extractor import extract_piece_specs, resolve_fabric_width_mm, resolve_gap_mm
from nesting_solver import solve_nesting

ACTION_TYPE = "dp_nesting"
WORKER_VERSION = "0.1.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dp-nesting-worker")


def _extract_job(payload_raw: str) -> dict[str, Any] | None:
    if not payload_raw or not payload_raw.strip():
        return None
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "dsl" in payload and isinstance(payload["dsl"], dict):
        return payload
    if "components" in payload and "topology" in payload:
        return {"dsl": payload}
    return None


def run_nesting_job(payload_raw: str) -> dict[str, Any]:
    job = _extract_job(payload_raw)
    if job is None:
        raise ValueError("payload must contain a 'dsl' object with components and topology")

    dsl = job["dsl"]
    topology_report = job.get("topologyReport")
    if isinstance(topology_report, dict) and topology_report.get("valid") is False:
        raise ValueError("topology validation failed upstream; nesting will not run on invalid DSL")

    dsl_version = (dsl.get("metadata") or {}).get("schemaVersion", "unknown")
    pieces, warnings = extract_piece_specs(dsl)
    fabric_width_mm = resolve_fabric_width_mm(job, dsl)
    gap_mm = resolve_gap_mm(job, dsl)
    plan = solve_nesting(pieces, fabric_width_mm=fabric_width_mm, gap_mm=gap_mm)

    consumed_length_mm = plan.consumed_length_mm
    total_part_area_mm2 = sum(piece.area_mm2 for piece in pieces)
    bounding_area_mm2 = consumed_length_mm * fabric_width_mm
    utilization = 0.0 if bounding_area_mm2 == 0 else total_part_area_mm2 / bounding_area_mm2

    placements = [placement.to_dict() for placement in sorted(plan.placements, key=lambda item: item.component_id)]
    rows = []
    for row_index, row in enumerate(plan.rows):
        rows.append(
            {
                "rowIndex": row_index,
                "heightMm": row.row_height_mm,
                "widthMm": row.row_width_mm,
                "componentIds": [item.component_id for item in row.items],
            }
        )

    return {
        "valid": True,
        "fabricWidthMm": fabric_width_mm,
        "consumedLengthMm": consumed_length_mm,
        "utilization": round(utilization, 6),
        "totalPartAreaMm2": total_part_area_mm2,
        "boundingAreaMm2": bounding_area_mm2,
        "placements": placements,
        "rows": rows,
        "warnings": warnings,
        "meta": {
            "workerVersion": WORKER_VERSION,
            "dslVersion": dsl_version,
            "algorithm": plan.algorithm,
            "pieceCount": len(pieces),
            "gapMm": gap_mm,
            "estimatedPieceCount": sum(1 for piece in pieces if piece.dimension_source == "category-estimate"),
            "topologyValid": True if not isinstance(topology_report, dict) else bool(topology_report.get("valid", True)),
        },
    }


def run_worker() -> None:
    server_url = os.getenv("ASYNCAIFLOW_SERVER_BASE_URL", "http://localhost:8080")
    worker_id = os.getenv("ASYNCAIFLOW_WORKER_ID", "dp-nesting-worker-py")
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
        worker_id, capabilities, server_url,
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
                result = run_nesting_job(payload_raw)
                logger.info(
                    "action_id=%s consumed_length_mm=%s utilization=%.4f piece_count=%d algorithm=%s",
                    action_id,
                    result["consumedLengthMm"],
                    result["utilization"],
                    result["meta"]["pieceCount"],
                    result["meta"]["algorithm"],
                )
                client.submit_result(
                    action_id=action_id,
                    status="SUCCEEDED",
                    result=result,
                    error_message=None,
                )
            except Exception as exc:
                logger.exception("Nesting failed for action_id=%s", action_id)
                client.submit_result(
                    action_id=action_id,
                    status="FAILED",
                    result={"error": "nesting failed"},
                    error_message=str(exc),
                )

        except Exception as exc:
            logger.warning("Worker loop error: %s - retrying in %.1fs", exc, poll_interval)
            time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()