from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asyncaiflow_client import AsyncAiFlowClient, AsyncAiFlowConfig
from llm_client import GeminiJsonClient, LlmConfig
from prompts import REPAIR_PROMPT_TEMPLATE, SYSTEM_PROMPT_TEMPLATE
from schema_validator import DesignDslSchemaValidator

ACTION_TYPE = "nl_to_design_dsl"


@dataclass
class TranslatorConfig:
    max_retries: int = 3


class DesignDslTranslator:
    def __init__(
        self,
        llm_client: GeminiJsonClient,
        validator: DesignDslSchemaValidator,
        config: TranslatorConfig,
    ) -> None:
        self.llm_client = llm_client
        self.validator = validator
        self.config = config

    def translate(self, natural_language: str) -> tuple[dict[str, Any], list[str], bool, int]:
        risk = self._risk_flags(natural_language)

        if risk["non_garment"]:
            envelope = self._fallback_envelope(natural_language, reason="non-garment request")
            return envelope, [], True, 0

        user_prompt = self._build_user_prompt(natural_language)
        last_errors: list[str] = []
        raw_candidate: dict[str, Any] | None = None

        for attempt in range(1, self.config.max_retries + 1):
            response_obj = self.llm_client.complete_json(SYSTEM_PROMPT_TEMPLATE, user_prompt)
            raw_candidate = response_obj
            envelope_errors = self._validate_envelope(response_obj)
            if envelope_errors:
                last_errors = envelope_errors
                user_prompt = REPAIR_PROMPT_TEMPLATE.format(
                    errors="\\n".join(last_errors),
                    previous_json=json.dumps(response_obj, ensure_ascii=False),
                )
                continue

            dsl_errors = self.validator.validate_dsl(response_obj["dsl"])
            if not dsl_errors:
                if risk["physically_weird"]:
                    response_obj.setdefault("uncertainItems", []).append(
                        {
                            "targetPath": "dsl.constraints.optimization.objective",
                            "reason": "input may violate practical garment constraints",
                            "suggestion": "confirm wearability and production assumptions",
                        }
                    )
                return response_obj, [], False, attempt

            last_errors = dsl_errors
            user_prompt = REPAIR_PROMPT_TEMPLATE.format(
                errors="\\n".join(dsl_errors),
                previous_json=json.dumps(response_obj, ensure_ascii=False),
            )

        fallback = self._fallback_envelope(
            natural_language,
            reason="validation failed after retries",
        )
        if raw_candidate is not None:
            fallback["meta"]["lastInvalidCandidate"] = raw_candidate
        return fallback, last_errors, True, self.config.max_retries

    def _validate_envelope(self, response_obj: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not isinstance(response_obj, dict):
            return ["response is not object"]
        if "dsl" not in response_obj or not isinstance(response_obj["dsl"], dict):
            errors.append("missing object field: dsl")
        if "fieldMappings" not in response_obj or not isinstance(response_obj["fieldMappings"], list):
            errors.append("missing array field: fieldMappings")
        if "uncertainItems" not in response_obj or not isinstance(response_obj["uncertainItems"], list):
            errors.append("missing array field: uncertainItems")
        return errors

    def _build_user_prompt(self, natural_language: str) -> str:
        return (
            "Convert this garment design request to Design Schema v0.1 envelope JSON.\\n"
            "Input:\\n"
            f"{natural_language.strip()}"
        )

    def _risk_flags(self, natural_language: str) -> dict[str, bool]:
        text = natural_language.lower()
        text_compact = text.replace(" ", "").replace("-", "")
        garment_keywords = {
            "shirt",
            "tshirt",
            "tee",
            "t-shirt",
            "jacket",
            "coat",
            "dress",
            "pants",
            "skirt",
            "vest",
            "waistcoat",
            "sleeve",
            "collar",
            "garment",
            "clothing",
            "衣",
            "恤",
            "袖",
            "领",
            "服装",
            "上衣",
            "夹克",
            "外套",
            "马甲",
            "背心",
            "裙",
            "裤",
        }
        non_garment = not any((word in text) or (word in text_compact) for word in garment_keywords)

        weird_markers = {
            "anti-gravity",
            "levitate",
            "cannot exist",
            "infinite stretch",
            "永不破损",
            "违反物理",
            "无限拉伸",
            "反重力",
        }
        physically_weird = any(marker in text for marker in weird_markers)

        return {"non_garment": non_garment, "physically_weird": physically_weird}

    def _fallback_envelope(self, natural_language: str, reason: str) -> dict[str, Any]:
        # Safe fallback keeps workflow alive with a conservative, schema-valid minimal garment.
        return {
            "dsl": {
                "metadata": {
                    "schemaVersion": "0.1",
                    "designIntent": f"Fallback generated from request: {natural_language[:120]}",
                    "styleTags": ["fallback"],
                    "targetGarmentType": "other",
                    "globalToleranceMm": 2.0,
                    "units": "mm",
                },
                "components": [
                    {
                        "id": "FrontBody",
                        "name": "Front Body",
                        "category": "body",
                        "panelRole": "front",
                        "material": {
                            "textileType": "blend",
                            "blend": "Cotton 95 / Elastane 5",
                            "weightGsm": 180,
                            "elasticRecoveryPct": 30,
                            "shrinkagePct": 3,
                        },
                        "stretchProfile": {
                            "warpStretchPct": 12,
                            "weftStretchPct": 16,
                        },
                        "seamAllowanceMm": 8,
                    },
                    {
                        "id": "BackBody",
                        "name": "Back Body",
                        "category": "body",
                        "panelRole": "back",
                        "material": {
                            "textileType": "blend",
                            "blend": "Cotton 95 / Elastane 5",
                            "weightGsm": 180,
                            "elasticRecoveryPct": 30,
                            "shrinkagePct": 3,
                        },
                        "stretchProfile": {
                            "warpStretchPct": 12,
                            "weftStretchPct": 16,
                        },
                        "seamAllowanceMm": 8,
                    },
                ],
                "topology": [
                    {
                        "id": "S1",
                        "componentA": "FrontBody",
                        "componentB": "BackBody",
                        "seamType": "flat",
                        "seamLengthMm": 600,
                    }
                ],
                "constraints": {
                    "optimization": {
                        "objective": "balanced",
                        "targetUnitCost": 30,
                        "maxFabricWastePct": 15,
                    },
                    "processLimits": {
                        "maxOperationCount": 12,
                        "maxConstructionMinutes": 35,
                        "allowHandFinish": True,
                    },
                },
            },
            "fieldMappings": [
                {
                    "source": "fallback",
                    "targetPath": "dsl",
                    "confidence": 0.25,
                    "uncertain": True,
                    "reason": reason,
                }
            ],
            "uncertainItems": [
                {
                    "targetPath": "dsl.metadata.designIntent",
                    "reason": reason,
                    "suggestion": "clarify garment category, key components, and construction constraints",
                }
            ],
            "meta": {
                "fallbackUsed": True,
                "reason": reason,
            },
        }


def parse_design_prompt(payload_raw: str) -> str:
    if not payload_raw:
        return ""
    payload = json.loads(payload_raw)
    if not isinstance(payload, dict):
        return ""
    prompt = str(payload.get("prompt") or payload.get("designIntent") or payload.get("text") or "").strip()
    # Append style hints from options so the LLM can tailor the DSL accordingly
    options = payload.get("options")
    if isinstance(options, dict):
        style = str(options.get("style") or "").strip()
        if style and style not in prompt:
            prompt = f"{prompt}\n风格偏好: {style}"
    return prompt


def build_result_payload(envelope: dict[str, Any], errors: list[str], fallback_used: bool, attempts: int) -> dict[str, Any]:
    merged = dict(envelope)
    meta = dict(merged.get("meta") or {})
    meta.update(
        {
            "fallbackUsed": fallback_used,
            "attempts": attempts,
            "validationErrors": errors,
        }
    )
    merged["meta"] = meta
    return merged


def _start_lease_renewer(async_client: AsyncAiFlowClient, action_id: int, interval_seconds: float) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()

    def renew_loop() -> None:
        while not stop_event.wait(interval_seconds):
            try:
                async_client.renew_lease(action_id)
            except Exception:
                # Best effort only; scheduler remains source of truth.
                pass

    thread = threading.Thread(target=renew_loop, name=f"design-gpt-lease-renew-{action_id}", daemon=True)
    thread.start()
    return stop_event, thread


def run_worker() -> None:
    server_url = os.getenv("ASYNCAIFLOW_SERVER_BASE_URL", "http://localhost:8080")
    worker_id = os.getenv("ASYNCAIFLOW_WORKER_ID", "design-gpt-worker-py")
    capabilities = [cap.strip() for cap in os.getenv("ASYNCAIFLOW_CAPABILITIES", ACTION_TYPE).split(",") if cap.strip()]
    poll_interval_seconds = float(os.getenv("ASYNCAIFLOW_POLL_INTERVAL_SECONDS", "1.0"))

    schema_path = Path(os.getenv(
        "DESIGN_SCHEMA_PATH",
        str(Path(__file__).resolve().parents[2] / "src/main/resources/schema/design-schema-v0.1.json"),
    ))

    llm_api_key = os.getenv("GEMINI_API_KEY", "")
    llm_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    llm_temperature = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
    llm_timeout_seconds = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
    max_retries = int(os.getenv("DSL_TRANSLATE_MAX_RETRIES", "3"))

    if not llm_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for design-gpt-worker")

    schema_text = schema_path.read_text(encoding="utf-8")

    async_client = AsyncAiFlowClient(AsyncAiFlowConfig(server_url, worker_id, capabilities))
    llm_client = GeminiJsonClient(
        LlmConfig(
            api_key=llm_api_key,
            model=llm_model,
            temperature=llm_temperature,
            timeout_seconds=llm_timeout_seconds,
            response_schema_text=schema_text,
        )
    )
    validator = DesignDslSchemaValidator(schema_path)
    translator = DesignDslTranslator(llm_client, validator, TranslatorConfig(max_retries=max_retries))

    async_client.register_worker()

    while True:
        async_client.heartbeat()
        assignment = async_client.poll_action()
        if not assignment:
            time.sleep(poll_interval_seconds)
            continue

        action_type = assignment.get("type")
        action_id = assignment.get("actionId")
        payload_raw = assignment.get("payload") or ""

        if action_type != ACTION_TYPE:
            async_client.submit_result(
                action_id=action_id,
                status="FAILED",
                result={"reason": "unsupported action type", "actionType": action_type},
                error_message=f"unsupported action type: {action_type}",
            )
            continue

        try:
            prompt = parse_design_prompt(payload_raw)
            if not prompt:
                raise ValueError("payload must contain non-empty prompt")
            renew_interval_seconds = max(10.0, min(30.0, llm_timeout_seconds / 3.0))
            renew_stop, renew_thread = _start_lease_renewer(async_client, action_id, renew_interval_seconds)
            try:
                envelope, errors, fallback_used, attempts = translator.translate(prompt)
                result_payload = build_result_payload(envelope, errors, fallback_used, attempts)
                async_client.submit_result(
                    action_id=action_id,
                    status="SUCCEEDED",
                    result=result_payload,
                    error_message=None,
                )
            finally:
                renew_stop.set()
                renew_thread.join(timeout=1.0)
        except Exception as exc:
            async_client.submit_result(
                action_id=action_id,
                status="FAILED",
                result={"error": "dsl translation failed"},
                error_message=str(exc),
            )


if __name__ == "__main__":
    run_worker()
