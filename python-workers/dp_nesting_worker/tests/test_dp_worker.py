from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geometry_extractor import extract_piece_specs, resolve_fabric_width_mm, resolve_gap_mm
from nesting_solver import solve_nesting
from worker import _extract_job, run_nesting_job


def _component(
    component_id: str,
    category: str,
    width_mm: int | None = None,
    height_mm: int | None = None,
    allow_rotation: bool | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "id": component_id,
        "name": component_id,
        "category": category,
        "panelRole": "front",
        "material": {"textileType": "blend", "blend": "Cotton 95 / Elastane 5", "weightGsm": 180},
        "stretchProfile": {"warpStretchPct": 10, "weftStretchPct": 15},
        "seamAllowanceMm": 8,
    }
    if width_mm is not None and height_mm is not None:
        payload["boundingBoxMm"] = {"width": width_mm, "height": height_mm}
    if allow_rotation is not None:
        payload["allowRotation"] = allow_rotation
    if extra:
        payload.update(extra)
    return payload


def _dsl(components: list[dict], fabric_width_mm: int = 1500, gap_mm: int = 10) -> dict:
    return {
        "metadata": {
            "schemaVersion": "0.1",
            "designIntent": "nesting test",
            "globalToleranceMm": 2.0,
            "units": "mm",
        },
        "components": components,
        "topology": [],
        "constraints": {
            "optimization": {
                "objective": "material_min",
                "fabricWidthMm": fabric_width_mm,
                "layoutGapMm": gap_mm,
            }
        },
    }


def _payload(dsl: dict, topology_valid: bool = True, **overrides: object) -> str:
    payload = {
        "taskId": "task_dp_001",
        "dsl": dsl,
        "topologyReport": {"valid": topology_valid},
    }
    payload.update(overrides)
    return json.dumps(payload)


class GeometryExtractionTests(unittest.TestCase):

    def test_extracts_explicit_bounding_box(self):
        dsl = _dsl([_component("FrontBody", "body", 600, 800)])
        pieces, warnings = extract_piece_specs(dsl)
        self.assertEqual(len(warnings), 0)
        self.assertEqual(pieces[0].width_mm, 600)
        self.assertEqual(pieces[0].height_mm, 800)
        self.assertEqual(pieces[0].dimension_source, "boundingBoxMm")

    def test_extracts_polygon_bounding_box(self):
        polygon_component = _component(
            "Pocket", "pocket", extra={"outlinePointsMm": [{"x": 0, "y": 0}, {"x": 120, "y": 0}, {"x": 120, "y": 200}]}
        )
        dsl = _dsl([polygon_component])
        pieces, warnings = extract_piece_specs(dsl)
        self.assertEqual(len(warnings), 0)
        self.assertEqual((pieces[0].width_mm, pieces[0].height_mm), (120, 200))
        self.assertEqual(pieces[0].dimension_source, "outlinePointsMm")

    def test_falls_back_to_category_estimate(self):
        dsl = _dsl([_component("SleeveA", "sleeve")])
        pieces, warnings = extract_piece_specs(dsl)
        self.assertEqual((pieces[0].width_mm, pieces[0].height_mm), (280, 620))
        self.assertEqual(pieces[0].dimension_source, "category-estimate")
        self.assertEqual(warnings[0]["code"], "ESTIMATED_BOUNDING_BOX")

    def test_grainline_disables_rotation(self):
        dsl = _dsl([_component("FrontBody", "body", 600, 800, extra={"grainline": {"axis": "vertical"}})])
        pieces, _ = extract_piece_specs(dsl)
        self.assertFalse(pieces[0].allow_rotation)

    def test_resolves_fabric_width_and_gap(self):
        dsl = _dsl([_component("FrontBody", "body", 500, 700)], fabric_width_mm=1350, gap_mm=18)
        payload = {"dsl": dsl}
        self.assertEqual(resolve_fabric_width_mm(payload, dsl), 1350)
        self.assertEqual(resolve_gap_mm(payload, dsl), 18)


class NestingSolverTests(unittest.TestCase):

    def test_two_pieces_share_one_row(self):
        dsl = _dsl([
            _component("A", "body", 700, 500),
            _component("B", "body", 700, 400),
        ], fabric_width_mm=1500, gap_mm=10)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1500, gap_mm=10)
        self.assertEqual(plan.consumed_length_mm, 500)
        self.assertEqual(len(plan.rows), 1)

    def test_width_overflow_creates_second_row(self):
        dsl = _dsl([
            _component("A", "body", 800, 500, allow_rotation=False),
            _component("B", "body", 800, 400, allow_rotation=False),
        ], fabric_width_mm=1500, gap_mm=10)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1500, gap_mm=10)
        self.assertEqual(plan.consumed_length_mm, 910)
        self.assertEqual(len(plan.rows), 2)

    def test_rotation_reduces_consumed_length(self):
        dsl = _dsl([
            _component("Body", "body", 1000, 700, allow_rotation=False),
            _component("PanelA", "other", 900, 300, allow_rotation=True),
            _component("PanelB", "other", 900, 300, allow_rotation=True),
        ], fabric_width_mm=1300, gap_mm=0)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1300, gap_mm=0)
        self.assertEqual(plan.consumed_length_mm, 1200)
        rotated = {placement.component_id: placement.rotated for placement in plan.placements}
        self.assertTrue(rotated["PanelA"] or rotated["PanelB"])

    def test_locked_rotation_prevents_turning(self):
        dsl = _dsl([
            _component("Body", "body", 1000, 700, allow_rotation=False),
            _component("PanelA", "other", 900, 300, allow_rotation=False),
            _component("PanelB", "other", 900, 300, allow_rotation=False),
        ], fabric_width_mm=1300, gap_mm=0)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1300, gap_mm=0)
        self.assertEqual(plan.consumed_length_mm, 1300)
        rotated = {placement.component_id: placement.rotated for placement in plan.placements}
        self.assertFalse(rotated["PanelA"])
        self.assertFalse(rotated["PanelB"])
        row_indices = {placement.component_id: placement.row_index for placement in plan.placements}
        self.assertNotEqual(row_indices["PanelA"], row_indices["PanelB"])

    def test_exact_dp_finds_best_partition(self):
        dsl = _dsl([
            _component("A", "body", 900, 500),
            _component("B", "body", 600, 500),
            _component("C", "other", 750, 200),
            _component("D", "other", 750, 200),
        ], fabric_width_mm=1500, gap_mm=0)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1500, gap_mm=0)
        self.assertEqual(plan.consumed_length_mm, 700)
        self.assertEqual(len(plan.rows), 2)

    def test_placements_do_not_overlap(self):
        dsl = _dsl([
            _component("A", "body", 700, 400),
            _component("B", "body", 600, 300),
            _component("C", "other", 300, 200),
            _component("D", "other", 200, 200),
        ], fabric_width_mm=1400, gap_mm=10)
        pieces, _ = extract_piece_specs(dsl)
        plan = solve_nesting(pieces, fabric_width_mm=1400, gap_mm=10)
        placements = list(plan.placements)
        for index, left in enumerate(placements):
            for right in placements[index + 1:]:
                overlap_x = left.x_mm < right.x_mm + right.width_mm and right.x_mm < left.x_mm + left.width_mm
                overlap_y = left.y_mm < right.y_mm + right.height_mm and right.y_mm < left.y_mm + left.height_mm
                self.assertFalse(overlap_x and overlap_y)

    def test_piece_wider_than_fabric_raises(self):
        dsl = _dsl([_component("A", "body", 1600, 500, allow_rotation=False)], fabric_width_mm=1500, gap_mm=0)
        pieces, _ = extract_piece_specs(dsl)
        with self.assertRaises(ValueError):
            solve_nesting(pieces, fabric_width_mm=1500, gap_mm=0)


class WorkerPayloadTests(unittest.TestCase):

    def test_extract_job_from_wrapper(self):
        dsl = _dsl([_component("FrontBody", "body", 600, 800)])
        job = _extract_job(_payload(dsl))
        self.assertIsNotNone(job)
        self.assertIn("dsl", job)

    def test_extract_job_from_bare_dsl(self):
        dsl = _dsl([_component("FrontBody", "body", 600, 800)])
        job = _extract_job(json.dumps(dsl))
        self.assertIsNotNone(job)
        self.assertIn("dsl", job)

    def test_extract_job_rejects_invalid_json(self):
        self.assertIsNone(_extract_job("{bad json"))

    def test_invalid_topology_report_blocks_nesting(self):
        dsl = _dsl([_component("FrontBody", "body", 600, 800)])
        with self.assertRaises(ValueError):
            run_nesting_job(_payload(dsl, topology_valid=False))


class WorkerIntegrationTests(unittest.TestCase):

    def test_result_contains_required_fields(self):
        dsl = _dsl([
            _component("FrontBody", "body", 700, 800),
            _component("BackBody", "body", 700, 780),
            _component("LeftSleeve", "sleeve", 280, 620, allow_rotation=False),
            _component("RightSleeve", "sleeve", 280, 620, allow_rotation=False),
        ], fabric_width_mm=1500, gap_mm=10)
        result = run_nesting_job(_payload(dsl))
        self.assertTrue(result["valid"])
        self.assertIn("consumedLengthMm", result)
        self.assertIn("utilization", result)
        self.assertEqual(len(result["placements"]), 4)
        self.assertEqual(result["meta"]["dslVersion"], "0.1")

    def test_result_is_json_serializable(self):
        dsl = _dsl([
            _component("FrontBody", "body", 700, 800),
            _component("Pocket", "pocket"),
        ])
        result = run_nesting_job(_payload(dsl, fabricWidthMm=1200, gapMm=0))
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertIn("consumedLengthMm", encoded)

    def test_payload_overrides_fabric_width(self):
        dsl = _dsl([
            _component("A", "body", 700, 500, allow_rotation=False),
            _component("B", "body", 700, 500, allow_rotation=False),
        ], fabric_width_mm=1500, gap_mm=10)
        result = run_nesting_job(_payload(dsl, fabricWidthMm=1000, gapMm=0))
        self.assertEqual(result["fabricWidthMm"], 1000)
        self.assertEqual(result["consumedLengthMm"], 1000)

    def test_estimated_geometry_warning_survives_to_result(self):
        dsl = _dsl([_component("Pocket", "pocket")])
        result = run_nesting_job(_payload(dsl))
        self.assertEqual(result["warnings"][0]["code"], "ESTIMATED_BOUNDING_BOX")


if __name__ == "__main__":
    unittest.main()