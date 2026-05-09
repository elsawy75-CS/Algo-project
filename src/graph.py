"""
graph.py — Cairo Transportation Network Graph
Weighted graph representation with adjacency list, supporting
time-varying edge weights and facility priority flags.
"""

from __future__ import annotations
import csv
import math
import heapq
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

DATA_DIR = Path(__file__).parent.parent / "data"

# --------------------------------------------------------------------------- #
#  Data classes                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class Node:
    id: str
    name: str
    population: int
    node_type: str          # Residential / Mixed / Business / Industrial / Government
    x: float                # longitude
    y: float                # latitude
    is_facility: bool = False
    is_critical: bool = False   # hospitals / government hubs → priority in MST

@dataclass
class Edge:
    src: str
    dst: str
    distance: float         # km
    capacity: int           # veh/h
    condition: int          # 1-10 road quality
    is_potential: bool = False
    construction_cost: float = 0.0   # million EGP (potential roads)

    # Time-varying traffic flows veh/h
    morning: int = 0
    afternoon: int = 0
    evening: int = 0
    night: int = 0

    def flow(self, time_period: str) -> int:
        return getattr(self, time_period, self.morning)

    def congestion_ratio(self, time_period: str) -> float:
        f = self.flow(time_period)
        return f / self.capacity if self.capacity else 0.0

    def time_weight(self, time_period: str) -> float:
        """
        Travel-time weight accounting for congestion.
        Uses BPR (Bureau of Public Roads) function:
          t = t0 * (1 + 0.15*(v/c)^4)
        where t0 = base travel time = distance / free-flow speed
        """
        free_flow_speed = 60.0  # km/h urban arterial
        t0 = self.distance / free_flow_speed * 60  # minutes
        ratio = self.congestion_ratio(time_period)
        bpr = t0 * (1 + 0.15 * (ratio ** 4))
        return round(bpr, 4)

    def mst_weight(self) -> float:
        """
        MST construction cost weight.
        Critical-facility edges get 50 % weight reduction (priority connectivity).
        """
        base = self.distance if not self.is_potential else self.construction_cost
        return base


# --------------------------------------------------------------------------- #
#  Graph                                                                        #
# --------------------------------------------------------------------------- #

class CairoGraph:
    """Weighted undirected graph of Cairo's transport network."""

    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._adj: Dict[str, List[Edge]] = {}   # adjacency list

    # ------------------------------------------------------------------ #
    #  Loaders                                                             #
    # ------------------------------------------------------------------ #

    def load(self):
        self._load_nodes()
        self._load_facilities()
        self._load_edges()
        self._load_potential_edges()
        self._load_traffic()
        self._build_adj()
        return self

    def _load_nodes(self):
        with open(DATA_DIR / "neighborhoods.csv") as f:
            for row in csv.DictReader(f):
                nid = row["ID"]
                n = Node(
                    id=nid,
                    name=row["Name"],
                    population=int(row["Population"]),
                    node_type=row["Type"],
                    x=float(row["X-coordinate"]),
                    y=float(row["Y-coordinate"]),
                    is_critical=(row["Type"] == "Government"),
                )
                self.nodes[nid] = n

    def _load_facilities(self):
        with open(DATA_DIR / "facilities.csv") as f:
            for row in csv.DictReader(f):
                fid = row["ID"]
                is_critical = row["Type"] in ("Medical", "Transit Hub")
                n = Node(
                    id=fid,
                    name=row["Name"],
                    population=0,
                    node_type=row["Type"],
                    x=float(row["X-coordinate"]),
                    y=float(row["Y-coordinate"]),
                    is_facility=True,
                    is_critical=is_critical,
                )
                self.nodes[fid] = n

    def _load_edges(self):
        with open(DATA_DIR / "existing_roads.csv") as f:
            for row in csv.DictReader(f):
                e = Edge(
                    src=row["FromID"],
                    dst=row["ToID"],
                    distance=float(row["Distance(km)"]),
                    capacity=int(row["Current Capacity(veh/h)"]),
                    condition=int(row["Condition(1-10)"]),
                )
                self.edges.append(e)

        # Add connections to medical facilities not in CSV
        # (hospitals are accessible from nearby nodes)
        extra = [
            ("3",  "F9",  1.5, 2000, 8),   # Downtown → Qasr El Aini
            ("6",  "F9",  2.0, 1800, 8),   # Zamalek → Qasr El Aini
            ("1",  "F10", 1.8, 2000, 9),   # Maadi → Maadi Military
            ("12", "F10", 5.0, 1800, 8),   # Helwan → Maadi Military
        ]
        for src, dst, dist, cap, cond in extra:
            self.edges.append(Edge(
                src=src, dst=dst,
                distance=dist, capacity=cap, condition=cond,
                morning=int(cap*0.6), afternoon=int(cap*0.3),
                evening=int(cap*0.55), night=int(cap*0.15),
            ))

    def _load_potential_edges(self):
        with open(DATA_DIR / "potential_roads.csv") as f:
            for row in csv.DictReader(f):
                e = Edge(
                    src=row["FromID"],
                    dst=row["ToID"],
                    distance=float(row["Distance(km)"]),
                    capacity=int(row["Estimated Capacity(veh/h)"]),
                    condition=10,
                    is_potential=True,
                    construction_cost=float(row["Construction Cost(Million EGP)"]),
                )
                self.edges.append(e)

    def _load_traffic(self):
        traffic: Dict[str, Dict[str, int]] = {}
        with open(DATA_DIR / "traffic_flow.csv") as f:
            for row in csv.DictReader(f):
                rid = row["RoadID"]
                traffic[rid] = {
                    "morning": int(row["Morning Peak(veh/h)"]),
                    "afternoon": int(row["Afternoon(veh/h)"]),
                    "evening": int(row["Evening Peak(veh/h)"]),
                    "night": int(row["Night(veh/h)"]),
                }
        for e in self.edges:
            key = f"{e.src}-{e.dst}"
            rev = f"{e.dst}-{e.src}"
            t = traffic.get(key) or traffic.get(rev) or {}
            e.morning   = t.get("morning", 0)
            e.afternoon = t.get("afternoon", 0)
            e.evening   = t.get("evening", 0)
            e.night     = t.get("night", 0)

    def _build_adj(self):
        self._adj = {nid: [] for nid in self.nodes}
        for e in self.edges:
            if e.src in self._adj:
                self._adj[e.src].append(e)
            if e.dst in self._adj:
                # Create reverse edge view
                rev = Edge(
                    src=e.dst, dst=e.src,
                    distance=e.distance, capacity=e.capacity,
                    condition=e.condition, is_potential=e.is_potential,
                    construction_cost=e.construction_cost,
                    morning=e.morning, afternoon=e.afternoon,
                    evening=e.evening, night=e.night,
                )
                self._adj[e.dst].append(rev)

    # ------------------------------------------------------------------ #
    #  Accessors                                                           #
    # ------------------------------------------------------------------ #

    def neighbors(self, node_id: str) -> List[Edge]:
        return self._adj.get(node_id, [])

    def get_edge(self, src: str, dst: str) -> Optional[Edge]:
        for e in self._adj.get(src, []):
            if e.dst == dst:
                return e
        return None

    def node_ids(self) -> List[str]:
        return list(self.nodes.keys())

    def existing_edges(self) -> List[Edge]:
        return [e for e in self.edges if not e.is_potential]

    def potential_edges(self) -> List[Edge]:
        return [e for e in self.edges if e.is_potential]

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def haversine(self, a: str, b: str) -> float:
        """Great-circle distance in km (used as A* heuristic)."""
        na, nb = self.nodes.get(a), self.nodes.get(b)
        if not na or not nb:
            return 0.0
        R = 6371.0
        lat1, lon1 = math.radians(na.y), math.radians(na.x)
        lat2, lon2 = math.radians(nb.y), math.radians(nb.x)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a_ = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        return 2 * R * math.asin(math.sqrt(a_))

    def summary(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "existing_edges": len(self.existing_edges()),
            "potential_edges": len(self.potential_edges()),
            "facilities": sum(1 for n in self.nodes.values() if n.is_facility),
            "critical_nodes": sum(1 for n in self.nodes.values() if n.is_critical),
        }
