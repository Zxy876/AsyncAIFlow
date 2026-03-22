"""
graph_builder.py
~~~~~~~~~~~~~~~~
Translates a Design Schema v0.1 DSL dict into a NetworkX undirected Graph.

Vertices  = DSL components  (node attributes carry all component metadata)
Edges     = DSL topology seams  (edge attributes carry all seam metadata)

The builder also captures pre-graph validation artefacts that the BFS
analyser needs:
  - unknown_refs      : seams that reference component IDs not in the graph
  - self_loops        : seams where componentA == componentB
  - duplicate_seam_ids: seam IDs that appear more than once in topology
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

# Category labels that represent the "trunk" of a garment for BFS origin.
BODY_CATEGORIES: frozenset[str] = frozenset({"body"})

# Prefix pairs used for symmetry checks (left/right mirror components).
SYMMETRIC_PAIR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("Left", "Right"),
    ("L_", "R_"),
)


@dataclass
class BuildResult:
    """Immutable output of build_graph()."""

    graph: nx.Graph                          # undirected, no self-loop edges
    component_ids: set[str]
    seam_ids: set[str]                       # de-duplicated seam IDs from topology
    unknown_refs: list[dict[str, Any]]       # seams referencing absent components
    self_loops: list[dict[str, Any]]         # seams where A == B
    duplicate_seam_ids: list[str]            # seam IDs appearing > 1 time


def build_graph(dsl: dict[str, Any]) -> BuildResult:
    """
    Build a NetworkX Graph from a Design Schema v0.1 DSL.

    Self-loops are noted in *self_loops* but are NOT added as graph edges so
    that degree-based isolation analysis remains accurate.
    Seams referencing unknown components are noted in *unknown_refs* and also
    not added to the graph.
    """
    g = nx.Graph()
    component_ids: set[str] = set()

    for comp in dsl.get("components", []):
        cid = comp["id"]
        component_ids.add(cid)
        attrs = {k: v for k, v in comp.items() if k != "id"}
        g.add_node(cid, **attrs)

    seam_ids: set[str] = set()
    seen_seam_ids: set[str] = set()
    duplicate_seam_ids: list[str] = []
    unknown_refs: list[dict[str, Any]] = []
    self_loops: list[dict[str, Any]] = []

    for seam in dsl.get("topology", []):
        sid = seam["id"]
        comp_a = seam["componentA"]
        comp_b = seam["componentB"]

        if sid in seen_seam_ids:
            duplicate_seam_ids.append(sid)
        seen_seam_ids.add(sid)
        seam_ids.add(sid)

        # Check for unknown component references
        unknown: list[str] = []
        if comp_a not in component_ids:
            unknown.append(comp_a)
        if comp_b not in component_ids:
            unknown.append(comp_b)
        if unknown:
            unknown_refs.append({"seamId": sid, "unknownComponents": unknown})
            continue  # skip — dangling edge would corrupt graph

        # Check self-loops
        if comp_a == comp_b:
            self_loops.append({"seamId": sid, "component": comp_a})
            continue  # skip — self-loops break degree-0 isolation detection

        edge_attrs = {k: v for k, v in seam.items() if k not in ("id", "componentA", "componentB")}
        edge_attrs["seamId"] = sid
        if not g.has_edge(comp_a, comp_b):
            g.add_edge(comp_a, comp_b, **edge_attrs)

    return BuildResult(
        graph=g,
        component_ids=component_ids,
        seam_ids=seam_ids,
        unknown_refs=unknown_refs,
        self_loops=self_loops,
        duplicate_seam_ids=duplicate_seam_ids,
    )
