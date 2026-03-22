"""
test_bfs_worker.py
~~~~~~~~~~~~~~~~~~
Comprehensive unit tests for the BFS Topology Worker.

Test matrix:
  GraphBuilderTests
    test_build_graph_nodes_and_edges        – correct vertex/edge counts
    test_build_graph_captures_self_loop     – self-loop flagged, NOT in graph
    test_build_graph_captures_unknown_ref   – unknown component reference flagged
    test_build_graph_captures_dup_seam_id   – duplicate seam ID flagged

  AnalyzerHappyPathTests
    test_valid_tshirt_no_errors             – standard T-shirt, fully connected
    test_minimal_two_component_dsl_valid    – smallest possible valid DSL

  IsolatedNodeTests
    test_isolated_left_sleeve_is_error      – isolated sleeve → ISOLATED_COMPONENT error
    test_repair_hints_mention_isolated_node – repair hint references the stuck component
    test_all_isolated_counted               – multiple isolated nodes all reported

  MultipleComponentTests
    test_two_disjoint_garments_warning      – top + pants with no bridge → warning, still valid
    test_disjoint_with_orphan_group         – group with no body node → UNREACHABLE repair hint
    test_bfs_reachability_bodyless_cc       – pocket pair unreachable from body BFS

  PreGraphErrorTests
    test_self_loop_seam_is_error            – seam A→A → SELF_LOOP_SEAM error
    test_unknown_component_ref_is_error     – seam to "Ghost" → UNKNOWN_COMPONENT_REF error
    test_duplicate_seam_id_is_error         – same seam ID twice → DUPLICATE_SEAM_ID error

  SymmetryTests
    test_asymmetric_pair_produces_warning   – LeftSleeve without RightSleeve → warning
    test_symmetric_pair_no_warning          – LeftSleeve + RightSleeve → no asymmetry warning

  Neo4jExporterTests
    test_cypher_contains_all_node_merges    – every component ID appears as MERGE node
    test_cypher_contains_seam_relationships – SEAM relationship for every edge
    test_cypher_escapes_single_quotes       – apostrophe in name escaped properly
    test_cypher_skips_self_loop_edges       – self-loop edges not emitted as relationships

  WorkerPayloadTests
    test_extract_dsl_from_wrapper           – {"dsl": {...}} shape
    test_extract_dsl_from_bare_root         – bare DSL at root
    test_extract_dsl_returns_none_on_empty  – empty/invalid payload
"""
from __future__ import annotations

import sys
import os
import unittest

# Allow imports from the parent directory (the worker package root)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bfs_analyzer import analyze, bfs_reachable
from graph_builder import build_graph
from neo4j_exporter import export_cypher
from worker import _extract_dsl


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────────────────────────────────────

_MATERIAL = {
    "textileType": "blend",
    "blend": "Cotton 95 / Elastane 5",
    "weightGsm": 180,
    "elasticRecoveryPct": 10,
    "shrinkagePct": 3,
}
_STRETCH = {"warpStretchPct": 10, "weftStretchPct": 15}


def _comp(comp_id: str, category: str = "body", panel_role: str = "front") -> dict:
    return {
        "id": comp_id,
        "name": comp_id,
        "category": category,
        "panelRole": panel_role,
        "material": _MATERIAL,
        "stretchProfile": _STRETCH,
        "seamAllowanceMm": 8,
    }


def _seam(seam_id: str, a: str, b: str, seam_type: str = "flat", length_mm: float = 400.0) -> dict:
    return {
        "id": seam_id,
        "componentA": a,
        "componentB": b,
        "seamType": seam_type,
        "seamLengthMm": length_mm,
    }


def _tshirt_dsl() -> dict:
    """Standard 4-component T-shirt: FrontBody-BackBody-LeftSleeve-RightSleeve, 4 seams."""
    return {
        "metadata": {
            "schemaVersion": "0.1",
            "designIntent": "Basic T-shirt",
            "globalToleranceMm": 2.0,
            "units": "mm",
        },
        "components": [
            _comp("FrontBody", "body", "front"),
            _comp("BackBody", "body", "back"),
            _comp("LeftSleeve", "sleeve", "left"),
            _comp("RightSleeve", "sleeve", "right"),
        ],
        "topology": [
            _seam("S1", "FrontBody", "BackBody", "flat", 600),
            _seam("S2", "FrontBody", "LeftSleeve", "overlock", 350),
            _seam("S3", "FrontBody", "RightSleeve", "overlock", 350),
        ],
        "constraints": {
            "optimization": {"objective": "balanced", "targetUnitCost": 20},
            "processLimits": {
                "maxOperationCount": 10,
                "maxConstructionMinutes": 30,
                "allowHandFinish": False,
            },
        },
    }


def _run(dsl: dict) -> tuple:
    """Convenience: build + analyze; returns (TopologyReport, BuildResult)."""
    br = build_graph(dsl)
    report = analyze(br, dsl_version="0.1")
    return report, br


def _error_codes(report) -> list[str]:
    return [e["code"] for e in report.errors]


def _warning_codes(report) -> list[str]:
    return [w["code"] for w in report.warnings]


# ─────────────────────────────────────────────────────────────────────────────
# GraphBuilderTests
# ─────────────────────────────────────────────────────────────────────────────

class GraphBuilderTests(unittest.TestCase):

    def test_build_graph_nodes_and_edges(self):
        br = build_graph(_tshirt_dsl())
        self.assertEqual(br.graph.number_of_nodes(), 4)
        self.assertEqual(br.graph.number_of_edges(), 3)
        self.assertIn("FrontBody", br.component_ids)
        self.assertIn("LeftSleeve", br.component_ids)
        self.assertEqual(len(br.seam_ids), 3)

    def test_build_graph_captures_self_loop(self):
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("SelfLoop", "FrontBody", "FrontBody"))
        br = build_graph(dsl)
        self.assertEqual(len(br.self_loops), 1)
        self.assertEqual(br.self_loops[0]["seamId"], "SelfLoop")
        # Self-loop must NOT appear as a graph edge
        self.assertFalse(br.graph.has_edge("FrontBody", "FrontBody"))

    def test_build_graph_captures_unknown_ref(self):
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("SX", "FrontBody", "GhostPanel"))
        br = build_graph(dsl)
        self.assertEqual(len(br.unknown_refs), 1)
        self.assertIn("GhostPanel", br.unknown_refs[0]["unknownComponents"])
        # Edge with dangling reference must NOT be added
        self.assertFalse(br.graph.has_edge("FrontBody", "GhostPanel"))

    def test_build_graph_captures_dup_seam_id(self):
        dsl = _tshirt_dsl()
        # Add a second seam with the same ID as S1
        dsl["topology"].append(_seam("S1", "BackBody", "LeftSleeve"))
        br = build_graph(dsl)
        self.assertIn("S1", br.duplicate_seam_ids)

    def test_build_graph_allows_parallel_seams_with_unique_ids(self):
        dsl = {
            "metadata": {"schemaVersion": "0.1", "designIntent": "vest", "globalToleranceMm": 2, "units": "mm"},
            "components": [_comp("FrontBody", "body", "front"), _comp("BackBody", "body", "back")],
            "topology": [
                _seam("SideSeam", "FrontBody", "BackBody", "overlock", 300),
                _seam("ShoulderSeam", "FrontBody", "BackBody", "flat", 100),
            ],
            "constraints": {
                "optimization": {"objective": "balanced", "targetUnitCost": 10},
                "processLimits": {"maxOperationCount": 5, "maxConstructionMinutes": 10, "allowHandFinish": False},
            },
        }
        br = build_graph(dsl)
        report = analyze(br, dsl_version="0.1")
        self.assertEqual(br.duplicate_seam_ids, [])
        self.assertTrue(report.valid)


# ─────────────────────────────────────────────────────────────────────────────
# AnalyzerHappyPathTests
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzerHappyPathTests(unittest.TestCase):

    def test_valid_tshirt_no_errors(self):
        report, _ = _run(_tshirt_dsl())
        self.assertTrue(report.valid)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.component_count, 4)
        self.assertEqual(report.seam_count, 3)
        self.assertEqual(report.connected_components, 1)

    def test_valid_tshirt_meta_populated(self):
        report, _ = _run(_tshirt_dsl())
        self.assertEqual(report.meta["dslVersion"], "0.1")
        self.assertIn("graphSummary", report.meta)
        self.assertEqual(report.meta["graphSummary"]["nodes"], 4)
        self.assertEqual(report.meta["graphSummary"]["bodyNodeCount"], 2)

    def test_minimal_two_component_dsl_valid(self):
        dsl = {
            "metadata": {"schemaVersion": "0.1", "designIntent": "min", "globalToleranceMm": 2, "units": "mm"},
            "components": [_comp("A", "body"), _comp("B", "body", "back")],
            "topology": [_seam("S1", "A", "B")],
            "constraints": {
                "optimization": {"objective": "balanced", "targetUnitCost": 10},
                "processLimits": {"maxOperationCount": 5, "maxConstructionMinutes": 10, "allowHandFinish": False},
            },
        }
        report, _ = _run(dsl)
        self.assertTrue(report.valid)
        self.assertEqual(report.connected_components, 1)


# ─────────────────────────────────────────────────────────────────────────────
# IsolatedNodeTests
# ─────────────────────────────────────────────────────────────────────────────

class IsolatedNodeTests(unittest.TestCase):

    def _dsl_with_isolated_sleeve(self) -> dict:
        dsl = _tshirt_dsl()
        # Remove the seams connecting LeftSleeve so it becomes isolated
        dsl["topology"] = [s for s in dsl["topology"] if s["id"] != "S2"]
        return dsl

    def test_isolated_left_sleeve_is_error(self):
        report, _ = _run(self._dsl_with_isolated_sleeve())
        self.assertFalse(report.valid)
        self.assertIn("ISOLATED_COMPONENT", _error_codes(report))
        isolated_errors = [e for e in report.errors if e["code"] == "ISOLATED_COMPONENT"]
        isolated_ids = {e["componentId"] for e in isolated_errors}
        self.assertIn("LeftSleeve", isolated_ids)

    def test_repair_hints_mention_isolated_node(self):
        report, _ = _run(self._dsl_with_isolated_sleeve())
        hints = [h for h in report.repair_hints if h.get("code") == "ISOLATED_COMPONENT"]
        self.assertTrue(len(hints) >= 1)
        hint_text = hints[0]["suggestion"]
        self.assertIn("LeftSleeve", hint_text)

    def test_repair_hint_sleeve_suggests_body_connection(self):
        report, _ = _run(self._dsl_with_isolated_sleeve())
        hints = [h for h in report.repair_hints if h.get("code") == "ISOLATED_COMPONENT"]
        # Hint for a sleeve should mention a body component
        self.assertTrue(
            any("body" in h["suggestion"].lower() or "FrontBody" in h["suggestion"] for h in hints)
        )

    def test_all_isolated_nodes_counted(self):
        """Both sleeves isolated → two ISOLATED_COMPONENT errors."""
        dsl = _tshirt_dsl()
        dsl["topology"] = [_seam("S1", "FrontBody", "BackBody")]  # only trunk seam remains
        report, _ = _run(dsl)
        self.assertFalse(report.valid)
        isolated_errors = [e for e in report.errors if e["code"] == "ISOLATED_COMPONENT"]
        self.assertEqual(len(isolated_errors), 2)
        isolated_ids = {e["componentId"] for e in isolated_errors}
        self.assertIn("LeftSleeve", isolated_ids)
        self.assertIn("RightSleeve", isolated_ids)


# ─────────────────────────────────────────────────────────────────────────────
# MultipleComponentTests
# ─────────────────────────────────────────────────────────────────────────────

class MultipleComponentTests(unittest.TestCase):

    def _two_garment_dsl(self) -> dict:
        """
        T-shirt (FrontBody + BackBody) and Trousers (LeftLeg + RightLeg + Waistband)
        with NO seam connecting the two groups.  Both groups have body-category nodes.
        """
        return {
            "metadata": {"schemaVersion": "0.1", "designIntent": "suit", "globalToleranceMm": 2, "units": "mm"},
            "components": [
                _comp("FrontBody", "body", "front"),
                _comp("BackBody", "body", "back"),
                _comp("LeftLeg", "body", "left"),      # using "body" for trousers legs
                _comp("RightLeg", "body", "right"),
                _comp("Waistband", "other", "other"),
            ],
            "topology": [
                _seam("S1", "FrontBody", "BackBody"),          # top seams
                _seam("S2", "LeftLeg", "RightLeg"),            # trouser seams
                _seam("S3", "Waistband", "LeftLeg"),
            ],
            "constraints": {
                "optimization": {"objective": "balanced", "targetUnitCost": 40},
                "processLimits": {"maxOperationCount": 15, "maxConstructionMinutes": 45, "allowHandFinish": True},
            },
        }

    def test_two_disjoint_garments_is_warning_not_error(self):
        """
        Two disjoint garments (top + trousers) → MULTIPLE_CONNECTED_COMPONENTS warning
        but valid=True because there are no errors (no isolated nodes, both CCs have body).
        """
        report, _ = _run(self._two_garment_dsl())
        self.assertTrue(report.valid, "Two-piece set should be valid (warnings only)")
        self.assertIn("MULTIPLE_CONNECTED_COMPONENTS", _warning_codes(report))
        mcc = next(w for w in report.warnings if w["code"] == "MULTIPLE_CONNECTED_COMPONENTS")
        self.assertEqual(mcc["connectedComponentCount"], 2)

    def test_two_disjoint_garments_repair_hint_suggests_multi_piece(self):
        report, _ = _run(self._two_garment_dsl())
        hint_texts = " ".join(h.get("suggestion", "") for h in report.repair_hints)
        # Should suggest targetGarmentType='other' or similar
        self.assertTrue(
            "targetGarmentType" in hint_texts or "multi-piece" in hint_texts.lower()
        )

    def test_disjoint_with_orphan_group_unreachable(self):
        """
        Group with NO body-category node → UNREACHABLE_FROM_BODY warning.
        """
        dsl = {
            "metadata": {"schemaVersion": "0.1", "designIntent": "test", "globalToleranceMm": 2, "units": "mm"},
            "components": [
                _comp("FrontBody", "body", "front"),
                _comp("BackBody", "body", "back"),
                _comp("LeftPocket", "pocket", "left"),
                _comp("RightPocket", "pocket", "right"),
            ],
            "topology": [
                _seam("S1", "FrontBody", "BackBody"),
                _seam("S2", "LeftPocket", "RightPocket"),   # pocket CC has no body node
            ],
            "constraints": {
                "optimization": {"objective": "balanced", "targetUnitCost": 20},
                "processLimits": {"maxOperationCount": 8, "maxConstructionMinutes": 20, "allowHandFinish": False},
            },
        }
        report, _ = _run(dsl)
        self.assertTrue(report.valid)  # no isolated nodes → still valid
        self.assertIn("MULTIPLE_CONNECTED_COMPONENTS", _warning_codes(report))
        self.assertIn("UNREACHABLE_FROM_BODY", _warning_codes(report))
        unreachable = [w for w in report.warnings if w["code"] == "UNREACHABLE_FROM_BODY"]
        unreachable_ids = {w["componentId"] for w in unreachable}
        self.assertIn("LeftPocket", unreachable_ids)
        self.assertIn("RightPocket", unreachable_ids)

    def test_bfs_reachable_helper_direct(self):
        """Unit-test the explicit BFS helper function directly."""
        br = build_graph(_tshirt_dsl())
        reached = bfs_reachable(br.graph, ["FrontBody"])
        # All 4 components should be reachable from FrontBody
        self.assertEqual(reached, {"FrontBody", "BackBody", "LeftSleeve", "RightSleeve"})

    def test_bfs_reachable_from_isolated_start(self):
        """Starting BFS from an unreachable node should only return that node."""
        dsl = _tshirt_dsl()
        dsl["topology"] = [_seam("S1", "FrontBody", "BackBody")]
        br = build_graph(dsl)
        reached = bfs_reachable(br.graph, ["LeftSleeve"])
        self.assertEqual(reached, {"LeftSleeve"})


# ─────────────────────────────────────────────────────────────────────────────
# PreGraphErrorTests
# ─────────────────────────────────────────────────────────────────────────────

class PreGraphErrorTests(unittest.TestCase):

    def test_self_loop_seam_is_error(self):
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("Loop1", "FrontBody", "FrontBody"))
        report, _ = _run(dsl)
        self.assertFalse(report.valid)
        self.assertIn("SELF_LOOP_SEAM", _error_codes(report))
        loop_error = next(e for e in report.errors if e["code"] == "SELF_LOOP_SEAM")
        self.assertEqual(loop_error["seamId"], "Loop1")
        self.assertEqual(loop_error["componentId"], "FrontBody")

    def test_unknown_component_ref_is_error(self):
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("Ghost1", "FrontBody", "GhostPanel"))
        report, _ = _run(dsl)
        self.assertFalse(report.valid)
        self.assertIn("UNKNOWN_COMPONENT_REF", _error_codes(report))
        ref_error = next(e for e in report.errors if e["code"] == "UNKNOWN_COMPONENT_REF")
        self.assertIn("GhostPanel", ref_error["unknownComponents"])

    def test_duplicate_seam_id_is_error(self):
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("S1", "BackBody", "LeftSleeve"))
        report, _ = _run(dsl)
        self.assertFalse(report.valid)
        self.assertIn("DUPLICATE_SEAM_ID", _error_codes(report))

    def test_multiple_pre_graph_errors_all_reported(self):
        """Self-loop + unknown ref in the same DSL → both errors appear."""
        dsl = _tshirt_dsl()
        dsl["topology"].append(_seam("Loop1", "BackBody", "BackBody"))
        dsl["topology"].append(_seam("X1", "FrontBody", "Phantom"))
        report, _ = _run(dsl)
        codes = _error_codes(report)
        self.assertIn("SELF_LOOP_SEAM", codes)
        self.assertIn("UNKNOWN_COMPONENT_REF", codes)


# ─────────────────────────────────────────────────────────────────────────────
# SymmetryTests
# ─────────────────────────────────────────────────────────────────────────────

class SymmetryTests(unittest.TestCase):

    def test_asymmetric_pair_produces_warning(self):
        """LeftSleeve without RightSleeve should trigger ASYMMETRIC_PAIR warning."""
        dsl = _tshirt_dsl()
        # Remove RightSleeve component and its seam
        dsl["components"] = [c for c in dsl["components"] if c["id"] != "RightSleeve"]
        dsl["topology"] = [s for s in dsl["topology"] if s["id"] != "S3"]
        report, _ = _run(dsl)
        # There may be errors (if LeftSleeve is connected) but there should be an asym warning
        self.assertIn("ASYMMETRIC_PAIR", _warning_codes(report))
        asym = next(w for w in report.warnings if w["code"] == "ASYMMETRIC_PAIR")
        self.assertEqual(asym["leftComponent"], "LeftSleeve")
        self.assertIn("RightSleeve", asym["expectedRightComponent"])

    def test_symmetric_pair_no_warning(self):
        """Both LeftSleeve and RightSleeve present → no ASYMMETRIC_PAIR warning."""
        report, _ = _run(_tshirt_dsl())
        self.assertNotIn("ASYMMETRIC_PAIR", _warning_codes(report))

    def test_asymmetric_pair_repair_hint_references_missing_side(self):
        dsl = _tshirt_dsl()
        dsl["components"] = [c for c in dsl["components"] if c["id"] != "RightSleeve"]
        dsl["topology"] = [s for s in dsl["topology"] if s["id"] != "S3"]
        report, _ = _run(dsl)
        asym_hints = [h for h in report.repair_hints if h.get("code") == "ASYMMETRIC_PAIR"]
        self.assertTrue(len(asym_hints) >= 1)
        self.assertIn("RightSleeve", asym_hints[0]["suggestion"])


# ─────────────────────────────────────────────────────────────────────────────
# Neo4jExporterTests
# ─────────────────────────────────────────────────────────────────────────────

class Neo4jExporterTests(unittest.TestCase):

    def _build_and_export(self, dsl: dict, label: str = "TestGarment") -> str:
        br = build_graph(dsl)
        return export_cypher(br.graph, garment_label=label)

    def test_cypher_contains_all_node_merges(self):
        cypher = self._build_and_export(_tshirt_dsl())
        for comp_id in ("FrontBody", "BackBody", "LeftSleeve", "RightSleeve"):
            self.assertIn(f"componentId: '{comp_id}'", cypher)
            self.assertIn("MERGE", cypher)

    def test_cypher_contains_seam_relationships(self):
        cypher = self._build_and_export(_tshirt_dsl())
        self.assertIn(":SEAM", cypher)
        self.assertIn("seamId: 'S1'", cypher)
        self.assertIn("seamId: 'S2'", cypher)
        self.assertIn("seamId: 'S3'", cypher)

    def test_cypher_uses_custom_garment_label(self):
        cypher = self._build_and_export(_tshirt_dsl(), label="SpringCollection2026")
        self.assertIn("SpringCollection2026", cypher)

    def test_cypher_escapes_single_quotes(self):
        dsl = _tshirt_dsl()
        dsl["components"][0]["name"] = "Front Body (Men's)"
        br = build_graph(dsl)
        cypher = export_cypher(br.graph)
        # Should NOT contain an unescaped single quote that would break Cypher
        self.assertNotIn("Men's", cypher)     # raw apostrophe must be escaped
        self.assertIn("Men\\'s", cypher)       # proper escape present

    def test_cypher_skips_self_loop_edges(self):
        dsl = _tshirt_dsl()
        # Add a self-loop; graph_builder will NOT add it as an edge,
        # so the exporter should produce no SEAM for it.
        dsl["topology"].append(_seam("Loop1", "BackBody", "BackBody"))
        br = build_graph(dsl)
        cypher = export_cypher(br.graph)
        # Loop1 should not appear in any SEAM MERGE
        self.assertNotIn("seamId: 'Loop1'", cypher)

    def test_cypher_relationship_count_matches_edges(self):
        """Number of MERGE (a)-[...:SEAM...]->(b) statements == number of edges."""
        br = build_graph(_tshirt_dsl())
        cypher = export_cypher(br.graph)
        seam_merge_count = cypher.count("MERGE (a)-[r:SEAM")
        self.assertEqual(seam_merge_count, br.graph.number_of_edges())


# ─────────────────────────────────────────────────────────────────────────────
# WorkerPayloadTests
# ─────────────────────────────────────────────────────────────────────────────

class WorkerPayloadTests(unittest.TestCase):

    def _bare_dsl_payload(self) -> str:
        import json
        dsl = _tshirt_dsl()
        return json.dumps(dsl)

    def _wrapped_dsl_payload(self) -> str:
        import json
        return json.dumps({"taskId": "task_abc", "dsl": _tshirt_dsl()})

    def test_extract_dsl_from_wrapper(self):
        dsl = _extract_dsl(self._wrapped_dsl_payload())
        self.assertIsNotNone(dsl)
        self.assertIn("components", dsl)
        self.assertIn("topology", dsl)

    def test_extract_dsl_from_bare_root(self):
        dsl = _extract_dsl(self._bare_dsl_payload())
        self.assertIsNotNone(dsl)
        self.assertIn("components", dsl)

    def test_extract_dsl_returns_none_on_empty(self):
        self.assertIsNone(_extract_dsl(""))
        self.assertIsNone(_extract_dsl("   "))
        self.assertIsNone(_extract_dsl("null"))

    def test_extract_dsl_returns_none_on_invalid_json(self):
        self.assertIsNone(_extract_dsl("{not valid json"))

    def test_extract_dsl_returns_none_when_no_dsl_key(self):
        import json
        self.assertIsNone(_extract_dsl(json.dumps({"taskId": "abc", "options": {}})))


# ─────────────────────────────────────────────────────────────────────────────
# Integration-style round-trip test
# ─────────────────────────────────────────────────────────────────────────────

class RoundTripTests(unittest.TestCase):

    def test_to_dict_is_json_serialisable(self):
        """TopologyReport.to_dict() must be JSON-serialisable without errors."""
        import json
        report, _ = _run(_tshirt_dsl())
        serialised = json.dumps(report.to_dict(), ensure_ascii=False)
        reloaded = json.loads(serialised)
        self.assertIn("valid", reloaded)
        self.assertIn("errors", reloaded)
        self.assertIn("warnings", reloaded)
        self.assertIn("repairHints", reloaded)
        self.assertIn("meta", reloaded)

    def test_report_fields_on_complex_dsl(self):
        """
        Four-component jacket DSL with a pocket group that has no body connection.
        Expect: valid=True, MULTIPLE_CONNECTED_COMPONENTS warning,
                UNREACHABLE_FROM_BODY warning for pockets.
        """
        dsl = {
            "metadata": {"schemaVersion": "0.1", "designIntent": "Jacket", "globalToleranceMm": 3, "units": "mm"},
            "components": [
                _comp("JacketFront", "body", "front"),
                _comp("JacketBack", "body", "back"),
                _comp("ChestPocketOuter", "pocket", "outer"),
                _comp("ChestPocketInner", "pocket", "inner"),
            ],
            "topology": [
                _seam("J1", "JacketFront", "JacketBack"),
                _seam("J2", "ChestPocketOuter", "ChestPocketInner"),
                # Pocket group intentionally disconnected from body for this test
            ],
            "constraints": {
                "optimization": {"objective": "balanced", "targetUnitCost": 80},
                "processLimits": {"maxOperationCount": 20, "maxConstructionMinutes": 60, "allowHandFinish": True},
            },
        }
        report, _ = _run(dsl)
        self.assertTrue(report.valid)
        codes = _warning_codes(report)
        self.assertIn("MULTIPLE_CONNECTED_COMPONENTS", codes)
        self.assertIn("UNREACHABLE_FROM_BODY", codes)
        self.assertEqual(report.connected_components, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
