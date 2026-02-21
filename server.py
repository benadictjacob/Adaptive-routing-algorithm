"""
REST API for the Adaptive Vector Routing System — Cross-Architecture Analysis Simulator.

Implements all 15 sections of the Master Specification, including architecture-specific 
models, traditional algorithm comparison, and performance metrics.
"""

import sys
import os
import time
import random
import math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from avrs.network import Network
from avrs.node import Node
from avrs.routing import RoutingEngine
from avrs.simulation import Simulation, Request
from avrs.math_utils import euclidean_distance

app = Flask(__name__, static_folder="dashboard", static_url_path="")
CORS(app)

# ── Architecture Models (Section 1) ────────────────────────────────

# ── Architecture Models with Semantic Roles ──────────────────────────
# Each role has a CENTER in 4D vector space.  Nodes of the same role
# get vectors tightly clustered around that center (spread ±0.08).
# Different roles are widely separated (centers ≥0.5 apart).

ARCHITECTURES = {
    "microservice": {
        "label": "Microservice Architecture",
        "seed": 42, "dim": 4, "latency": "low", "fail_prob": 0.02,
        "roles": {
            "api_gateway":  {"center": [0.8, 0.8, 0.2, 0.2], "count": 3,  "color": "cyan"},
            "auth_service": {"center": [0.2, 0.8, 0.8, 0.2], "count": 3,  "color": "purple"},
            "compute":      {"center": [0.2, 0.2, 0.2, 0.8], "count": 5,  "color": "orange"},
            "database":     {"center": [0.8, 0.2, 0.8, 0.8], "count": 4,  "color": "emerald"},
            "cache_proxy":  {"center": [0.5, 0.5, 0.2, 0.2], "count": 5,  "color": "pink"},
        }
    },
    "edge": {
        "label": "Edge Computing Network",
        "seed": 77, "dim": 4, "latency": "variable", "fail_prob": 0.08,
        "roles": {
            "edge_proxy":   {"center": [0.9, 0.1, 0.1, 0.5], "count": 8, "color": "cyan"},
            "fog_compute":  {"center": [0.1, 0.9, 0.5, 0.1], "count": 7, "color": "purple"},
            "cdn_cache":    {"center": [0.5, 0.5, 0.9, 0.1], "count": 6, "color": "orange"},
            "sensor_hub":   {"center": [0.1, 0.1, 0.1, 0.9], "count": 5, "color": "emerald"},
            "cloud_bridge": {"center": [0.9, 0.9, 0.5, 0.5], "count": 4, "color": "pink"},
        }
    },
    "cloud": {
        "label": "Cloud Cluster Infrastructure",
        "seed": 99, "dim": 4, "latency": "ultra-low", "fail_prob": 0.01,
        "roles": {
            "load_balancer":{"center": [0.9, 0.5, 0.1, 0.5], "count": 5,  "color": "cyan"},
            "app_server":   {"center": [0.5, 0.9, 0.5, 0.1], "count": 10, "color": "purple"},
            "db_replica":   {"center": [0.1, 0.1, 0.9, 0.5], "count": 8,  "color": "orange"},
            "object_store": {"center": [0.5, 0.1, 0.5, 0.9], "count": 7,  "color": "emerald"},
            "queue_worker": {"center": [0.1, 0.5, 0.1, 0.1], "count": 10, "color": "pink"},
        }
    },
    "iot": {
        "label": "IoT Distributed Mesh",
        "seed": 55, "dim": 4, "latency": "high", "fail_prob": 0.15,
        "roles": {
            "sensor":       {"center": [0.1, 0.1, 0.1, 0.1], "count": 15, "color": "cyan"},
            "actuator":     {"center": [0.9, 0.1, 0.9, 0.1], "count": 10, "color": "purple"},
            "gateway":      {"center": [0.5, 0.9, 0.5, 0.9], "count": 5,  "color": "orange"},
            "edge_proc":    {"center": [0.1, 0.5, 0.9, 0.5], "count": 10, "color": "emerald"},
            "aggregator":   {"center": [0.9, 0.9, 0.1, 0.5], "count": 10, "color": "pink"},
        }
    },
    "hpc": {
        "label": "HPC Distributed Cluster",
        "seed": 33, "dim": 4, "latency": "near-zero", "fail_prob": 0.001,
        "roles": {
            "scheduler":    {"center": [0.9, 0.9, 0.5, 0.5], "count": 3,  "color": "cyan"},
            "compute_node": {"center": [0.2, 0.2, 0.5, 0.5], "count": 10, "color": "purple"},
            "storage_node": {"center": [0.5, 0.5, 0.9, 0.1], "count": 5,  "color": "orange"},
            "interconnect": {"center": [0.5, 0.5, 0.1, 0.9], "count": 4,  "color": "emerald"},
            "monitor":      {"center": [0.8, 0.2, 0.2, 0.8], "count": 3,  "color": "pink"},
        }
    }
}

# Role color name → index mapping (matches CLUSTER_COLORS in app.js)
ROLE_COLOR_INDEX = {"cyan": 0, "purple": 1, "orange": 2, "emerald": 3, "pink": 4, "yellow": 5}

# ── Traditional Algorithm (Section 10) ──────────────────────────────

def run_traditional_route(network, start_id, target_vector, max_hops=50):
    """Run simple distance-only greedy routing (no load/trust awareness)."""
    start = network.get_node(start_id)
    if not start:
        return {"success": False, "path": [], "total_hops": 0}

    current = start
    path = [current.id]
    visited = {current.id}

    for step in range(max_hops):
        current_dist = euclidean_distance(list(current.vector), target_vector)

        # Check termination: local minimum
        best_nb = None
        best_dist = current_dist
        for nb in current.neighbors:
            if not nb.alive or nb.id in visited:
                continue
            d = euclidean_distance(list(nb.vector), target_vector)
            if d < best_dist:
                best_dist = d
                best_nb = nb

        if best_nb is None:
            # Reached local minimum or no unvisited closer neighbor
            return {"success": True, "path": path, "total_hops": len(path)}

        visited.add(best_nb.id)
        path.append(best_nb.id)
        current = best_nb

    return {"success": False, "path": path, "total_hops": max_hops}

# ── Global State ──────────────────────────────────────────────────

current_arch = "microservice"
network = None
engine_adaptive = RoutingEngine()
sim_adaptive = None

node_positions = {} # id -> {x, y} for layouts
node_clusters = {}  # id -> cluster index
node_roles = {}     # id -> role name

def init_system(mode="microservice"):
    """
    Build a semantically-clustered network for the given architecture.

    Nodes of the same role get vectors VERY CLOSE together (spread ±0.08),
    so proxy servers cluster, compute nodes cluster, etc.  Different roles
    are separated by ≥0.5 in vector space.  Layout is a 2D projection of
    the actual 4D vectors, so the visual display matches the vector-space reality.
    """
    global network, sim_adaptive, current_arch, node_positions, node_clusters, node_roles
    current_arch = mode
    arch = ARCHITECTURES[mode]
    rng = random.Random(arch["seed"])
    dim = arch["dim"]
    roles = arch["roles"]

    # --- Step 1: Generate nodes with role-based clustered vectors ---
    network = Network()
    node_positions = {}
    node_clusters = {}
    node_roles = {}

    node_idx = 0
    role_idx = 0
    for role_name, role_cfg in roles.items():
        center = role_cfg["center"]
        count = role_cfg["count"]
        color_idx = ROLE_COLOR_INDEX.get(role_cfg["color"], role_idx)
        spread = 0.08  # tight clustering: nodes within ±0.08 of center

        for j in range(count):
            # Vector: center + small random perturbation
            vec = [center[d_] + rng.uniform(-spread, spread) for d_ in range(dim)]
            # Clamp to [0, 1]
            vec = [max(0.0, min(1.0, v)) for v in vec]

            node_id = f"N{node_idx:03d}"
            node = Node(node_id=node_id, vector=vec)
            network.nodes.append(node)
            network._node_map[node_id] = node

            # 2D position = projection of 4D vector (scaled for canvas)
            node_positions[node_id] = {
                "x": (vec[0] - 0.5) * 800 + rng.uniform(-15, 15),
                "y": (vec[1] - 0.5) * 600 + rng.uniform(-15, 15),
            }
            node_clusters[node_id] = color_idx
            node_roles[node_id] = role_name
            node_idx += 1

        role_idx += 1

    # --- Step 2: Connect via Delaunay triangulation for routing guarantee ---
    vectors = [list(n.vector) for n in network.nodes]
    network._connect_delaunay(vectors)

    # --- Step 3: Set up the simulation engine ---
    sim_adaptive = Simulation(network, engine_adaptive)


init_system("microservice")

metrics = {
    "adaptive": {"total": 0, "success": 0, "hops": 0, "decision_time": 0},
    "trad": {"total": 0, "success": 0, "hops": 0, "decision_time": 0},
    "routes": []
}

# ── API Endpoints ─────────────────────────────────────────────────

@app.route("/")
def serve_dashboard():
    return send_from_directory("dashboard", "index.html")

@app.route("/api/network")
def get_network():
    nodes = []
    for n in network.nodes:
        pos = node_positions.get(n.id, {"x": 0, "y": 0})
        nodes.append({
            "id": n.id,
            "vector": [round(v, 3) for v in n.vector],
            "load": n.load,
            "trust": round(n.trust, 2),
            "alive": n.alive,
            "x": pos["x"],
            "y": pos["y"],
            "cluster": node_clusters.get(n.id, 0),
            "role": node_roles.get(n.id, "unknown"),
            "neighbors": [nb.id for nb in n.neighbors]
        })
    
    edges = []
    seen = set()
    for n in network.nodes:
        for nb in n.neighbors:
            pair = tuple(sorted([n.id, nb.id]))
            if pair not in seen:
                seen.add(pair)
                edges.append({"source": n.id, "target": nb.id})
    
    # Build roles summary for legend
    arch = ARCHITECTURES[current_arch]
    roles_summary = []
    for rname, rcfg in arch["roles"].items():
        roles_summary.append({
            "name": rname,
            "color_idx": ROLE_COLOR_INDEX.get(rcfg["color"], 0),
            "count": rcfg["count"],
            "center": rcfg["center"]
        })
                
    return jsonify({
        "architecture": current_arch,
        "label": arch["label"],
        "latency": arch["latency"],
        "fail_prob": arch["fail_prob"],
        "roles": roles_summary,
        "nodes": nodes,
        "edges": edges
    })

@app.route("/api/route", methods=["POST"])
def run_comparison_route():
    """Run both Adaptive and Traditional algorithms for comparison.
    
    SECTION-BOUNDARY RULE:
    If every node in the target section is dead, routing MUST NOT cross
    into another section.  Instead, it returns failure and routes back
    to the source node.
    """
    data = request.json
    start_id = data.get("start", "N000")
    target = data.get("target", [0.5, 0.5, 0.5, 0.5])
    
    start_node = network.get_node(start_id)
    if not start_node:
        return jsonify({"error": "Start node not found"}), 404
    
    # --- Identify the target section (closest role center) ---
    arch = ARCHITECTURES[current_arch]
    target_role = None
    best_role_dist = float("inf")
    for rname, rcfg in arch["roles"].items():
        d = euclidean_distance(target, rcfg["center"])
        if d < best_role_dist:
            best_role_dist = d
            target_role = rname
    
    # --- Check if any alive node exists in that section ---
    section_nodes = [n for n in network.nodes if node_roles.get(n.id) == target_role]
    alive_in_section = [n for n in section_nodes if n.alive]
    section_all_dead = len(alive_in_section) == 0
    
    if section_all_dead:
        # ALL nodes in target section are dead → route back to source
        return jsonify({
            "section_failure": True,
            "target_role": target_role,
            "message": f"All {len(section_nodes)} nodes in '{target_role}' section are dead. Route returns to source.",
            "adaptive": {
                "success": False,
                "path": [start_id, start_id],  # round-trip back to source
                "total_hops": 0,
                "decision_time": 0,
                "hops": [],
                "section_failed": True
            },
            "trad": {
                "success": False,
                "path": [start_id],
                "total_hops": 0,
                "decision_time": 0,
                "section_failed": True
            }
        })
        
    req = Request(target_vector=target)
    
    # Time Adaptive
    t0 = time.perf_counter()
    res_adaptive = sim_adaptive.route_request(start_node, req)
    t1 = time.perf_counter()
    
    # Time Traditional (standalone function, doesn't need Simulation)
    t2 = time.perf_counter()
    res_trad = run_traditional_route(network, start_id, target)
    t3 = time.perf_counter()
    
    # --- Section-boundary validation ---
    # If adaptive route ended at a node OUTSIDE the target section,
    # that means it crossed a boundary → treat as section failure
    adaptive_path = res_adaptive.path
    if adaptive_path:
        final_node_id = adaptive_path[-1]
        final_role = node_roles.get(final_node_id, "")
        if final_role != target_role:
            # Crossed section boundary → route back to source
            adaptive_path = adaptive_path + list(reversed(adaptive_path[:-1]))
            res_adaptive.success = False
    
    trad_path = res_trad["path"]
    if trad_path:
        final_trad = trad_path[-1]
        if node_roles.get(final_trad, "") != target_role:
            trad_path = trad_path + list(reversed(trad_path[:-1]))
            res_trad["success"] = False
    
    # Update metrics
    metrics["adaptive"]["total"] += 1
    if res_adaptive.success:
        metrics["adaptive"]["success"] += 1
        metrics["adaptive"]["hops"] += res_adaptive.total_hops
        metrics["adaptive"]["decision_time"] += (t1 - t0)
        
    metrics["trad"]["total"] += 1
    if res_trad["success"]:
        metrics["trad"]["success"] += 1
        metrics["trad"]["hops"] += res_trad["total_hops"]
        metrics["trad"]["decision_time"] += (t3 - t2)

    # Build adaptive hops detail
    adaptive_hops = []
    for h in res_adaptive.hops:
        hop_data = {
            "node_id": h.node_id,
            "distance": h.distance_to_target,
            "chosen_next": h.chosen_next,
            "is_terminal": h.is_terminal,
            "scores": h.scores
        }
        adaptive_hops.append(hop_data)

    return jsonify({
        "target_role": target_role,
        "section_failure": False,
        "adaptive": {
            "success": res_adaptive.success,
            "path": adaptive_path,
            "total_hops": res_adaptive.total_hops,
            "decision_time": (t1 - t0) * 1000,
            "hops": adaptive_hops
        },
        "trad": {
            "success": res_trad["success"],
            "path": trad_path,
            "total_hops": res_trad["total_hops"],
            "decision_time": (t3 - t2) * 1000
        }
    })

@app.route("/api/node/<id>/toggle", methods=["POST"])
def toggle_node(id):
    node = network.get_node(id)
    if not node: return jsonify({"error": "Not found"}), 404
    if node.alive: node.fail()
    else: node.recover()
    return jsonify({"id": id, "alive": node.alive})

@app.route("/api/node/<id>/trust", methods=["POST"])
def set_trust(id):
    node = network.get_node(id)
    if not node: return jsonify({"error": "Not found"}), 404
    data = request.json
    node.trust = max(0, min(1, float(data.get("trust", 1))))
    return jsonify({"id": id, "trust": node.trust})

@app.route("/api/simulate/failure", methods=["POST"])
def simulate_failure():
    """Simulate complex failure patterns (Section 6 & 12)."""
    data = request.json
    fail_type = data.get("type", "node") # node, cluster, partition
    
    rng = random.Random()
    affected = []
    
    if fail_type == "node":
        target = rng.choice(network.nodes)
        target.fail()
        affected.append(target.id)
    elif fail_type == "cluster":
        # Fail 20% of nodes in a geographic proximity
        center = rng.choice(network.nodes)
        dists = []
        for n in network.nodes:
            d = euclidean_distance(list(center.vector), list(n.vector))
            dists.append((d, n))
        dists.sort(key=lambda x: x[0])
        for _, n in dists[:int(len(network.nodes)*0.25)]:
            n.fail()
            affected.append(n.id)
    elif fail_type == "partition":
        # Fail nodes with high degree to split the graph
        # For simplicity, we fail nodes in the 'middle' of the generated layout
        mid_x = sum(node_positions[n.id]["x"] for n in network.nodes) / len(network.nodes)
        for n in network.nodes:
            if abs(node_positions[n.id]["x"] - mid_x) < 50:
                n.fail()
                affected.append(n.id)
                
    return jsonify({"status": "failure_simulated", "type": fail_type, "affected": affected})

@app.route("/api/architecture", methods=["POST"])
def switch_arch():
    data = request.json
    mode = data.get("mode", "microservice")
    if mode not in ARCHITECTURES:
        return jsonify({"error": "Invalid mode"}), 400
    init_system(mode)
    return jsonify({"status": "switched", "mode": mode})

@app.route("/api/reset", methods=["POST"])
def reset():
    init_system(current_arch)
    return jsonify({"status": "reset"})

@app.route("/api/metrics")
def get_metrics():
    def calc(m):
        return {
            "success_rate": round(m["success"] / m["total"] * 100, 1) if m["total"] > 0 else 0,
            "avg_hops": round(m["hops"] / m["success"], 2) if m["success"] > 0 else 0,
            "avg_time": round(m["decision_time"] / m["total"] * 1000, 3) if m["total"] > 0 else 0
        }
    
    return jsonify({
        "adaptive": calc(metrics["adaptive"]),
        "trad": calc(metrics["trad"]),
        "alive_nodes": sum(1 for n in network.nodes if n.alive),
        "total_nodes": len(network.nodes)
    })

if __name__ == "__main__":
    app.run(debug=True, port=5000)
