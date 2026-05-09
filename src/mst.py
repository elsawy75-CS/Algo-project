"""
mst.py — Minimum Spanning Tree algorithms for Cairo road network design.

Implements:
  • Kruskal's algorithm  — O(E log E) with Union-Find (path compression + rank)
  • Prim's algorithm     — O((V+E) log V) with min-heap

Both algorithms include a modification: edges incident to critical facilities
(hospitals, transit hubs, government centres) have their weight halved to
guarantee those nodes are pulled into the MST early.

Time complexity:  Kruskal O(E log E + E·α(V))
Space complexity: O(V + E)
"""

from __future__ import annotations
import heapq
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

from graph import CairoGraph, Edge, Node


# --------------------------------------------------------------------------- #
#  Union-Find (Disjoint Set Union)                                             #
# --------------------------------------------------------------------------- #

class UnionFind:
    def __init__(self, elements):
        self.parent = {e: e for e in elements}
        self.rank   = {e: 0  for e in elements}
        self.components = len(elements)

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])   # path compression
        return self.parent[x]

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False   # same component → would create cycle
        # union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        self.components -= 1
        return True

    def connected(self) -> bool:
        return self.components == 1


# --------------------------------------------------------------------------- #
#  MST result                                                                   #
# --------------------------------------------------------------------------- #

@dataclass
class MSTResult:
    edges: List[Edge]
    total_weight: float
    total_distance: float
    algorithm: str
    steps: List[dict]           # trace log for visualization

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "edge_count": self.edge_count,
            "total_weight": round(self.total_weight, 2),
            "total_distance": round(self.total_distance, 2),
            "edges": [
                {
                    "src": e.src,
                    "dst": e.dst,
                    "distance": e.distance,
                    "is_potential": e.is_potential,
                    "construction_cost": e.construction_cost,
                }
                for e in self.edges
            ],
            "steps": self.steps,
        }


# --------------------------------------------------------------------------- #
#  Priority weight modifier                                                     #
# --------------------------------------------------------------------------- #

def _priority_weight(graph: CairoGraph, edge: Edge) -> float:
    """
    MST edge weight.  Critical-facility connections get 50 % discount
    so they are guaranteed early connectivity (project constraint).
    Potential roads use construction cost; existing roads use distance.
    """
    base = edge.distance if not edge.is_potential else edge.construction_cost
    src_critical = graph.nodes.get(edge.src, Node("","",0,"",0,0)).is_critical
    dst_critical = graph.nodes.get(edge.dst, Node("","",0,"",0,0)).is_critical
    if src_critical or dst_critical:
        base *= 0.5
    return base


# --------------------------------------------------------------------------- #
#  Kruskal's Algorithm                                                          #
# --------------------------------------------------------------------------- #

def kruskal(graph: CairoGraph,
            include_potential: bool = False) -> MSTResult:
    """
    Kruskal's MST with Union-Find.

    Steps:
      1. Collect candidate edges (existing + optionally potential).
      2. Sort by priority weight ascending — O(E log E).
      3. Greedily add edge if it connects two different components — O(α(V)) per edge.

    Modification: critical-facility edges weighted at 50 % → pulled in first.

    Complexity: Time O(E log E),  Space O(V + E)
    """
    all_edges: List[Edge] = graph.existing_edges()
    if include_potential:
        all_edges += graph.potential_edges()

    # Sort edges by modified priority weight
    sorted_edges = sorted(all_edges, key=lambda e: _priority_weight(graph, e))

    uf = UnionFind(list(graph.nodes.keys()))
    mst_edges: List[Edge] = []
    steps: List[dict] = []
    total_weight = 0.0

    for e in sorted_edges:
        w = _priority_weight(graph, e)
        action = "rejected (cycle)"
        if uf.union(e.src, e.dst):
            mst_edges.append(e)
            total_weight += w
            action = "added"

        steps.append({
            "src": e.src,
            "dst": e.dst,
            "src_name": graph.nodes.get(e.src, Node("","","","",0,0)).name if hasattr(graph.nodes.get(e.src, None), 'name') else e.src,
            "dst_name": graph.nodes.get(e.dst, Node("","","","",0,0)).name if hasattr(graph.nodes.get(e.dst, None), 'name') else e.dst,
            "weight": round(w, 2),
            "distance": e.distance,
            "action": action,
            "is_potential": e.is_potential,
        })

        if len(mst_edges) == len(graph.nodes) - 1:
            break   # MST complete

    total_dist = sum(e.distance for e in mst_edges)
    return MSTResult(
        edges=mst_edges,
        total_weight=total_weight,
        total_distance=total_dist,
        algorithm="Kruskal",
        steps=steps,
    )


# --------------------------------------------------------------------------- #
#  Prim's Algorithm                                                             #
# --------------------------------------------------------------------------- #

def prim(graph: CairoGraph,
         start: str = "3",
         include_potential: bool = False) -> MSTResult:
    """
    Prim's MST starting from Downtown Cairo.

    Steps:
      1. Initialize min-heap with start node at weight 0.
      2. Greedily extract min-weight frontier edge — O(log V) per extraction.
      3. Relax neighbours — O(E log V) total.

    Modification: same critical-facility weight halving as Kruskal.

    Complexity: Time O((V+E) log V),  Space O(V)
    """
    in_mst: set = set()
    # heap entries: (weight, src, dst, edge_object_or_None)
    heap = [(0.0, start, start, None)]
    mst_edges: List[Edge] = []
    steps: List[dict] = []
    total_weight = 0.0

    all_candidate_ids = set(graph.nodes.keys())

    while heap and len(in_mst) < len(all_candidate_ids):
        w, src, dst, edge = heapq.heappop(heap)
        if dst in in_mst:
            continue
        in_mst.add(dst)

        if edge is not None:
            mst_edges.append(edge)
            total_weight += w
            steps.append({
                "src": src,
                "dst": dst,
                "weight": round(w, 2),
                "distance": edge.distance,
                "action": "added",
                "is_potential": edge.is_potential,
            })

        for neighbour_edge in graph.neighbors(dst):
            if neighbour_edge.dst in in_mst:
                continue
            if neighbour_edge.is_potential and not include_potential:
                continue
            pw = _priority_weight(graph, neighbour_edge)
            heapq.heappush(heap, (pw, dst, neighbour_edge.dst, neighbour_edge))

    total_dist = sum(e.distance for e in mst_edges)
    return MSTResult(
        edges=mst_edges,
        total_weight=total_weight,
        total_distance=total_dist,
        algorithm="Prim",
        steps=steps,
    )


# --------------------------------------------------------------------------- #
#  Cost analysis helper                                                         #
# --------------------------------------------------------------------------- #

def cost_analysis(graph: CairoGraph, result: MSTResult) -> dict:
    """
    Compare MST cost vs full network cost.
    Returns saving percentages and per-type breakdown.
    """
    existing = graph.existing_edges()
    full_dist = sum(e.distance for e in existing)
    potential_cost = sum(e.construction_cost for e in graph.potential_edges())

    mst_existing = [e for e in result.edges if not e.is_potential]
    mst_potential = [e for e in result.edges if e.is_potential]

    return {
        "full_network_distance_km": round(full_dist, 1),
        "mst_distance_km": round(result.total_distance, 1),
        "distance_saving_pct": round((1 - result.total_distance / full_dist) * 100, 1),
        "mst_existing_roads": len(mst_existing),
        "mst_new_roads": len(mst_potential),
        "new_road_cost_mEGP": round(sum(e.construction_cost for e in mst_potential), 1),
        "total_potential_cost_mEGP": round(potential_cost, 1),
        "cost_saving_pct": round(
            (1 - sum(e.construction_cost for e in mst_potential) / max(potential_cost, 1)) * 100, 1
        ),
    }
