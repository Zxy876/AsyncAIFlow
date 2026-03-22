from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class AsyncAiFlowConfig:
    server_base_url: str
    worker_id: str
    capabilities: list[str]


class AsyncAiFlowClient:
    def __init__(self, config: AsyncAiFlowConfig, timeout_seconds: int = 15) -> None:
        self.config = config
        self.base_url = config.server_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False

    def register_worker(self) -> None:
        self._post(
            "/worker/register",
            {"workerId": self.config.worker_id, "capabilities": self.config.capabilities},
        )

    def heartbeat(self) -> None:
        self._post("/worker/heartbeat", {"workerId": self.config.worker_id})

    def renew_lease(self, action_id: int) -> None:
        self._post(
            f"/action/{action_id}/renew-lease",
            {"workerId": self.config.worker_id},
        )

    def poll_action(self) -> dict[str, Any] | None:
        response = self.session.get(
            f"{self.base_url}/action/poll",
            params={"workerId": self.config.worker_id},
            timeout=self.timeout_seconds,
        )
        if response.status_code == 204 or not response.text.strip():
            return None
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            raise RuntimeError(payload.get("message", "poll failed"))
        return payload.get("data")

    def submit_result(self, action_id: int, status: str, result: dict[str, Any] | str, error_message: str | None) -> None:
        self._post(
            "/action/result",
            {
                "workerId": self.config.worker_id,
                "actionId": action_id,
                "status": status,
                "result": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                "errorMessage": error_message,
            },
        )

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}{path}",
            json=body,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            raise RuntimeError(payload.get("message", f"{path} failed"))
        return payload
