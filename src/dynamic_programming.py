"""
dynamic_programming.py — DP solutions for Cairo Transportation System.

Implements:
  1. Vehicle scheduling DP   — allocate bus/metro fleet across routes to
                               maximise daily passenger coverage.
  2. Road maintenance DP     — knapsack allocation of maintenance budget
                               to maximise condition-score improvement.
  3. Memoised route planning — @lru_cache wrapper around shortest-path queries
                               for repeated O(1) lookups.

All DP tables are returned for step-by-step visualisation.
"""

from __future__ import annotations
import csv
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

DATA_DIR = Path(__file__).parent.parent / "data"


# --------------------------------------------------------------------------- #
#  1. Vehicle Scheduling DP                                                     #
# --------------------------------------------------------------------------- #
#
#  Problem:  Allocate B buses across R routes to maximise total passengers.
#  Each route i has a "passengers-per-bus" rate p_i.
#  Decision: assign b_i buses to route i  (b_i ≥ min_i, sum b_i = B).
#
#  State:    dp[i][j] = max passengers using j buses across first i routes.
#  Transition:
#    dp[i][j] = max over k in [min_i .. j]:
#                  dp[i-1][j-k]  +  passengers(i, k)
#  where passengers(i, k) = min(k, max_k_i) * p_i   (diminishing returns cap)
#
#  Complexity: Time O(R * B^2),  Space O(R * B)
# --------------------------------------------------------------------------- #

@dataclass
class Route:
    id: str
    name: str
    min_buses: int      # current assignment (lower bound)
    max_buses: int      # upper limit (route capacity)
    pax_per_bus: float  # passengers per bus per day
    mode: str           # bus / metro


@dataclass
class SchedulingResult:
    allocation: Dict[str, int]   # route_id → buses assigned
    total_passengers: int
    dp_table: List[List[int]]    # for step visualisation
    routes: List[Route]
    budget_buses: int


def load_routes() -> List[Route]:
    routes = []
    with open(DATA_DIR / "bus_routes.csv") as f:
        for row in csv.DictReader(f):
            buses = int(row["Buses Assigned"])
            pax = int(row["Daily Passengers"])
            routes.append(Route(
                id=row["RouteID"],
                name=f"Bus {row['RouteID']}",
                min_buses=max(1, buses - 5),
                max_buses=buses + 15,
                pax_per_bus=pax / buses,
                mode="bus",
            ))
    with open(DATA_DIR / "metro_lines.csv") as f:
        for row in csv.DictReader(f):
            lid = row["LineID"]
            pax = int(row["Daily Passengers"])
            routes.append(Route(
                id=lid,
                name=row["Name"],
                min_buses=10,
                max_buses=40,
                pax_per_bus=pax / 20,   # normalised per train unit
                mode="metro",
            ))
    return routes


def schedule_dp(budget_buses: int,
                routes: Optional[List[Route]] = None) -> SchedulingResult:
    """
    Unbounded knapsack variant: allocate exactly budget_buses units.
    Returns optimal allocation and full DP table.
    """
    if routes is None:
        routes = load_routes()

    R = len(routes)

    # budget_buses is TOTAL buses. Each route must receive at least min_buses,
    # so the extra buses available above the mandatory minimums is:
    sum_min = sum(r.min_buses for r in routes)
    B_extra = max(0, budget_buses - sum_min)   # extra units to distribute

    # dp[i][j]: max passengers when j EXTRA buses are distributed across first i routes
    # Each route i already gets its min_buses; j is the surplus on top.
    dp = [[0] * (B_extra + 1) for _ in range(R + 1)]

    # Seed row 0 with base passengers from mandatory minimums
    for i in range(1, R + 1):
        r = routes[i - 1]
        base_pax = int(r.min_buses * r.pax_per_bus)
        for j in range(B_extra + 1):
            # Option A: give no extra buses to route i
            dp[i][j] = dp[i-1][j] + base_pax
            # Option B: give e extra buses to route i (e = 1 .. min(j, max_extra))
            max_extra = r.max_buses - r.min_buses
            for e in range(1, min(j, max_extra) + 1):
                actual_buses = r.min_buses + e
                pax = int(actual_buses * r.pax_per_bus)
                candidate = dp[i-1][j - e] + pax
                if candidate > dp[i][j]:
                    dp[i][j] = candidate

    # Backtrack to find allocation
    allocation: Dict[str, int] = {}
    j = B_extra
    for i in range(R, 0, -1):
        r = routes[i - 1]
        max_extra = r.max_buses - r.min_buses
        best_extra = 0   # default: no extra buses for this route
        best_val = -1
        for e in range(0, min(j, max_extra) + 1):
            actual_buses = r.min_buses + e
            pax = int(actual_buses * r.pax_per_bus)
            remaining = j - e
            prev_val = dp[i-1][remaining]
            if prev_val + pax > best_val:
                best_val = prev_val + pax
                best_extra = e
        allocation[r.id] = r.min_buses + best_extra
        j = j - best_extra

    return SchedulingResult(
        allocation=allocation,
        total_passengers=dp[R][B_extra],
        dp_table=[row + [row[-1]] * (budget_buses - B_extra) for row in dp],
        routes=routes,
        budget_buses=budget_buses,
    )


def scheduling_result_to_dict(res: SchedulingResult) -> dict:
    return {
        "budget_buses": res.budget_buses,
        "total_passengers": res.total_passengers,
        "allocation": [
            {
                "route_id": r.id,
                "route_name": r.name,
                "mode": r.mode,
                "buses_assigned": res.allocation.get(r.id, r.min_buses),
                "estimated_passengers": int(res.allocation.get(r.id, r.min_buses) * r.pax_per_bus),
                "pax_per_bus": round(r.pax_per_bus, 0),
            }
            for r in res.routes
        ],
        "dp_table_sample": [row[:min(21, len(row))] for row in res.dp_table[:min(6, len(res.dp_table))]],
    }


# --------------------------------------------------------------------------- #
#  2. Road Maintenance Knapsack DP                                              #
# --------------------------------------------------------------------------- #
#
#  Problem:  Given a budget B (million EGP) and N road segments,
#            choose segments to maintain to maximise total condition gain.
#  Each road segment has:
#    cost_i  = maintenance cost (million EGP) ∝ distance × (10 - condition)
#    gain_i  = condition score improvement (integer, 1-5)
#
#  Standard 0/1 knapsack:
#    dp[i][b] = max gain using budget b for first i roads
#  Complexity: Time O(N * B),  Space O(N * B)
# --------------------------------------------------------------------------- #

@dataclass
class RoadSegment:
    road_id: str
    src: str
    dst: str
    distance: float
    condition: int
    capacity: int
    cost: int           # maintenance cost (million EGP, discretised)
    gain: int           # condition score improvement


@dataclass
class MaintenanceResult:
    selected_roads: List[RoadSegment]
    total_cost: int
    total_gain: int
    dp_table: List[List[int]]
    budget: int


def load_road_segments() -> List[RoadSegment]:
    segments = []
    with open(DATA_DIR / "existing_roads.csv") as f:
        for row in csv.DictReader(f):
            cond = int(row["Condition(1-10)"])
            dist = float(row["Distance(km)"])
            if cond < 9:   # only roads that benefit from maintenance
                deficit = 10 - cond
                cost = max(1, int(dist * deficit * 2))      # rough EGP estimate
                gain = min(5, deficit)
                segments.append(RoadSegment(
                    road_id=f"{row['FromID']}-{row['ToID']}",
                    src=row["FromID"],
                    dst=row["ToID"],
                    distance=dist,
                    condition=cond,
                    capacity=int(row["Current Capacity(veh/h)"]),
                    cost=cost,
                    gain=gain,
                ))
    return segments


def maintenance_dp(budget_mEGP: int,
                   segments: Optional[List[RoadSegment]] = None) -> MaintenanceResult:
    """
    0/1 knapsack DP for road maintenance budget allocation.
    """
    if segments is None:
        segments = load_road_segments()

    N = len(segments)
    B = budget_mEGP

    dp = [[0] * (B + 1) for _ in range(N + 1)]

    for i in range(1, N + 1):
        seg = segments[i - 1]
        for b in range(B + 1):
            dp[i][b] = dp[i-1][b]
            if seg.cost <= b:
                dp[i][b] = max(dp[i][b], dp[i-1][b - seg.cost] + seg.gain)

    # Backtrack
    selected: List[RoadSegment] = []
    b = B
    for i in range(N, 0, -1):
        if dp[i][b] != dp[i-1][b]:
            selected.append(segments[i-1])
            b -= segments[i-1].cost

    return MaintenanceResult(
        selected_roads=selected,
        total_cost=sum(s.cost for s in selected),
        total_gain=sum(s.gain for s in selected),
        dp_table=dp,
        budget=budget_mEGP,
    )


def maintenance_result_to_dict(res: MaintenanceResult) -> dict:
    return {
        "budget_mEGP": res.budget,
        "total_cost": res.total_cost,
        "total_gain": res.total_gain,
        "selected_roads": [
            {
                "road_id": s.road_id,
                "src": s.src,
                "dst": s.dst,
                "distance": s.distance,
                "current_condition": s.condition,
                "new_condition": min(10, s.condition + s.gain),
                "cost_mEGP": s.cost,
                "gain": s.gain,
            }
            for s in res.selected_roads
        ],
        "dp_table_sample": [row[:min(21, len(row))] for row in res.dp_table[:min(6, len(res.dp_table))]],
    }


# --------------------------------------------------------------------------- #
#  3. Memoised Route Cache                                                      #
# --------------------------------------------------------------------------- #

class MemoCache:
    """
    LRU-cached route lookup.  Wraps any shortest-path function.
    Stores up to 256 recent (src, dst, time_period) → PathResult mappings.
    Demonstrates memoisation technique for route planning.
    """

    def __init__(self, path_fn):
        self._fn = path_fn
        self._cache: Dict[Tuple, object] = {}
        self._hits = 0
        self._misses = 0

    def query(self, graph, src: str, dst: str, time_period: str = "morning"):
        key = (src, dst, time_period)
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        result = self._fn(graph, src, dst, time_period)
        if len(self._cache) >= 256:
            # Evict oldest entry
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result
        return result

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_queries": total,
            "hit_rate_pct": round(self._hits / max(total, 1) * 100, 1),
            "cached_entries": len(self._cache),
        }
