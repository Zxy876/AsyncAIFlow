from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from schema_validator import DesignDslSchemaValidator
from worker import DesignDslTranslator, TranslatorConfig


class FakeLlmClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str):
        self.calls += 1
        if not self.responses:
            raise RuntimeError("no more responses")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "src/main/resources/schema/design-schema-v0.1.json"


def _valid_envelope() -> dict:
    return {
        "dsl": {
            "metadata": {
                "schemaVersion": "0.1",
                "designIntent": "Minimal T-shirt",
                "styleTags": ["minimal"],
                "targetGarmentType": "tshirt",
                "globalToleranceMm": 2,
                "units": "mm",
            },
            "components": [
                {
                    "id": "FrontBody",
                    "name": "Front Body",
                    "category": "body",
                    "panelRole": "front",
                    "material": {
                        "textileType": "cotton",
                        "blend": "Cotton 100",
                        "weightGsm": 180,
                        "elasticRecoveryPct": 15,
                        "shrinkagePct": 3,
                    },
                    "stretchProfile": {"warpStretchPct": 8, "weftStretchPct": 10},
                    "seamAllowanceMm": 8,
                },
                {
                    "id": "BackBody",
                    "name": "Back Body",
                    "category": "body",
                    "panelRole": "back",
                    "material": {
                        "textileType": "cotton",
                        "blend": "Cotton 100",
                        "weightGsm": 180,
                        "elasticRecoveryPct": 15,
                        "shrinkagePct": 3,
                    },
                    "stretchProfile": {"warpStretchPct": 8, "weftStretchPct": 10},
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
                    "maxFabricWastePct": 12,
                },
                "processLimits": {
                    "maxOperationCount": 10,
                    "maxConstructionMinutes": 30,
                    "allowHandFinish": True,
                },
            },
        },
        "fieldMappings": [
            {
                "source": "minimal tshirt",
                "targetPath": "dsl.metadata.designIntent",
                "confidence": 0.92,
                "uncertain": False,
                "reason": "direct match",
            }
        ],
        "uncertainItems": [],
    }


class DesignWorkerTests(TestCase):
    def setUp(self):
        self.validator = DesignDslSchemaValidator(_schema_path())

    def test_success_on_first_attempt(self):
        llm = FakeLlmClient([_valid_envelope()])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("设计一件极简 T 恤")

        self.assertFalse(fallback)
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 1)
        self.assertEqual(result["dsl"]["metadata"]["schemaVersion"], "0.1")

    def test_auto_repair_retry(self):
        bad = _valid_envelope()
        bad["dsl"]["metadata"]["schemaVersion"] = "9.9"
        llm = FakeLlmClient([bad, _valid_envelope()])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("设计一件极简 T 恤")

        self.assertFalse(fallback)
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 2)
        self.assertEqual(result["dsl"]["metadata"]["schemaVersion"], "0.1")

    def test_non_garment_request_triggers_fallback(self):
        llm = FakeLlmClient([_valid_envelope()])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("帮我设计一个火星基地供电系统")

        self.assertTrue(fallback)
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 0)
        self.assertGreaterEqual(len(result.get("uncertainItems", [])), 1)

    def test_vest_prompt_is_treated_as_garment(self):
        llm = FakeLlmClient([_valid_envelope()])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("设计一件不对称的机能风马甲")

        self.assertFalse(fallback)
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 1)
        self.assertEqual(result["dsl"]["metadata"]["schemaVersion"], "0.1")

    def test_physics_weird_prompt_marks_uncertainty(self):
        llm = FakeLlmClient([_valid_envelope()])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("设计一件反重力且无限拉伸的夹克")

        self.assertFalse(fallback)
        self.assertEqual(errors, [])
        self.assertEqual(attempts, 1)
        self.assertGreaterEqual(len(result.get("uncertainItems", [])), 1)

    def test_fallback_after_retries_exhausted(self):
        invalid = _valid_envelope()
        invalid["dsl"]["components"][0]["material"].pop("blend")
        llm = FakeLlmClient([invalid, invalid, invalid])
        translator = DesignDslTranslator(llm, self.validator, TranslatorConfig(max_retries=3))

        result, errors, fallback, attempts = translator.translate("设计一件基础上衣")

        self.assertTrue(fallback)
        self.assertEqual(attempts, 3)
        self.assertGreater(len(errors), 0)
        self.assertIn("meta", result)
        self.assertTrue(result["meta"].get("fallbackUsed"))


class ValidatorDefenseTests(TestCase):
    def test_forbidden_3d_field_is_rejected(self):
        validator = DesignDslSchemaValidator(_schema_path())
        envelope = _valid_envelope()
        envelope["dsl"]["meshes"] = [{"id": "m1"}]

        errors = validator.validate_dsl(envelope["dsl"])
        merged = "\\n".join(errors)
        self.assertIn("forbidden 3D field", merged)
