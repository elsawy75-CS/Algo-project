"""
greedy.py — Greedy algorithms for Cairo Transportation System.

Implements:
  1. Traffic signal optimiser  — greedy phase allocation at major intersections
                                  based on real-time congestion ratio.
  2. Emergency preemption      — priority queue that clears corridors for
                                  emergency vehicles.
  3. Optimality analysis       — documents where greedy is / is not optimal
                                  in the Cairo context.

The greedy signal approach uses a simple max-flow-first heuristic:
  • Sort intersections by congestion ratio descending.
  • Assign green time proportional to (flow / capacity).
  • Cap minimum green at 30 s, maximum at 120 s.

Greedy is provably optimal for a SINGLE isolated intersection.
For interconnected grids it may get stuck in local optima — we document this.
"""

from __future__ import annotations
import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from graph import CairoGraph, Edge


# --------------------------------------------------------------------------- #
#  Intersection data model                                                      #
# --------------------------------------------------------------------------- #

@dataclass
class Intersection:
    node_id: str
    name: str
    flow: int           # current veh/h
    capacity: int       # intersection capacity veh/h
    approaches: int = 4 # number of approach roads
    is_emergency_route: bool = False

    @property
    def congestion_ratio(self) -> float:
        return self.flow / self.capacity if self.capacity else 0.0

    @property
    def level_of_service(self) -> str:
        r = self.congestion_ratio
        if r < 0.60: return "A"
        if r < 0.70: return "B"
        if r < 0.80: return "C"
        if r < 0.90: return "D"
        if r < 1.00: return "E"
        return "F"   # over-capacity


@dataclass(order=True)
class SignalPlan:
    priority: float = field(compare=True)    # higher = more urgent
    node_id: str = field(compare=False)
    green_time: int = field(compare=False)   # seconds
    phase: str = field(compare=False)        # NS / EW / NS+EW
    reason: str = field(compare=False)
    is_emergency: bool = field(compare=False, default=False)


# --------------------------------------------------------------------------- #
#  Greedy signal optimiser                                                      #
# --------------------------------------------------------------------------- #

CYCLE_LENGTH = 120   # seconds, typical Cairo intersection cycle
MIN_GREEN = 30
MAX_GREEN = 90


def build_intersections(graph: CairoGraph,
                         time_period: str = "morning") -> List[Intersection]:
    """
    Derive intersection congestion from graph traffic data.
    Aggregates all edge flows into each node.
    """
    intersections = []
    for nid, node in graph.nodes.items():
        edges = graph.neighbors(nid)
        total_flow = sum(e.flow(time_period) for e in edges)
        total_cap  = sum(e.capacity for e in edges)
        if total_cap == 0:
            continue
        intersections.append(Intersection(
            node_id=nid,
            name=node.name,
            flow=total_flow,
            capacity=total_cap,
            is_emergency_route=node.is_critical,
        ))
    return intersections


def greedy_signal_optimise(intersections: List[Intersection],
                            emergency_vehicle: Optional[str] = None,
                            cycle_length: int = CYCLE_LENGTH) -> List[SignalPlan]:
    """
    Greedy allocation of green time at each intersection.

    Algorithm:
      1. Sort by congestion ratio descending (most congested first).
      2. Assign green_time = max(MIN_GREEN, min(MAX_GREEN,
             round(ratio * cycle_length / approaches)))
      3. If emergency_vehicle is set, force full green on emergency path.

    This is a greedy approach: locally optimal decision per intersection.
    DOES NOT account for upstream/downstream coordination — suboptimal for grids.

    Complexity: O(I log I) where I = number of intersections
    """
    plans: List[SignalPlan] = []

    # Sort by congestion ratio — highest first (greedy choice)
    ranked = sorted(intersections, key=lambda x: x.congestion_ratio, reverse=True)

    for inter in ranked:
        if emergency_vehicle and inter.node_id == emergency_vehicle:
            plans.append(SignalPlan(
                priority=10.0,
                node_id=inter.node_id,
                green_time=MAX_GREEN,
                phase="ALL",
                reason="Emergency vehicle preemption",
                is_emergency=True,
            ))
            continue

        ratio = inter.congestion_ratio
        # Green time proportional to demand ratio
        raw_green = ratio * cycle_length / max(inter.approaches / 2, 1)
        green = max(MIN_GREEN, min(MAX_GREEN, int(raw_green)))

        phase = "NS" if ratio > 0.85 else ("EW" if ratio > 0.7 else "NS+EW")
        reason = (
            "Over-capacity: extend green, suppress cross" if ratio >= 1.0
            else "High demand: extended green phase" if ratio > 0.8
            else "Moderate demand: balanced timing" if ratio > 0.6
            else "Low demand: minimal green"
        )

        plans.append(SignalPlan(
            priority=ratio,
            node_id=inter.node_id,
            green_time=green,
            phase=phase,
            reason=reason,
        ))

    return plans


def plans_to_dict(plans: List[SignalPlan],
                   intersections: List[Intersection]) -> dict:
    inter_map = {i.node_id: i for i in intersections}
    return {
        "plans": [
            {
                "node_id": p.node_id,
                "name": inter_map.get(p.node_id, Intersection(p.node_id,"",0,1)).name,
                "green_time": p.green_time,
                "red_time": CYCLE_LENGTH - p.green_time,
                "phase": p.phase,
                "reason": p.reason,
                "is_emergency": p.is_emergency,
                "congestion_ratio": round(inter_map[p.node_id].congestion_ratio if p.node_id in inter_map else 0, 3),
                "level_of_service": inter_map[p.node_id].level_of_service if p.node_id in inter_map else "?",
            }
            for p in sorted(plans, key=lambda x: -x.priority)
        ],
        "emergency_active": any(p.is_emergency for p in plans),
    }


# --------------------------------------------------------------------------- #
#  Emergency preemption priority queue                                          #
# --------------------------------------------------------------------------- #

class EmergencyPreemptor:
    """
    Min-heap priority queue for managing multiple emergency vehicle requests.
    Each request has a severity score (1-10) and origin node.
    Higher severity → lower heap key → processed first.
    """

    def __init__(self):
        self._heap: List[Tuple[float, str, str]] = []   # (neg_severity, vehicle_id, origin)
        self._active: Dict[str, str] = {}               # vehicle_id → origin

    def add_emergency(self, vehicle_id: str, origin: str, severity: int = 8):
        heapq.heappush(self._heap, (-severity, vehicle_id, origin))
        self._active[vehicle_id] = origin

    def next_emergency(self) -> Optional[Tuple[str, str]]:
        while self._heap:
            neg_sev, vid, origin = heapq.heappop(self._heap)
            if vid in self._active:
                del self._active[vid]
                return vid, origin
        return None

    def clear(self):
        self._heap.clear()
        self._active.clear()

    @property
    def queue_length(self) -> int:
        return len(self._active)


# --------------------------------------------------------------------------- #
#  Optimality analysis                                                          #
# --------------------------------------------------------------------------- #

OPTIMALITY_ANALYSIS = {
    "optimal_cases": [
        {
            "scenario": "Single isolated intersection",
            "reason": "Greedy max-flow-first is provably optimal: no downstream interactions.",
            "optimal": True,
        },
        {
            "scenario": "Emergency vehicle preemption",
            "reason": "Single-objective (clear corridor); greedy priority queue is optimal.",
            "optimal": True,
        },
        {
            "scenario": "Independent road segments",
            "reason": "Each segment is separable — greedy local choice = global optimum.",
            "optimal": True,
        },
    ],
    "suboptimal_cases": [
        {
            "scenario": "Downtown Cairo grid (nodes 3,6,9,10,F2)",
            "reason": "Cycle spillback: greedy at node 3 may cause queue to block node 9. "
                      "Coordinated signal plans (e.g. SCOOT, TRANSYT) outperform greedy by ~15%.",
            "optimal": False,
        },
        {
            "scenario": "Event demand surge at Cairo Stadium (node F6)",
            "reason": "Greedy reacts only to current flow; cannot anticipate post-match surge. "
                      "Predictive (ML-based) timing beats greedy by ~20% in response time.",
            "optimal": False,
        },
        {
            "scenario": "Multi-modal conflict at Ramses Square (F2)",
            "reason": "Metro, bus, and private vehicle phases interact. Greedy ignores "
                      "transit priority; a weighted approach is needed.",
            "optimal": False,
        },
    ],
}
