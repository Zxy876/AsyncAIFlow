"""
bfs_analyzer.py
~~~~~~~~~~~~~~~
Garment topology analysis using BFS / connected-component algorithms.

Analysis pipeline (all run on every DSL):
  Phase 0 — Pre-graph errors captured during graph construction
             (unknown component references, self-loops, duplicate seam IDs)
  Phase 1 — Isolated node detection   (degree == 0)           → errors
  Phase 2 — Connected component count (cc > 1)               → warnings
  Phase 3 — BFS reachability from body nodes                  → warnings
  Phase 4 — Symmetric pair heuristic  (LeftX / RightX)       → warnings

Output:  TopologyReport.to_dict() is the action result payload sent back to
         the AsyncAIFlow scheduler.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from graph_builder import BODY_CATEGORIES, SYMMETRIC_PAIR_PREFIXES, BuildResult

_WORKER_VERSION = "0.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Result model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TopologyReport:
    valid: bool                                # True iff errors is empty
    component_count: int
    seam_count: int
    connected_components: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    repair_hints: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "componentCount": self.component_count,
            "seamCount": self.seam_count,
            "connectedComponents": self.connected_components,
            "errors": self.errors,
            "warnings": self.warnings,
            "repairHints": self.repair_hints,
            "meta": self.meta,
        }


# ─────────────────────────────────────────────────────────────────────────────
# BFS helper (explicit, for traceability and unit-testability)
# ─────────────────────────────────────────────────────────────────────────────

def bfs_reachable(graph: nx.Graph, start_nodes: list[str]) -> set[str]:
    """
    Return the set of nodes reachable from *start_nodes* via undirected BFS.
    Implemented explicitly so the traversal is visible and unit-testable.
    """
    visited: set[str] = set()
    queue: deque[str] = deque(n for n in start_nodes if n in graph)
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for neighbor in graph.neighbors(node):
            if neighbor not in visited:
                queue.append(neighbor)
    return visited


# ─────────────────────────────────────────────────────────────────────────────
# Main analysis entry point
# ─────────────────────────────────────────────────────────────────────────────

def analyze(build_result: BuildResult, dsl_version: str = "unknown") -> TopologyReport:
    """
    Run full topology analysis on a BuildResult and return a TopologyReport.

    Parameters
    ----------
    build_result:
        Output of graph_builder.build_graph(dsl).
    dsl_version:
        Schema version string extracted from dsl.metadata.schemaVersion,
        passed through into the result meta block.
    """
    t_start = time.monotonic()

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    repair_hints: list[dict[str, Any]] = []

    # ── Phase 0: build-time errors ────────────────────────────────────────────
    for ref in build_result.unknown_refs:
        errors.append({
            "code": "UNKNOWN_COMPONENT_REF",
            "seamId": ref["seamId"],
            "unknownComponents": ref["unknownComponents"],
            "message": (
                f"Seam '{ref['seamId']}' references unknown component(s): "
                f"{', '.join(ref['unknownComponents'])}."
            ),
        })
        repair_hints.append({
            "code": "UNKNOWN_COMPONENT_REF",
            "targetSeamId": ref["seamId"],
            "suggestion": (
                f"Add the missing component(s) ({', '.join(ref['unknownComponents'])}) "
                "to the 'components' array, or correct the seam endpoint identifiers."
            ),
        })

    for sl in build_result.self_loops:
        errors.append({
            "code": "SELF_LOOP_SEAM",
            "seamId": sl["seamId"],
            "componentId": sl["component"],
            "message": (
                f"Seam '{sl['seamId']}' connects component '{sl['component']}' to itself."
            ),
        })
        repair_hints.append({
            "code": "SELF_LOOP_SEAM",
            "targetSeamId": sl["seamId"],
            "suggestion": (
                f"Change one endpoint of seam '{sl['seamId']}' to a different component."
            ),
        })

    for sid in build_result.duplicate_seam_ids:
        errors.append({
            "code": "DUPLICATE_SEAM_ID",
            "seamId": sid,
            "message": f"Seam ID '{sid}' appears more than once in the topology array.",
        })
        repair_hints.append({
            "code": "DUPLICATE_SEAM_ID",
            "targetSeamId": sid,
            "suggestion": (
                f"Assign a unique ID to every seam entry. Rename the duplicate '{sid}'."
            ),
        })

    # Working graph: undirected, self-loops removed ───────────────────────────
    g = build_result.graph  # already free of self-loops (see graph_builder)

    # ── Phase 1: Isolated nodes (degree == 0) ─────────────────────────────────
    isolated: list[str] = [n for n in g.nodes if g.degree(n) == 0]

    for node in isolated:
        category = g.nodes[node].get("category", "unknown")
        errors.append({
            "code": "ISOLATED_COMPONENT",
            "componentId": node,
            "category": category,
            "message": (
                f"Component '{node}' (category={category}) has no seam connections."
            ),
        })
        repair_hints.append({
            "code": "ISOLATED_COMPONENT",
            "targetComponentId": node,
            "suggestion": _isolation_hint(node, category, g),
        })

    # ── Phase 2: Connected components ─────────────────────────────────────────
    ccs = [frozenset(c) for c in nx.connected_components(g)]
    cc_count = len(ccs)

    if cc_count > 1:
        cc_summaries: list[dict[str, Any]] = []
        for idx, cc in enumerate(sorted(ccs, key=lambda c: (-len(c), sorted(c)[0]))):
            body_in_cc = [n for n in cc if g.nodes[n].get("category") in BODY_CATEGORIES]
            cc_summaries.append({
                "index": idx,
                "componentCount": len(cc),
                "components": sorted(cc),
                "hasBodyNode": bool(body_in_cc),
            })

        warnings.append({
            "code": "MULTIPLE_CONNECTED_COMPONENTS",
            "connectedComponentCount": cc_count,
            "componentGroups": cc_summaries,
            "message": (
                f"The garment graph has {cc_count} disconnected component groups. "
                "A single-piece garment should form one connected graph. "
                "This may indicate a multi-piece set (e.g., jacket + pants) or a design error."
            ),
        })

        orphan_groups = [s for s in cc_summaries if not s["hasBodyNode"]]
        main_groups = [s for s in cc_summaries if s["hasBodyNode"]]

        for occ in orphan_groups:
            repair_hints.append({
                "code": "MULTIPLE_CONNECTED_COMPONENTS",
                "affectedComponents": occ["components"],
                "suggestion": (
                    f"Component group {occ['components']} has no 'body'-category node. "
                    "Connect it to the main garment body via a new seam, "
                    "or add a body-category component to this group."
                ),
            })

        if not orphan_groups and len(main_groups) > 1:
            # Both groups have body nodes → likely a conscious multi-piece set
            repair_hints.append({
                "code": "MULTIPLE_CONNECTED_COMPONENTS",
                "suggestion": (
                    "If this is intentionally a multi-piece set (e.g., a suit), "
                    "set metadata.targetGarmentType to 'other' to suppress this warning. "
                    "Otherwise add seam(s) to connect the separate garment pieces."
                ),
            })

    # ── Phase 3: BFS reachability from body nodes ─────────────────────────────
    body_nodes = [n for n in g.nodes if g.nodes[n].get("category") in BODY_CATEGORIES]
    reachable_from_body = bfs_reachable(g, body_nodes)

    isolated_set = frozenset(isolated)
    for node in sorted(g.nodes):
        if node in reachable_from_body:
            continue
        if node in isolated_set:
            continue  # already reported
        category = g.nodes[node].get("category", "unknown")
        warnings.append({
            "code": "UNREACHABLE_FROM_BODY",
            "componentId": node,
            "category": category,
            "message": (
                f"Component '{node}' (category={category}) is not reachable from any "
                "'body'-category component via BFS traversal."
            ),
        })
        repair_hints.append({
            "code": "UNREACHABLE_FROM_BODY",
            "targetComponentId": node,
            "suggestion": (
                f"Add a seam that links '{node}' (or its connected group) to a body component, "
                "or verify this component belongs to a separate intentional piece."
            ),
        })

    # ── Phase 4: Symmetric-pair heuristic ─────────────────────────────────────
    node_set = set(g.nodes)
    for left_prefix, right_prefix in SYMMETRIC_PAIR_PREFIXES:
        left_nodes = [n for n in node_set if n.startswith(left_prefix)]
        for ln in left_nodes:
            expected_right = right_prefix + ln[len(left_prefix):]
            if expected_right not in node_set:
                warnings.append({
                    "code": "ASYMMETRIC_PAIR",
                    "leftComponent": ln,
                    "expectedRightComponent": expected_right,
                    "message": (
                        f"Found '{ln}' but no corresponding '{expected_right}'. "
                        "The garment may lack bilateral symmetry."
                    ),
                })
                repair_hints.append({
                    "code": "ASYMMETRIC_PAIR",
                    "targetComponentId": ln,
                    "suggestion": (
                        f"Add a '{expected_right}' component paired with '{ln}' "
                        "and connect it symmetrically with the same seam type and length."
                    ),
                })

    # ── Finalise ──────────────────────────────────────────────────────────────
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    density = nx.density(g) if g.number_of_nodes() > 1 else 0.0
    valid = len(errors) == 0

    return TopologyReport(
        valid=valid,
        component_count=len(build_result.component_ids),
        seam_count=len(build_result.seam_ids),
        connected_components=cc_count,
        errors=errors,
        warnings=warnings,
        repair_hints=repair_hints,
        meta={
            "workerVersion": _WORKER_VERSION,
            "dslVersion": dsl_version,
            "analysisTimeMs": elapsed_ms,
            "graphSummary": {
                "nodes": g.number_of_nodes(),
                "edges": g.number_of_edges(),
                "density": round(density, 4),
                "bodyNodeCount": len(body_nodes),
                "isolatedNodeCount": len(isolated),
                "bfsReachableFromBodyCount": len(reachable_from_body),
            },
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _isolation_hint(node_id: str, category: str, graph: nx.Graph) -> str:
    """Generate a targeted repair suggestion based on the isolated component's category."""
    body_nodes = [n for n in graph.nodes if graph.nodes[n].get("category") in BODY_CATEGORIES]

    if category == "sleeve":
        if body_nodes:
            return (
                f"在 topology 中添加一条将 '{node_id}' 连接到身体部件（如 '{body_nodes[0]}'）的接缝。"
                "Add a seam in 'topology' connecting the isolated sleeve to a body component "
                f"(e.g., '{body_nodes[0]}')."
            )
        return f"Add a seam in 'topology' connecting sleeve '{node_id}' to a body component."

    if category == "collar":
        if body_nodes:
            return (
                f"Add a seam connecting collar '{node_id}' to the front body component "
                f"(e.g., '{body_nodes[0]}') at the neckline edge."
            )
        return f"Add a seam connecting collar '{node_id}' to a body component."

    if category == "cuff":
        sleeve_nodes = [n for n in graph.nodes if graph.nodes[n].get("category") == "sleeve"]
        if sleeve_nodes:
            return (
                f"Add a seam connecting cuff '{node_id}' to a sleeve component "
                f"(e.g., '{sleeve_nodes[0]}')."
            )
        return f"Add a seam connecting cuff '{node_id}' to a sleeve or body component."

    if category in ("pocket", "placket", "hem"):
        if body_nodes:
            return (
                f"Add a seam connecting '{node_id}' (category={category}) to "
                f"'{body_nodes[0]}' or the relevant panel it belongs to."
            )

    if body_nodes:
        return (
            f"Add at least one seam in 'topology' connecting '{node_id}' to a body component "
            f"(e.g., '{body_nodes[0]}')."
        )
    return f"Add at least one seam in 'topology' connecting '{node_id}' to another component."
