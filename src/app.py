"""
app.py — Cairo Smart Transportation System — Flask Web API.

Endpoints:
  GET  /                        → serve index.html
  GET  /api/graph               → full network data for visualisation
  GET  /api/mst                 → Kruskal / Prim MST result
  POST /api/route               → Dijkstra route query
  POST /api/astar               → A* emergency route query
  POST /api/race                → side-by-side Dijkstra vs A* comparison
  GET  /api/traffic             → time-varying traffic data
  POST /api/signals             → greedy signal optimisation
  POST /api/schedule            → DP vehicle scheduling
  POST /api/maintenance         → DP road maintenance knapsack
  POST /api/predict             → ML congestion prediction
  GET  /api/forecast/<road_id>  → 24h ML congestion forecast
  GET  /api/train               → trigger ML model training
  GET  /api/summary             → system summary stats
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Source imports (graph, algorithms)
import sys
sys.path.insert(0, str(Path(__file__).parent))

from graph import CairoGraph
from mst import kruskal, prim, cost_analysis
from shortest_path import dijkstra, astar, race_comparison, time_varying_dijkstra
from dynamic_programming import (
    schedule_dp, scheduling_result_to_dict,
    maintenance_dp, maintenance_result_to_dict,
    load_routes, load_road_segments,
)
from greedy import (
    build_intersections, greedy_signal_optimise,
    plans_to_dict, OPTIMALITY_ANALYSIS,
)
from ml_prediction import (
    train_models, predict_congestion, forecast_24h,
)

# --------------------------------------------------------------------------- #
#  App setup                                                                    #
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

app = Flask(
    __name__,
    static_folder=str(STATIC_DIR),
    template_folder=str(TEMPLATE_DIR),
)
CORS(app)

# --------------------------------------------------------------------------- #
#  Initialise graph at startup                                                  #
# --------------------------------------------------------------------------- #

_graph: CairoGraph = None

def get_graph() -> CairoGraph:
    global _graph
    if _graph is None:
        _graph = CairoGraph().load()
    return _graph


# --------------------------------------------------------------------------- #
#  Root — serve frontend                                                        #
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    return send_from_directory(str(TEMPLATE_DIR), "index.html")

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory(str(STATIC_DIR), path)


# --------------------------------------------------------------------------- #
#  /api/summary                                                                 #
# --------------------------------------------------------------------------- #

@app.route("/api/summary")
def api_summary():
    g = get_graph()
    return jsonify({
        **g.summary(),
        "neighborhoods": [
            {"id": n.id, "name": n.name, "population": n.population,
             "type": n.node_type, "x": n.x, "y": n.y}
            for n in g.nodes.values() if not n.is_facility
        ],
        "facilities_count": sum(1 for n in g.nodes.values() if n.is_facility),
    })


# --------------------------------------------------------------------------- #
#  /api/graph  — full network for canvas visualisation                         #
# --------------------------------------------------------------------------- #

@app.route("/api/graph")
def api_graph():
    g = get_graph()
    time_period = request.args.get("time", "morning")

    nodes_out = []
    for nid, n in g.nodes.items():
        nodes_out.append({
            "id": nid,
            "name": n.name,
            "population": n.population,
            "type": n.node_type,
            "x": n.x,
            "y": n.y,
            "is_facility": n.is_facility,
            "is_critical": n.is_critical,
        })

    edges_out = []
    for e in g.existing_edges():
        edges_out.append({
            "src": e.src,
            "dst": e.dst,
            "distance": e.distance,
            "capacity": e.capacity,
            "condition": e.condition,
            "flow": e.flow(time_period),
            "congestion_ratio": round(e.congestion_ratio(time_period), 3),
            "travel_time_min": round(e.time_weight(time_period), 2),
        })

    return jsonify({"nodes": nodes_out, "edges": edges_out, "time_period": time_period})


# --------------------------------------------------------------------------- #
#  /api/mst                                                                     #
# --------------------------------------------------------------------------- #

@app.route("/api/mst")
def api_mst():
    g = get_graph()
    algo    = request.args.get("algo", "kruskal")
    include = request.args.get("potential", "false").lower() == "true"

    if algo == "prim":
        start = request.args.get("start", "3")
        result = prim(g, start=start, include_potential=include)
    else:
        result = kruskal(g, include_potential=include)

    analysis = cost_analysis(g, result)
    return jsonify({**result.to_dict(), "cost_analysis": analysis})


# --------------------------------------------------------------------------- #
#  /api/route  (Dijkstra)                                                       #
# --------------------------------------------------------------------------- #

@app.route("/api/route", methods=["POST"])
def api_route():
    g = get_graph()
    body = request.get_json(force=True)
    src  = str(body.get("src", "1"))
    dst  = str(body.get("dst", "3"))
    time = body.get("time", "morning")
    hour = body.get("hour")

    if hour is not None:
        result = time_varying_dijkstra(g, src, dst, int(hour))
    else:
        result = dijkstra(g, src, dst, time_period=time)

    d = result.to_dict()
    d["path_names"] = [g.nodes[n].name for n in result.path if n in g.nodes]
    return jsonify(d)


# --------------------------------------------------------------------------- #
#  /api/astar  (A* emergency routing)                                           #
# --------------------------------------------------------------------------- #

@app.route("/api/astar", methods=["POST"])
def api_astar():
    g = get_graph()
    body = request.get_json(force=True)
    src  = str(body.get("src", "4"))
    dst  = str(body.get("dst", "F9"))
    time = body.get("time", "morning")

    result = astar(g, src, dst, time_period=time)
    d = result.to_dict()
    d["path_names"] = [g.nodes[n].name for n in result.path if n in g.nodes]
    return jsonify(d)


# --------------------------------------------------------------------------- #
#  /api/race  (side-by-side comparison)                                         #
# --------------------------------------------------------------------------- #

@app.route("/api/race", methods=["POST"])
def api_race():
    g = get_graph()
    body = request.get_json(force=True)
    src  = str(body.get("src", "7"))
    dst  = str(body.get("dst", "F9"))
    time = body.get("time", "morning")

    result = race_comparison(g, src, dst, time_period=time)

    # Enrich with path names
    for algo in ("dijkstra", "astar"):
        result[algo]["path_names"] = [
            g.nodes[n].name for n in result[algo]["path"] if n in g.nodes
        ]

    return jsonify(result)


# --------------------------------------------------------------------------- #
#  /api/traffic                                                                 #
# --------------------------------------------------------------------------- #

@app.route("/api/traffic")
def api_traffic():
    g = get_graph()
    time_period = request.args.get("time", "morning")

    roads = []
    for e in g.existing_edges():
        roads.append({
            "road_id": f"{e.src}-{e.dst}",
            "src": e.src,
            "dst": e.dst,
            "src_name": g.nodes.get(e.src, type("N", (), {"name": e.src})()).name,
            "dst_name": g.nodes.get(e.dst, type("N", (), {"name": e.dst})()).name,
            "capacity": e.capacity,
            "morning": e.morning,
            "afternoon": e.afternoon,
            "evening": e.evening,
            "night": e.night,
            "current_flow": e.flow(time_period),
            "congestion_ratio": round(e.congestion_ratio(time_period), 3),
            "condition": e.condition,
        })

    roads.sort(key=lambda r: -r["congestion_ratio"])
    return jsonify({"roads": roads, "time_period": time_period})


# --------------------------------------------------------------------------- #
#  /api/signals  (greedy)                                                       #
# --------------------------------------------------------------------------- #

@app.route("/api/signals", methods=["POST"])
def api_signals():
    g = get_graph()
    body = request.get_json(force=True)
    time       = body.get("time", "morning")
    emergency  = body.get("emergency_node")

    intersections = build_intersections(g, time_period=time)
    plans = greedy_signal_optimise(intersections, emergency_vehicle=emergency)
    result = plans_to_dict(plans, intersections)
    result["optimality_analysis"] = OPTIMALITY_ANALYSIS
    return jsonify(result)


# --------------------------------------------------------------------------- #
#  /api/schedule  (DP scheduling)                                               #
# --------------------------------------------------------------------------- #

@app.route("/api/schedule", methods=["POST"])
def api_schedule():
    body = request.get_json(force=True)
    buses = int(body.get("buses", 200))
    buses = max(50, min(400, buses))

    routes = load_routes()
    result = schedule_dp(buses, routes)
    return jsonify(scheduling_result_to_dict(result))


# --------------------------------------------------------------------------- #
#  /api/maintenance  (DP knapsack)                                              #
# --------------------------------------------------------------------------- #

@app.route("/api/maintenance", methods=["POST"])
def api_maintenance():
    body = request.get_json(force=True)
    budget = int(body.get("budget_mEGP", 200))
    budget = max(10, min(1000, budget))

    segments = load_road_segments()
    result = maintenance_dp(budget, segments)
    return jsonify(maintenance_result_to_dict(result))


# --------------------------------------------------------------------------- #
#  /api/train  (ML training)                                                    #
# --------------------------------------------------------------------------- #

@app.route("/api/train")
def api_train():
    force = request.args.get("force", "false").lower() == "true"
    result = train_models(force=force)
    return jsonify(result)


# --------------------------------------------------------------------------- #
#  /api/predict  (ML inference)                                                 #
# --------------------------------------------------------------------------- #

@app.route("/api/predict", methods=["POST"])
def api_predict():
    body = request.get_json(force=True)
    road_id  = body.get("road_id", "1-3")
    capacity = int(body.get("capacity", 3000))
    condition = int(body.get("condition", 7))
    hour     = int(body.get("hour", 8))
    day_type = int(body.get("day_type", 0))
    model    = body.get("model", "rf")

    result = predict_congestion(road_id, capacity, condition, hour, day_type, model=model)
    return jsonify(result)


# --------------------------------------------------------------------------- #
#  /api/forecast/<road_id>  (24h ML forecast)                                  #
# --------------------------------------------------------------------------- #

@app.route("/api/forecast/<road_id>")
def api_forecast(road_id):
    g = get_graph()
    day_type = int(request.args.get("day_type", 0))

    # Look up road metadata
    edge = None
    for e in g.existing_edges():
        if f"{e.src}-{e.dst}" == road_id or f"{e.dst}-{e.src}" == road_id:
            edge = e
            break

    capacity  = edge.capacity  if edge else 2500
    condition = edge.condition if edge else 7

    result = forecast_24h(road_id, capacity, condition, day_type)
    return jsonify(result)


# --------------------------------------------------------------------------- #
#  Entry point                                                                  #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print(f"Cairo Transport API starting on http://0.0.0.0:{port}")
    print(f"    Graph nodes: {get_graph().summary()}")
    app.run(host="0.0.0.0", port=port, debug=debug)
