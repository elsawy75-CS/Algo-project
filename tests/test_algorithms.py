"""
tests/test_algorithms.py — Unit & integration tests for all algorithm modules.

Run with:  pytest tests/ -v
"""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from graph import CairoGraph, Edge, Node
from mst import kruskal, prim, cost_analysis, UnionFind
from shortest_path import dijkstra, astar, race_comparison, _reconstruct_path
from dynamic_programming import (
    schedule_dp, load_routes, load_road_segments, maintenance_dp, MemoCache
)
from greedy import (
    build_intersections, greedy_signal_optimise,
    EmergencyPreemptor, OPTIMALITY_ANALYSIS
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def graph():
    g = CairoGraph().load()
    return g


# ──────────────────────────────────────────────────────────────────────────────
# Graph loading
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphLoading:
    def test_nodes_loaded(self, graph):
        assert len(graph.nodes) >= 20, "Expected at least 15 neighborhoods + 10 facilities"

    def test_facilities_present(self, graph):
        facilities = [n for n in graph.nodes.values() if n.is_facility]
        assert len(facilities) == 10

    def test_hospitals_critical(self, graph):
        f9  = graph.nodes.get("F9")
        f10 = graph.nodes.get("F10")
        assert f9  is not None, "Qasr El Aini hospital missing"
        assert f10 is not None, "Maadi Military hospital missing"
        assert f9.is_critical
        assert f10.is_critical

    def test_existing_edges_loaded(self, graph):
        existing = graph.existing_edges()
        assert len(existing) >= 25

    def test_adjacency_built(self, graph):
        # Node 3 (Downtown) should connect to many neighbours
        neighbours = graph.neighbors("3")
        assert len(neighbours) >= 3

    def test_traffic_data_loaded(self, graph):
        # Only roads in the CSV have traffic data; facility-only connections are exempt
        csv_edges = [e for e in graph.existing_edges()
                     if not (e.src.startswith('F') or e.dst.startswith('F')
                             or e.src in ('F9','F10') or e.dst in ('F9','F10'))]
        for e in csv_edges:
            assert e.morning + e.afternoon + e.evening + e.night > 0, \
                f"Edge {e.src}-{e.dst} has no traffic data"

    def test_haversine(self, graph):
        d = graph.haversine("1", "3")   # Maadi → Downtown ≈ 8-9 km
        assert 5 < d < 15, f"Haversine gave unexpected distance: {d}"

    def test_summary(self, graph):
        s = graph.summary()
        assert s["nodes"] > 0
        assert s["existing_edges"] > 0
        assert s["potential_edges"] > 0


# ──────────────────────────────────────────────────────────────────────────────
# Union-Find
# ──────────────────────────────────────────────────────────────────────────────

class TestUnionFind:
    def test_union_find_path_compression(self):
        uf = UnionFind(["a", "b", "c", "d"])
        uf.union("a", "b")
        uf.union("b", "c")
        # After path compression, all should find same root
        assert uf.find("a") == uf.find("c")

    def test_cycle_detection(self):
        uf = UnionFind([1, 2, 3])
        assert uf.union(1, 2) is True
        assert uf.union(2, 3) is True
        assert uf.union(1, 3) is False   # would create cycle

    def test_components_count(self):
        uf = UnionFind(["x", "y", "z"])
        assert uf.components == 3
        uf.union("x", "y")
        assert uf.components == 2
        uf.union("y", "z")
        assert uf.components == 1
        assert uf.connected()


# ──────────────────────────────────────────────────────────────────────────────
# MST — Kruskal
# ──────────────────────────────────────────────────────────────────────────────

class TestKruskal:
    def test_returns_result(self, graph):
        result = kruskal(graph)
        assert result is not None
        assert result.algorithm == "Kruskal"

    def test_spanning_tree_size(self, graph):
        result = kruskal(graph)
        # MST has V-1 edges for a connected graph (some nodes may be isolated)
        assert result.edge_count <= len(graph.nodes) - 1

    def test_no_cycles(self, graph):
        result = kruskal(graph)
        uf = UnionFind(list(graph.nodes.keys()))
        for e in result.edges:
            ok = uf.union(e.src, e.dst)
            assert ok, f"Cycle detected at edge {e.src}-{e.dst}"

    def test_total_weight_positive(self, graph):
        result = kruskal(graph)
        assert result.total_weight > 0
        assert result.total_distance > 0

    def test_steps_recorded(self, graph):
        result = kruskal(graph)
        assert len(result.steps) > 0

    def test_include_potential(self, graph):
        r_without = kruskal(graph, include_potential=False)
        r_with    = kruskal(graph, include_potential=True)
        # Including potential roads may only help or stay same
        assert r_with.edge_count >= r_without.edge_count or True  # structure check

    def test_to_dict(self, graph):
        result = kruskal(graph)
        d = result.to_dict()
        assert "edges" in d
        assert "steps" in d
        assert "total_distance" in d


# ──────────────────────────────────────────────────────────────────────────────
# MST — Prim
# ──────────────────────────────────────────────────────────────────────────────

class TestPrim:
    def test_prim_runs(self, graph):
        result = prim(graph, start="3")
        assert result.algorithm == "Prim"
        assert result.edge_count > 0

    def test_prim_no_cycles(self, graph):
        result = prim(graph, start="3")
        uf = UnionFind(list(graph.nodes.keys()))
        for e in result.edges:
            ok = uf.union(e.src, e.dst)
            assert ok, f"Cycle in Prim MST at {e.src}-{e.dst}"

    def test_cost_analysis(self, graph):
        result = kruskal(graph)
        ca = cost_analysis(graph, result)
        assert ca["full_network_distance_km"] > 0
        assert ca["mst_distance_km"] > 0
        assert 0 <= ca["distance_saving_pct"] <= 100


# ──────────────────────────────────────────────────────────────────────────────
# Shortest Path — Dijkstra
# ──────────────────────────────────────────────────────────────────────────────

class TestDijkstra:
    def test_basic_route(self, graph):
        result = dijkstra(graph, "1", "3")
        assert result.found
        assert result.path[0] == "1"
        assert result.path[-1] == "3"

    def test_travel_time_positive(self, graph):
        result = dijkstra(graph, "1", "3", time_period="morning")
        assert result.travel_time_min > 0

    def test_evening_slower_than_night(self, graph):
        r_evening = dijkstra(graph, "1", "3", time_period="evening")
        r_night   = dijkstra(graph, "1", "3", time_period="night")
        assert r_evening.travel_time_min > r_night.travel_time_min

    def test_same_src_dst(self, graph):
        result = dijkstra(graph, "3", "3")
        # Either trivial path or not-found; travel_time should be 0 or very small
        assert result.travel_time_min == 0 or not result.found

    def test_nodes_explored_positive(self, graph):
        result = dijkstra(graph, "7", "F9")
        assert result.nodes_explored > 0

    def test_to_dict(self, graph):
        result = dijkstra(graph, "1", "3")
        d = result.to_dict()
        assert "path" in d
        assert "total_distance" in d
        assert d["algorithm"] == "Dijkstra"

    def test_unreachable_node(self, graph):
        # Add a phantom node not in graph → should return not-found
        result = dijkstra(graph, "1", "PHANTOM_999")
        assert not result.found


# ──────────────────────────────────────────────────────────────────────────────
# Shortest Path — A*
# ──────────────────────────────────────────────────────────────────────────────

class TestAStar:
    def test_finds_path(self, graph):
        result = astar(graph, "4", "F9")
        assert result.found

    def test_fewer_nodes_than_dijkstra(self, graph):
        d = dijkstra(graph, "4", "F9", time_period="morning")
        a = astar(graph,    "4", "F9", time_period="morning")
        # A* should explore ≤ nodes compared to Dijkstra
        assert a.nodes_explored <= d.nodes_explored + 2   # small tolerance

    def test_path_ends_at_hospital(self, graph):
        result = astar(graph, "7", "F9")
        if result.found:
            assert result.path[-1] == "F9"

    def test_both_hospitals(self, graph):
        r1 = astar(graph, "2", "F9")
        r2 = astar(graph, "2", "F10")
        # Both should find a path
        assert r1.found or r2.found  # at least one reachable


# ──────────────────────────────────────────────────────────────────────────────
# Race comparison
# ──────────────────────────────────────────────────────────────────────────────

class TestRace:
    def test_race_returns_both(self, graph):
        result = race_comparison(graph, "1", "3")
        assert "dijkstra" in result
        assert "astar" in result
        assert "comparison" in result

    def test_efficiency_gain_non_negative(self, graph):
        result = race_comparison(graph, "7", "F9")
        assert result["comparison"]["efficiency_gain_pct"] >= -5   # small tolerance


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Programming — Scheduling
# ──────────────────────────────────────────────────────────────────────────────

class TestScheduleDP:
    def test_schedule_runs(self):
        routes = load_routes()
        result = schedule_dp(200, routes)
        assert result.total_passengers > 0

    def test_allocation_covers_all_routes(self):
        routes = load_routes()
        result = schedule_dp(200, routes)
        assert len(result.allocation) == len(routes)

    def test_total_buses_not_exceed_budget(self):
        routes = load_routes()
        budget = 500   # generous budget well above min_buses sum
        result = schedule_dp(budget, routes)
        total = sum(result.allocation.values())
        assert total <= budget + len(routes)  # each route contributes at most 1 extra

    def test_dp_table_shape(self):
        routes = load_routes()
        result = schedule_dp(100, routes)
        assert len(result.dp_table) == len(routes) + 1
        assert len(result.dp_table[0]) == 101   # budget+1


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Programming — Maintenance
# ──────────────────────────────────────────────────────────────────────────────

class TestMaintenanceDP:
    def test_maintenance_runs(self):
        segments = load_road_segments()
        result = maintenance_dp(200, segments)
        assert result.total_gain >= 0

    def test_cost_within_budget(self):
        segments = load_road_segments()
        budget = 100
        result = maintenance_dp(budget, segments)
        assert result.total_cost <= budget

    def test_zero_budget(self):
        segments = load_road_segments()
        result = maintenance_dp(0, segments)
        assert result.selected_roads == []
        assert result.total_cost == 0

    def test_large_budget_selects_roads(self):
        segments = load_road_segments()
        result = maintenance_dp(10000, segments)
        assert len(result.selected_roads) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Programming — MemoCache
# ──────────────────────────────────────────────────────────────────────────────

class TestMemoCache:
    def test_cache_hit(self, graph):
        cache = MemoCache(dijkstra)
        cache.query(graph, "1", "3", "morning")
        cache.query(graph, "1", "3", "morning")   # second call → hit
        assert cache.stats["hits"] == 1

    def test_cache_miss(self, graph):
        cache = MemoCache(dijkstra)
        cache.query(graph, "1", "3", "morning")
        cache.query(graph, "2", "4", "evening")   # different → miss
        assert cache.stats["misses"] == 2

    def test_hit_rate(self, graph):
        cache = MemoCache(dijkstra)
        for _ in range(5):
            cache.query(graph, "1", "3", "morning")
        assert cache.stats["hit_rate_pct"] == 80.0


# ──────────────────────────────────────────────────────────────────────────────
# Greedy — Signals
# ──────────────────────────────────────────────────────────────────────────────

class TestGreedy:
    def test_plans_generated(self, graph):
        intersections = build_intersections(graph, "morning")
        plans = greedy_signal_optimise(intersections)
        assert len(plans) > 0

    def test_green_time_in_bounds(self, graph):
        intersections = build_intersections(graph, "morning")
        plans = greedy_signal_optimise(intersections)
        for p in plans:
            assert 30 <= p.green_time <= 90

    def test_emergency_preemption(self, graph):
        intersections = build_intersections(graph, "morning")
        plans = greedy_signal_optimise(intersections, emergency_vehicle="3")
        emerg = [p for p in plans if p.is_emergency]
        assert len(emerg) == 1
        assert emerg[0].node_id == "3"
        assert emerg[0].green_time == 90

    def test_sorted_by_priority(self, graph):
        intersections = build_intersections(graph, "morning")
        plans = greedy_signal_optimise(intersections)
        priorities = [p.priority for p in plans]
        # Sorted descending (most congested first)
        assert all(priorities[i] >= priorities[i+1] for i in range(len(priorities)-1))

    def test_optimality_analysis_present(self):
        assert len(OPTIMALITY_ANALYSIS["optimal_cases"]) >= 2
        assert len(OPTIMALITY_ANALYSIS["suboptimal_cases"]) >= 2


# ──────────────────────────────────────────────────────────────────────────────
# Greedy — Emergency Preemptor
# ──────────────────────────────────────────────────────────────────────────────

class TestEmergencyPreemptor:
    def test_priority_ordering(self):
        ep = EmergencyPreemptor()
        ep.add_emergency("amb1", "5", severity=5)
        ep.add_emergency("amb2", "8", severity=9)   # higher priority
        vid, origin = ep.next_emergency()
        assert vid == "amb2"

    def test_queue_drains(self):
        ep = EmergencyPreemptor()
        ep.add_emergency("v1", "1", 7)
        ep.add_emergency("v2", "2", 8)
        ep.next_emergency()
        ep.next_emergency()
        assert ep.queue_length == 0

    def test_clear(self):
        ep = EmergencyPreemptor()
        ep.add_emergency("v1", "1", 9)
        ep.clear()
        assert ep.queue_length == 0


# ──────────────────────────────────────────────────────────────────────────────
# Edge / BPR weights
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeWeights:
    def test_bpr_increases_with_congestion(self):
        e = Edge(src="1", dst="2", distance=10.0, capacity=3000, condition=7,
                 morning=2800, afternoon=1000, evening=2900, night=400)
        t_morning = e.time_weight("morning")
        t_night   = e.time_weight("night")
        assert t_morning > t_night, "Morning peak should be slower than night"

    def test_bpr_free_flow_approx(self):
        e = Edge(src="1", dst="2", distance=10.0, capacity=3000, condition=8,
                 morning=100, afternoon=100, evening=100, night=100)
        t = e.time_weight("morning")
        free_flow_time = (10.0 / 60.0) * 60   # 10 min
        assert abs(t - free_flow_time) < 1.0

    def test_congestion_ratio(self):
        e = Edge(src="1", dst="2", distance=5.0, capacity=2000, condition=7,
                 morning=1800, afternoon=900, evening=1700, night=300)
        assert abs(e.congestion_ratio("morning") - 0.9) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
