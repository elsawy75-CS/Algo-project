# 🗺️ Cairo Smart Transportation Network Optimization System

> **CSE112 — Data Structures & Algorithms Project**  
> A full-stack transportation management system for Greater Cairo implementing graph algorithms, dynamic programming, greedy strategies, and ML-based traffic prediction.

---

## 📋 Table of Contents
- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Docker Deployment](#-docker-deployment)
- [Deploy to the Web](#-deploy-to-the-web)
- [API Reference](#-api-reference)
- [Algorithm Details](#-algorithm-details)
- [ML Prediction](#-ml-prediction)
- [Testing](#-testing)
- [Project Structure](#-project-structure)

---

## ✨ Features

| Module | Algorithm | Complexity |
|--------|-----------|------------|
| Road Network Design | Kruskal's MST + Prim's MST | O(E log E) |
| Route Planning | Dijkstra's Algorithm (time-varying) | O((V+E) log V) |
| Emergency Routing | A* Search (haversine heuristic) | O(E log V) |
| Algorithm Race | Dijkstra vs A* animated comparison | — |
| Transit Scheduling | Dynamic Programming (knapsack variant) | O(R·B²) |
| Road Maintenance | 0/1 Knapsack DP | O(N·B) |
| Traffic Signals | Greedy signal optimiser | O(I log I) |
| Emergency Preemption | Priority queue (min-heap) | O(log I) |
| Traffic Prediction | RandomForest + GradientBoosting | O(N·trees·depth) |
| 24h Forecast | ML inference pipeline | O(trees·depth) |

---

## 🏗 Architecture

```
cairo_transport/
├── src/
│   ├── app.py               ← Flask REST API (all endpoints)
│   ├── graph.py             ← Weighted graph, data loaders, BPR weights
│   ├── mst.py               ← Kruskal + Prim + Union-Find + cost analysis
│   ├── shortest_path.py     ← Dijkstra, A*, time-varying, race comparison
│   ├── dynamic_programming.py ← Schedule DP, maintenance knapsack, memoisation
│   ├── greedy.py            ← Signal optimiser, emergency preemptor, analysis
│   └── ml_prediction.py     ← Feature engineering, RF/GB training, 24h forecast
├── data/                    ← CSV datasets (neighborhoods, roads, traffic…)
├── templates/index.html     ← Single-page frontend
├── static/
│   ├── css/style.css        ← Dark-theme responsive UI
│   └── js/
│       ├── network.js       ← Canvas graph renderer + race animator
│       └── main.js          ← All tab logic, chart.js dashboards
├── models/                  ← Persisted scikit-learn models (.pkl)
├── tests/test_algorithms.py ← 40+ pytest unit tests
├── Dockerfile               ← Multi-stage Docker build
├── docker-compose.yml       ← One-command deployment
└── requirements.txt
```

---

## 🚀 Quick Start

### Option A — Run locally

```bash
# 1. Clone / unzip the project
cd cairo_transport

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
cd src
python app.py
# → http://localhost:5000
```

### Option B — With virtual environment (recommended)

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd src && python app.py
```

---

## 🐳 Docker Deployment

### Build & run

```bash
# Build image
docker build -t cairo-transport .

# Run container
docker run -p 5000:5000 cairo-transport

# Or with Docker Compose (recommended — mounts model cache)
docker compose up --build
```

The app will be available at **http://localhost:5000**.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | HTTP port |
| `FLASK_DEBUG` | `false` | Enable debug mode |

---

## 🌐 Deploy to the Web

### Vercel (recommended for frontend)
> The backend is Python/Flask — use Render or Railway for full-stack.

### Render (full-stack, free tier)

1. Push the project to GitHub.
2. Go to [render.com](https://render.com) → **New Web Service**.
3. Connect your repo. Set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn --chdir src --bind 0.0.0.0:$PORT app:app`
   - **Root directory:** *(leave blank)*
4. Add environment variable: `PYTHONPATH=src`
5. Click **Deploy** → get a public URL like `https://cairo-transport.onrender.com`.

### GitHub Pages (static frontend only)
If you want to serve only the UI:
1. Change `API` in `static/js/main.js` to your Render URL.
2. Copy `templates/index.html` and `static/` into `docs/`.
3. Enable GitHub Pages from the `docs/` folder.

---

## 📡 API Reference

All endpoints return JSON.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve frontend SPA |
| GET | `/api/summary` | Network stats |
| GET | `/api/graph?time=morning` | Full network data |
| GET | `/api/mst?algo=kruskal&potential=false` | MST result + steps |
| POST | `/api/route` | Dijkstra route `{src, dst, time}` |
| POST | `/api/astar` | A* emergency route `{src, dst, time}` |
| POST | `/api/race` | Side-by-side comparison `{src, dst, time}` |
| GET | `/api/traffic?time=morning` | Traffic data for all roads |
| POST | `/api/signals` | Greedy signal plans `{time, emergency_node?}` |
| POST | `/api/schedule` | DP scheduling `{buses}` |
| POST | `/api/maintenance` | Knapsack DP `{budget_mEGP}` |
| GET | `/api/train?force=false` | Train ML models |
| POST | `/api/predict` | Single prediction `{road_id, capacity, condition, hour}` |
| GET | `/api/forecast/<road_id>?day_type=0` | 24-hour ML forecast |

---

## 📐 Algorithm Details

### 1. Minimum Spanning Tree (Kruskal's + Prim's)
- **Modification:** edges incident to hospitals / government centres have weight × 0.5 → guaranteed early connectivity.
- **Union-Find** with path compression + union-by-rank: O(α(V)) per operation.
- Kruskal sorts edges O(E log E), then processes each O(E·α(V)).

### 2. Dijkstra's (time-varying)
- Edge weight = BPR travel-time function: `t = t₀ × (1 + 0.15 × (v/c)⁴)`
- Switches between four traffic periods (morning / afternoon / evening / night).
- `time_varying_dijkstra()` maps any hour 0–23 to the nearest band.

### 3. A* Emergency Routing
- Heuristic: `h(n) = haversine(n, dst) / free_flow_speed` — admissible & consistent.
- Emergency bonus: congestion weight capped at 1.2 × free-flow (signal preemption).

### 4. Dynamic Programming (Scheduling)
- State: `dp[i][j]` = max passengers using `j` buses across first `i` routes.
- Transition: try all valid bus counts for route `i`.
- Memoisation: `MemoCache` wraps any path function with LRU eviction.

### 5. Road Maintenance Knapsack
- Standard 0/1 knapsack: `dp[i][b]` = max condition gain using budget `b` for first `i` segments.
- Cost = `distance × (10 − condition) × 2` (million EGP estimate).

### 6. Greedy Signal Optimiser
- Sorts intersections by `flow / capacity` descending.
- Green time = `max(30, min(90, ratio × 120 / (approaches/2)))` seconds.
- **Optimal** for isolated intersections; **suboptimal** for interconnected Cairo grid (documented).

---

## 🤖 ML Prediction

### Training data
- 4 traffic bands × 28 road segments × 56 synthetic days = ~158,000 samples.
- Features: `hour, day_type, capacity, condition, is_arterial, sin(hour), cos(hour), flow`.
- Circular encoding of hour (sin/cos) prevents discontinuity at midnight.

### Models
| Model | MAE (congestion ratio) | R² |
|-------|----------------------|-----|
| RandomForestRegressor (100 trees, depth 8) | ~0.04 | ~0.91 |
| GradientBoostingRegressor (150 trees, lr=0.08) | ~0.05 | ~0.89 |

### Endpoints
- `GET /api/train` — trains both models, saves to `models/*.pkl`.
- `GET /api/forecast/1-3` — returns 24 hourly congestion predictions.

---

## 🧪 Testing

```bash
# Install test dependency
pip install pytest

# Run all tests (40+)
pytest tests/ -v

# Run with coverage
pip install pytest-cov
pytest tests/ -v --cov=src --cov-report=term-missing
```

Test categories:
- `TestGraphLoading` — data integrity checks
- `TestUnionFind` — path compression, cycle detection
- `TestKruskal / TestPrim` — MST correctness, no-cycle guarantee
- `TestDijkstra / TestAStar` — path finding, travel time ordering
- `TestRace` — comparison metrics
- `TestScheduleDP / TestMaintenanceDP` — DP correctness, budget constraints
- `TestMemoCache` — cache hit/miss rates
- `TestGreedy / TestEmergencyPreemptor` — signal timing, priority ordering
- `TestEdgeWeights` — BPR function validation

---

## 📁 Project Structure

```
cairo_transport/
├── data/
│   ├── neighborhoods.csv          (15 neighborhoods)
│   ├── facilities.csv             (10 facilities)
│   ├── existing_roads.csv         (28 roads with condition/capacity)
│   ├── potential_roads.csv        (15 proposed new roads)
│   ├── traffic_flow.csv           (4-band temporal traffic)
│   ├── metro_lines.csv            (3 metro lines)
│   ├── bus_routes.csv             (10 bus routes)
│   └── public_transport_demand.csv
├── src/
│   ├── app.py
│   ├── graph.py
│   ├── mst.py
│   ├── shortest_path.py
│   ├── dynamic_programming.py
│   ├── greedy.py
│   └── ml_prediction.py
├── static/css/style.css
├── static/js/{network,main}.js
├── templates/index.html
├── tests/test_algorithms.py
├── models/                        (auto-created after training)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 👥 Authors

CSE112 — Spring 2026  
Greater Cairo Metropolitan Transportation Optimization Project

---

## 📄 License

MIT — free to use for academic purposes.
