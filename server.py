"""
═══════════════════════════════════════════════════════════════════════
  KUBERNETES SELF-HEALING DISASTER-RECOVERY PLATFORM
  Central REST API Server (Section 12, 13)
═══════════════════════════════════════════════════════════════════════

Ties together all layers:
  • Cluster Model        → controller/cluster.py
  • Failure Detection    → controller/failure_detector.py
  • Health Monitoring    → monitor/health_checker.py
  • Automated Recovery   → recovery/recovery_engine.py
  • Proxy / Rerouting    → proxy/proxy_server.py
  • State Snapshots      → state_store/snapshot_engine.py
  • Disaster Restoration → recovery/disaster_restore.py

Dashboard served from /dashboard (built separately).
Real-time events via SSE at /api/events/stream.
"""

import sys
import os
import json
import time
import random
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

from controller.cluster import (
    Cluster, KubeNode, Pod, Deployment, Service,
    NodeStatus, PodStatus, ServiceType,
)
from controller.failure_detector import FailureDetector
from monitor.health_checker import HealthChecker
from recovery.recovery_engine import RecoveryEngine
from proxy.proxy_server import ProxyServer, ProxyRequest
from state_store.snapshot_engine import SnapshotEngine
from recovery.disaster_restore import DisasterRestore


app = Flask(__name__, static_folder="dashboard", static_url_path="")
CORS(app)

# ═══════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════

cluster: Cluster = None
failure_detector: FailureDetector = None
health_checker: HealthChecker = None
recovery_engine: RecoveryEngine = None
proxy_server: ProxyServer = None
snapshot_engine: SnapshotEngine = None
disaster_restore: DisasterRestore = None

# SSE event queue for real-time dashboard updates
sse_events = []
sse_lock = threading.Lock()


def push_sse_event(event_type: str, data: dict):
    """Push an event to the SSE stream for the dashboard."""
    with sse_lock:
        sse_events.append({
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        })
        # Keep last 200 events
        if len(sse_events) > 200:
            del sse_events[:100]


# ═══════════════════════════════════════════════════════════════════
#  SYSTEM INITIALIZATION
# ═══════════════════════════════════════════════════════════════════

def init_system(config_path: str = None):
    """Initialize the entire DR platform from a config file."""
    global cluster, failure_detector, health_checker, recovery_engine
    global proxy_server, snapshot_engine, disaster_restore

    # Load config
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(__file__), "config", "default_cluster.json"
        )
    with open(config_path) as f:
        config = json.load(f)

    # ── Step 1: Create cluster ───────────────────────────────────
    cluster = Cluster(name=config.get("cluster_name", "k8s-cluster"))
    push_sse_event("system", {"message": "Initializing cluster..."})

    # ── Step 2: Create nodes ─────────────────────────────────────
    for node_cfg in config.get("nodes", []):
        node = KubeNode(
            name=node_cfg["name"],
            cpu_cores=node_cfg.get("cpu_cores", 4),
            memory_gb=node_cfg.get("memory_gb", 8.0),
            max_pods=node_cfg.get("max_pods", 30),
        )
        cluster.add_node(node)

    # ── Step 3: Create deployments and schedule pods ─────────────
    for dep_cfg in config.get("deployments", []):
        dep = Deployment(
            name=dep_cfg["name"],
            image=dep_cfg.get("image", "app:latest"),
            replicas=dep_cfg.get("replicas", 3),
            labels=dep_cfg.get("labels", {}),
        )
        cluster.create_deployment(dep)

    # ── Step 4: Create services ──────────────────────────────────
    for svc_cfg in config.get("services", []):
        svc_type = ServiceType.CLUSTER_IP
        if svc_cfg.get("type") == "LoadBalancer":
            svc_type = ServiceType.LOAD_BALANCER
        elif svc_cfg.get("type") == "NodePort":
            svc_type = ServiceType.NODE_PORT

        svc = Service(
            name=svc_cfg["name"],
            selector=svc_cfg.get("selector", {}),
            port=svc_cfg.get("port", 80),
            service_type=svc_type,
        )
        cluster.create_service(svc)

    # ── Step 5: Wire up all subsystems ───────────────────────────
    failure_detector = FailureDetector(cluster, check_interval=3.0)
    health_checker = HealthChecker(cluster, interval=2.0)
    recovery_engine = RecoveryEngine(cluster)
    proxy_server = ProxyServer(cluster)
    snapshot_engine = SnapshotEngine(cluster, interval=30.0)
    disaster_restore = DisasterRestore(snapshot_engine)

    # Connect failure detector → recovery engine (auto-heal pipeline)
    def on_failure_detected(event):
        recovery_engine.handle_failure(event)
        push_sse_event("failure", event.to_dict())

    failure_detector.on_failure(on_failure_detected)

    # ── Step 6: Start background threads ─────────────────────────
    health_checker.start()
    failure_detector.start()
    snapshot_engine.start()

    # Take initial snapshot
    snapshot_engine.take_snapshot()

    push_sse_event("system", {
        "message": f"Cluster '{cluster.name}' initialized: "
                   f"{len(cluster.nodes)} nodes, {len(cluster.deployments)} deployments, "
                   f"{len(cluster.services)} services, {len(cluster.all_pods())} pods"
    })

    print(f"\n{'='*60}")
    print(f"  KUBERNETES DR PLATFORM — {cluster.name}")
    print(f"  Nodes: {len(cluster.nodes)}  |  Deployments: {len(cluster.deployments)}")
    print(f"  Services: {len(cluster.services)}  |  Pods: {len(cluster.all_pods())}")
    print(f"{'='*60}\n")


# Initialize on module load
init_system()


# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@app.route("/")
def serve_dashboard():
    return send_from_directory("dashboard", "index.html")


# ═══════════════════════════════════════════════════════════════════
#  SSE — Real-time event stream
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/events/stream")
def event_stream():
    """Server-Sent Events stream for real-time dashboard updates."""
    def generate():
        last_idx = len(sse_events)
        while True:
            with sse_lock:
                new_events = sse_events[last_idx:]
                last_idx = len(sse_events)
            for ev in new_events:
                yield f"data: {json.dumps(ev)}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# ═══════════════════════════════════════════════════════════════════
#  CLUSTER STATE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/cluster")
def get_cluster():
    """Get full cluster state."""
    return jsonify(cluster.to_dict())


@app.route("/api/nodes")
def get_nodes():
    """Get all node details."""
    return jsonify({"nodes": [n.to_dict() for n in cluster.nodes]})


@app.route("/api/pods")
def get_pods():
    """Get all pod details."""
    return jsonify({"pods": [p.to_dict() for p in cluster.all_pods()]})


@app.route("/api/deployments")
def get_deployments():
    return jsonify({"deployments": [d.to_dict() for d in cluster.deployments]})


@app.route("/api/services")
def get_services():
    all_p = cluster.all_pods()
    return jsonify({"services": [s.to_dict(all_p) for s in cluster.services]})


@app.route("/api/events")
def get_events():
    count = request.args.get("count", 50, type=int)
    return jsonify({"events": cluster.get_recent_events(count)})


# ═══════════════════════════════════════════════════════════════════
#  DISASTER SIMULATION ENDPOINTS (Section 11)
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/simulate/kill-pod", methods=["POST"])
def kill_pod():
    """Kill a specific pod or a random one."""
    data = request.json or {}
    pod_name = data.get("pod")

    if pod_name:
        target = None
        for p in cluster.all_pods():
            if p.name == pod_name:
                target = p
                break
        if not target:
            return jsonify({"error": f"Pod '{pod_name}' not found"}), 404
    else:
        running_pods = [p for p in cluster.all_pods() if p.status == PodStatus.RUNNING]
        if not running_pods:
            return jsonify({"error": "No running pods to kill"}), 400
        target = random.choice(running_pods)

    target.crash()
    push_sse_event("simulation", {"action": "kill-pod", "pod": target.name, "node": target.node_name})
    cluster._log_event("Simulation", f"Pod '{target.name}' killed (simulated crash)", "Warning")

    return jsonify({
        "action": "kill-pod",
        "pod": target.name,
        "node": target.node_name,
        "status": target.status.value,
    })


@app.route("/api/simulate/kill-node", methods=["POST"])
def kill_node():
    """Kill a specific node or a random one."""
    data = request.json or {}
    node_name = data.get("node")

    if node_name:
        target = cluster.get_node(node_name)
        if not target:
            return jsonify({"error": f"Node '{node_name}' not found"}), 404
    else:
        ready = cluster.get_ready_nodes()
        if not ready:
            return jsonify({"error": "No ready nodes to kill"}), 400
        target = random.choice(ready)

    affected_pods = [p.name for p in target.pods]
    target.mark_not_ready()
    push_sse_event("simulation", {
        "action": "kill-node", "node": target.name,
        "affected_pods": affected_pods,
    })
    cluster._log_event("Simulation", f"Node '{target.name}' killed — {len(affected_pods)} pods affected", "Critical")

    return jsonify({
        "action": "kill-node",
        "node": target.name,
        "affected_pods": affected_pods,
        "status": target.status.value,
    })


@app.route("/api/simulate/network-delay", methods=["POST"])
def network_delay():
    """Inject network latency into random pods."""
    data = request.json or {}
    delay_ms = data.get("delay_ms", 500.0)
    count = data.get("count", 5)

    running = [p for p in cluster.all_pods() if p.status == PodStatus.RUNNING]
    targets = random.sample(running, min(count, len(running)))

    affected = []
    for pod in targets:
        pod.latency_ms = delay_ms + random.uniform(0, 100)
        affected.append({"pod": pod.name, "latency_ms": round(pod.latency_ms, 1)})

    push_sse_event("simulation", {"action": "network-delay", "affected": affected})
    cluster._log_event("Simulation", f"Network delay injected into {len(affected)} pods", "Warning")

    return jsonify({"action": "network-delay", "affected": affected})


@app.route("/api/simulate/cluster-crash", methods=["POST"])
def cluster_crash():
    """Simulate a full cluster crash — all nodes go NotReady."""
    affected = []
    for node in cluster.nodes:
        node.mark_not_ready()
        affected.append(node.name)

    push_sse_event("simulation", {"action": "cluster-crash", "nodes_affected": affected})
    cluster._log_event("Simulation", "FULL CLUSTER CRASH — all nodes down", "Critical")

    return jsonify({
        "action": "cluster-crash",
        "nodes_affected": affected,
        "message": "All nodes marked NotReady. Use /api/restore to rebuild.",
    })


@app.route("/api/simulate/recover-node", methods=["POST"])
def recover_node():
    """Manually recover a specific node."""
    data = request.json or {}
    node_name = data.get("node")

    if not node_name:
        return jsonify({"error": "Provide 'node' name"}), 400

    node = cluster.get_node(node_name)
    if not node:
        return jsonify({"error": f"Node '{node_name}' not found"}), 404

    node.mark_ready()
    # Restart pods on the recovered node
    for pod in node.pods:
        pod.start()

    push_sse_event("recovery", {"action": "node-recovered", "node": node_name})
    cluster._log_event("Recovery", f"Node '{node_name}' manually recovered")

    return jsonify({"action": "recover-node", "node": node_name, "status": node.status.value})


# ═══════════════════════════════════════════════════════════════════
#  PROXY / TRAFFIC ROUTING
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/route", methods=["POST"])
def route_traffic():
    """Route traffic through the proxy to a service."""
    data = request.json or {}
    service_name = data.get("service", "api-gateway-svc")
    count = data.get("count", 1)

    if count == 1:
        req = ProxyRequest(service_name)
        resp = proxy_server.route_request(req)
        push_sse_event("traffic", resp.to_dict())
        return jsonify(resp.to_dict())
    else:
        results = proxy_server.route_batch(service_name, count)
        summary = {
            "service": service_name,
            "total": len(results),
            "success": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "responses": [r.to_dict() for r in results[:10]],  # first 10 only
        }
        return jsonify(summary)


@app.route("/api/proxy/stats")
def proxy_stats():
    return jsonify(proxy_server.get_all_stats())


# ═══════════════════════════════════════════════════════════════════
#  SNAPSHOT / RESTORE
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/snapshot", methods=["POST"])
def take_snapshot():
    """Manually trigger a snapshot."""
    filename = snapshot_engine.take_snapshot()
    push_sse_event("snapshot", {"action": "created", "filename": filename})
    return jsonify({"status": "snapshot_created", "filename": filename})


@app.route("/api/snapshots")
def list_snapshots():
    return jsonify({"snapshots": snapshot_engine.list_snapshots()})


@app.route("/api/restore", methods=["POST"])
def restore_cluster():
    """Restore cluster from the latest snapshot, or a specific one."""
    data = request.json or {}
    filename = data.get("filename")

    # Stop background threads before restore
    failure_detector.stop()
    health_checker.stop()

    if filename:
        result = disaster_restore.restore_from_file(filename)
    else:
        result = disaster_restore.restore_from_latest()

    # Restart background threads
    health_checker.start()
    failure_detector.start()

    push_sse_event("restore", result)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════
#  HEALTH / METRICS
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/health")
def cluster_health():
    """Get cluster-wide health summary."""
    return jsonify(health_checker.get_cluster_health_summary())


@app.route("/api/health/<pod_name>")
def pod_health(pod_name):
    """Get health history for a specific pod."""
    rec = health_checker.get_pod_health(pod_name)
    if not rec:
        return jsonify({"error": "Pod not found"}), 404
    return jsonify(rec)


@app.route("/api/metrics")
def get_metrics():
    """Get comprehensive platform metrics."""
    return jsonify({
        "cluster": cluster.to_dict(),
        "health": health_checker.get_cluster_health_summary(),
        "failures": failure_detector.get_failure_summary(),
        "recovery": recovery_engine.get_recovery_summary(),
        "proxy": proxy_server.get_all_stats(),
        "snapshots": len(snapshot_engine.list_snapshots()),
        "restores": len(disaster_restore.get_restore_history()),
    })


@app.route("/api/failures")
def get_failures():
    return jsonify({
        "active": failure_detector.get_active_failures(),
        "summary": failure_detector.get_failure_summary(),
    })


@app.route("/api/recovery")
def get_recovery():
    return jsonify(recovery_engine.get_recovery_summary())


# ═══════════════════════════════════════════════════════════════════
#  AUTOMATION SCRIPTS (Section 12)
# ═══════════════════════════════════════════════════════════════════

@app.route("/api/scale", methods=["POST"])
def scale_deployment():
    """Scale a deployment to a new replica count."""
    data = request.json or {}
    dep_name = data.get("deployment")
    replicas = data.get("replicas", 3)

    dep = cluster.get_deployment(dep_name)
    if not dep:
        return jsonify({"error": f"Deployment '{dep_name}' not found"}), 404

    old_count = dep.replicas_desired
    dep.replicas_desired = replicas
    recovery_engine._reconcile_deployment(dep)

    push_sse_event("scale", {"deployment": dep_name, "old": old_count, "new": replicas})
    cluster._log_event("Scale", f"Deployment '{dep_name}' scaled {old_count}→{replicas}")

    return jsonify({
        "deployment": dep_name,
        "old_replicas": old_count,
        "new_replicas": replicas,
        "pods": [p.name for p in dep.pods],
    })


@app.route("/api/reset", methods=["POST"])
def reset_system():
    """Full system reset from config."""
    failure_detector.stop()
    health_checker.stop()
    snapshot_engine.stop()
    init_system()
    return jsonify({"status": "reset", "message": "System reinitialized from config"})


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, port=8000)
