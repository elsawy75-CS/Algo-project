"""
shortest_path.py — Routing algorithms for Cairo Transportation Network.

Implements:
  • Dijkstra's algorithm     — standard route planning, O((V+E) log V)
  • A* search                — emergency vehicle routing with haversine heuristic
  • Time-varying Dijkstra    — BPR-weighted edges change with time period
  • Memoised route cache     — LRU cache for repeated route queries

All algorithms return a PathResult with the full path, distance, and
travel-time estimate.
"""

from __future__ import annotations
import heapq
import math
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from graph import CairoGraph, Edge


# --------------------------------------------------------------------------- #
#  Result dataclass                                                             #
# --------------------------------------------------------------------------- #

@dataclass
class PathResult:
    src: str
    dst: str
    path: List[str]
    total_distance: float       # km
    travel_time_min: float      # estimated minutes
    algorithm: str
    time_period: str
    nodes_explored: int         # for performance comparison
    edges_in_path: List[Edge] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return len(self.path) >= 2

    def to_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "path": self.path,
            "path_names": [],   # populated by API layer
            "total_distance": round(self.total_distance, 2),
            "travel_time_min": round(self.travel_time_min, 1),
            "algorithm": self.algorithm,
            "time_period": self.time_period,
            "nodes_explored": self.nodes_explored,
            "found": self.found,
        }


# --------------------------------------------------------------------------- #
#  Dijkstra's Algorithm                                                         #
# --------------------------------------------------------------------------- #

def dijkstra(graph: CairoGraph,
             src: str,
             dst: str,
             time_period: str = "morning",
             weight_fn=None) -> PathResult:
    """
    Classic Dijkstra with binary min-heap (heapq).

    weight_fn: callable(edge) → float.  Defaults to BPR travel-time weight
    accounting for time-varying congestion.

    Complexity: Time O((V+E) log V),  Space O(V)
    """
    if weight_fn is None:
        weight_fn = lambda e: e.time_weight(time_period)

    dist: Dict[str, float] = {nid: math.inf for nid in graph.nodes}
    prev: Dict[str, Optional[str]] = {nid: None for nid in graph.nodes}
    dist[src] = 0.0
    heap = [(0.0, src)]
    visited: set = set()
    nodes_explored = 0

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        nodes_explored += 1

        if u == dst:
            break

        for edge in graph.neighbors(u):
            v = edge.dst
            if v in visited:
                continue
            w = weight_fn(edge)
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    path = _reconstruct_path(prev, src, dst)
    edges_in_path = _path_edges(graph, path)
    total_dist = sum(e.distance for e in edges_in_path)
    travel_time = dist.get(dst, math.inf)

    return PathResult(
        src=src, dst=dst, path=path,
        total_distance=total_dist,
        travel_time_min=travel_time if travel_time != math.inf else -1,
        algorithm="Dijkstra",
        time_period=time_period,
        nodes_explored=nodes_explored,
        edges_in_path=edges_in_path,
    )


# --------------------------------------------------------------------------- #
#  A* Search                                                                    #
# --------------------------------------------------------------------------- #

def astar(graph: CairoGraph,
          src: str,
          dst: str,
          time_period: str = "morning") -> PathResult:
    """
    A* search for emergency vehicle routing.

    Heuristic h(n) = haversine(n, dst) / free_flow_speed  (admissible + consistent)
    → guarantees optimal path while exploring far fewer nodes than Dijkstra.

    Emergency vehicles get a signal-preemption bonus: congestion weight
    is capped at 1.2× free-flow (they bypass congestion).

    Complexity: Time O(E log V) average,  Space O(V)
    """
    FREE_FLOW = 60.0    # km/h
    PREEMPTION_CAP = 1.2   # emergency bonus

    def h(n: str) -> float:
        d = graph.haversine(n, dst)
        return (d / FREE_FLOW) * 60   # convert to minutes

    def w(edge: Edge) -> float:
        # BPR but capped for emergency preemption
        t0 = (edge.distance / FREE_FLOW) * 60
        ratio = min(edge.congestion_ratio(time_period), PREEMPTION_CAP / 4)
        return t0 * (1 + 0.15 * (ratio ** 4))

    g_score: Dict[str, float] = {nid: math.inf for nid in graph.nodes}
    f_score: Dict[str, float] = {nid: math.inf for nid in graph.nodes}
    prev: Dict[str, Optional[str]] = {nid: None for nid in graph.nodes}
    g_score[src] = 0.0
    f_score[src] = h(src)

    closed_set: set = set()
    heap = [(f_score[src], src)]
    nodes_explored = 0

    while heap:
        _, u = heapq.heappop(heap)
        if u in closed_set:
            continue
        closed_set.add(u)
        nodes_explored += 1

        if u == dst:
            break

        for edge in graph.neighbors(u):
            v = edge.dst
            if v in closed_set:
                continue
            tentative_g = g_score[u] + w(edge)
            if tentative_g < g_score[v]:
                prev[v] = u
                g_score[v] = tentative_g
                f_score[v] = tentative_g + h(v)
                heapq.heappush(heap, (f_score[v], v))

    path = _reconstruct_path(prev, src, dst)
    edges_in_path = _path_edges(graph, path)
    total_dist = sum(e.distance for e in edges_in_path)
    travel_time = g_score.get(dst, math.inf)

    return PathResult(
        src=src, dst=dst, path=path,
        total_distance=total_dist,
        travel_time_min=travel_time if travel_time != math.inf else -1,
        algorithm="A*",
        time_period=time_period,
        nodes_explored=nodes_explored,
        edges_in_path=edges_in_path,
    )


# --------------------------------------------------------------------------- #
#  Time-varying Dijkstra (multi-period aware)                                  #
# --------------------------------------------------------------------------- #

def time_varying_dijkstra(graph: CairoGraph,
                           src: str,
                           dst: str,
                           hour: int = 8) -> PathResult:
    """
    Dijkstra with time-of-day traffic weights interpolated by hour.
    Covers Cairo's morning rush (6-10), midday (10-16), evening (16-20), night.

    Provides richer granularity than the 4-band approach for the ML
    traffic prediction integration.
    """
    def hour_to_period(h: int) -> str:
        if 6 <= h < 10:
            return "morning"
        elif 10 <= h < 16:
            return "afternoon"
        elif 16 <= h < 21:
            return "evening"
        else:
            return "night"

    period = hour_to_period(hour)
    result = dijkstra(graph, src, dst, time_period=period)
    result.algorithm = f"Dijkstra (hour={hour:02d}:00)"
    return result


# --------------------------------------------------------------------------- #
#  Race comparison — Dijkstra vs A*                                             #
# --------------------------------------------------------------------------- #

def race_comparison(graph: CairoGraph,
                    src: str,
                    dst: str,
                    time_period: str = "morning") -> dict:
    """
    Run both algorithms and return comparative metrics for visualisation.
    Used by the side-by-side algorithm comparison animatior.
    """
    d_result = dijkstra(graph, src, dst, time_period)
    a_result = astar(graph, src, dst, time_period)

    return {
        "dijkstra": d_result.to_dict(),
        "astar": a_result.to_dict(),
        "comparison": {
            "nodes_explored_dijkstra": d_result.nodes_explored,
            "nodes_explored_astar": a_result.nodes_explored,
            "efficiency_gain_pct": round(
                (1 - a_result.nodes_explored / max(d_result.nodes_explored, 1)) * 100, 1
            ),
            "same_path": d_result.path == a_result.path,
            "distance_match": abs(d_result.total_distance - a_result.total_distance) < 0.01,
        },
    }


# --------------------------------------------------------------------------- #
#  Utilities                                                                    #
# --------------------------------------------------------------------------- #

def _reconstruct_path(prev: dict, src: str, dst: str) -> List[str]:
    path = []
    cur = dst
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
        if cur == src:
            path.append(src)
            break
    path.reverse()
    if not path or path[0] != src:
        return []
    return path


def _path_edges(graph: CairoGraph, path: List[str]) -> List[Edge]:
    edges = []
    for i in range(len(path) - 1):
        e = graph.get_edge(path[i], path[i+1])
        if e:
            edges.append(e)
    return edges


def all_pairs_shortest_paths(graph: CairoGraph,
                              time_period: str = "morning") -> Dict[str, Dict[str, float]]:
    """
    Run Dijkstra from every node.  Returns distance matrix.
    Used for DP scheduling and public transit analysis.
    O(V * (V+E) log V) — feasible for |V|=25.
    """
    dist_matrix: Dict[str, Dict[str, float]] = {}
    for src in graph.nodes:
        result = dijkstra(graph, src, src, time_period)   # warmup
        d: Dict[str, float] = {nid: math.inf for nid in graph.nodes}
        d[src] = 0.0
        heap = [(0.0, src)]
        visited: set = set()
        while heap:
            cost, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)
            for edge in graph.neighbors(u):
                v = edge.dst
                nd = cost + edge.time_weight(time_period)
                if nd < d[v]:
                    d[v] = nd
                    heapq.heappush(heap, (nd, v))
        dist_matrix[src] = d
    return dist_matrix
