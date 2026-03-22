"""
worker.py
~~~~~~~~~
BFS Topology Validation Worker — AsyncAIFlow action type: topology_validate

This worker:
  1. Registers itself with the AsyncAIFlow runtime.
  2. Polls for topology_validate actions.
  3. Extracts the DSL from the action payload (injected from upstream
     nl_to_design_dsl result via the scheduler's payload injection engine,
     or supplied directly as {"dsl": {...}}).
  4. Runs BFS topology analysis (graph_builder + bfs_analyzer).
  5. Submits the structured TopologyReport as the action result.

Environment variables (all optional, shown with defaults)
----------------------------------------------------------
  ASYNCAIFLOW_SERVER_BASE_URL   = http://localhost:8080
  ASYNCAIFLOW_WORKER_ID         = bfs-topology-worker-py
  ASYNCAIFLOW_CAPABILITIES      = topology_validate
  ASYNCAIFLOW_POLL_INTERVAL_SECONDS = 1.0

Wiring into the DAG (Java side)
--------------------------------
The action payload is built in DesignTaskServiceImpl with inject:
  {
    "taskId": "<task-id>",
    "inject": {
      "dsl": "$.upstreamByType.nl_to_design_dsl.result.dsl"
    }
  }
After scheduler injection the worker receives:
  {
    "taskId": "<task-id>",
    "dsl": { ...full Design Schema v0.1 object... }
  }
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from asyncaiflow_client import AsyncAiFlowClient, AsyncAiFlowConfig
from bfs_analyzer import analyze
from graph_builder import build_graph

ACTION_TYPE = "topology_validate"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bfs-topology-worker")


# ─────────────────────────────────────────────────────────────────────────────
# Payload extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_dsl(payload_raw: str) -> dict[str, Any] | None:
    """
    Extract the DSL object from an action payload JSON string.

    Accepted shapes:
      • {"dsl": {...}}          — explicit wrapper (injected by scheduler)
      • {"components": [...], "topology": [...], ...}  — bare DSL at root
    """
    if not payload_raw or not payload_raw.strip():
        return None
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    # Prefer explicit "dsl" key (scheduler injection sets this)
    dsl = payload.get("dsl")
    if isinstance(dsl, dict):
        return dsl

    # Fall back: treat root as bare DSL if it looks like one
    if "components" in payload and "topology" in payload:
        return payload

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main worker loop
# ─────────────────────────────────────────────────────────────────────────────

def run_worker() -> None:
    server_url = os.getenv("ASYNCAIFLOW_SERVER_BASE_URL", "http://localhost:8080")
    worker_id = os.getenv("ASYNCAIFLOW_WORKER_ID", "bfs-topology-worker-py")
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
                dsl = _extract_dsl(payload_raw)
                if dsl is None:
                    raise ValueError(
                        "payload must contain a 'dsl' object with 'components' and 'topology'"
                    )

                dsl_version = (dsl.get("metadata") or {}).get("schemaVersion", "unknown")
                build_result = build_graph(dsl)
                report = analyze(build_result, dsl_version=dsl_version)

                logger.info(
                    "action_id=%s valid=%s errors=%d warnings=%d "
                    "components=%d seams=%d connected_components=%d",
                    action_id,
                    report.valid,
                    len(report.errors),
                    len(report.warnings),
                    report.component_count,
                    report.seam_count,
                    report.connected_components,
                )

                client.submit_result(
                    action_id=action_id,
                    status="SUCCEEDED",
                    result=report.to_dict(),
                    error_message=None,
                )

            except Exception as exc:
                logger.exception("Topology analysis failed for action_id=%s", action_id)
                client.submit_result(
                    action_id=action_id,
                    status="FAILED",
                    result={"error": "topology analysis failed"},
                    error_message=str(exc),
                )

        except Exception as exc:
            logger.warning("Worker loop error: %s — retrying in %.1fs", exc, poll_interval)
            time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker()
