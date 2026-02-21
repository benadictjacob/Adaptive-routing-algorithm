"""
═══════════════════════════════════════════════════════════════════════
  ORCHESTRATOR SERVER — Central API for Self-Healing Platform
═══════════════════════════════════════════════════════════════════════

Integrates: Monitor, Logs, AI Engine, Recovery, Deployment
Serves: Dashboard, REST API, SSE Events, Timeline
"""

import time
import json
import threading
import docker
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS

from monitor.monitor import HealthMonitor, FailureEvent
from logs.collector import LogCollector
from ai_engine.analyzer import AIAnalyzer
from recovery.recovery import RecoveryEngine
from deployment.deployer import BlueGreenDeployer

# ═══════════════════════════════════════════════════════════
#  APP INIT
# ═══════════════════════════════════════════════════════════

app = Flask(__name__, static_folder="dashboard", static_url_path="")
CORS(app)

monitor = None
log_collector = None
ai_analyzer = None
recovery_engine = None
deployer = None
docker_client = None

# Event + Timeline stores
event_stream = []
timeline_entries = []
MAX_EVENTS = 200

SERVICE_PORTS = {
    "healstack_api-gateway": 9001,
    "healstack_auth-service": 9002,
    "healstack_data-service": 9003,
}


def push_event(event_type, data):
    entry = {"type": event_type, "data": data, "timestamp": time.time()}
    event_stream.append(entry)
    if len(event_stream) > MAX_EVENTS:
        event_stream.pop(0)


def push_timeline(phase, service, message, details=None):
    entry = {
        "phase": phase,
        "service": service,
        "message": message,
        "details": details or {},
        "timestamp": time.time(),
    }
    timeline_entries.append(entry)
    if len(timeline_entries) > MAX_EVENTS:
        timeline_entries.pop(0)
    push_event("timeline", entry)


# ═══════════════════════════════════════════════════════════
#  SELF-HEALING PIPELINE CALLBACK
# ═══════════════════════════════════════════════════════════

def on_failure_detected(event: FailureEvent):
    """
    Complete self-healing pipeline:
    1. Failure detected → 2. Logs fetched → 3. AI analysis → 4. Recovery → 5. Restored
    """
    # Phase 1: Detection
    push_timeline("detection", event.service_name,
                  f"🚨 {event.event_type}: {event.message}")
    push_event("failure", event.to_dict())
    print(f"\n🚨 FAILURE: [{event.event_type}] {event.service_name}: {event.message}")

    # Phase 2: Log collection
    logs = ""
    try:
        logs = log_collector.collect_from_service(event.service_name)
        if not logs:
            logs = log_collector.collect_from_container(event.container_name)
        event.logs = logs
        push_timeline("logs_captured", event.service_name,
                      f"📋 Captured {len(logs)} chars of logs")
        print(f"📋 LOGS: Captured {len(logs)} chars from {event.container_name}")
    except Exception as e:
        push_timeline("logs_captured", event.service_name,
                      f"⚠️ Log capture failed: {str(e)[:60]}")

    # Phase 3: AI analysis
    context = {"exit_code": event.details.get("exit_code")}
    analysis = ai_analyzer.analyze(logs, context)
    event.ai_analysis = analysis
    push_timeline("analysis", event.service_name,
                  f"🤖 {analysis['error_type']}: {analysis['human_explanation'][:100]}")
    push_event("ai_analysis", {
        "service": event.service_name,
        "analysis": analysis,
    })
    print(f"🤖 AI: {analysis['error_type']} — {analysis['human_explanation'][:80]}")

    # Phase 4: Recovery
    recovery_engine.handle_failure(event)
    push_timeline("recovery", event.service_name,
                  f"🔧 Recovery action executed for {event.service_name}")
    push_event("recovery", {
        "service": event.service_name,
        "message": f"Auto-recovered {event.service_name}",
    })
    print(f"♻️ RECOVERED: {event.service_name}")

    # Phase 5: Mark restored
    push_timeline("restored", event.service_name,
                  f"✅ {event.service_name} recovery complete")


# ═══════════════════════════════════════════════════════════
#  ROUTES — Dashboard
# ═══════════════════════════════════════════════════════════

@app.route("/")
def dashboard():
    return send_from_directory("dashboard", "index.html")


# ═══════════════════════════════════════════════════════════
#  ROUTES — Services & Containers
# ═══════════════════════════════════════════════════════════

@app.route("/api/services")
def api_services():
    try:
        services = docker_client.services.list(
            filters={"label": "com.docker.stack.namespace=healstack"}
        )
        result = []
        for svc in services:
            tasks = svc.tasks()
            running = sum(1 for t in tasks if t["Status"]["State"] == "running")
            desired = svc.attrs["Spec"]["Mode"].get("Replicated", {}).get("Replicas", 0)
            result.append({
                "name": svc.name,
                "id": svc.short_id,
                "image": svc.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"].split("@")[0],
                "replicas_running": running,
                "replicas_desired": desired,
                "ports": svc.attrs["Endpoint"].get("Ports", []),
            })
        return jsonify({"services": result})
    except Exception as e:
        return jsonify({"services": [], "error": str(e)[:100]})


@app.route("/api/containers")
def api_containers():
    try:
        states = monitor.get_all_states()
        return jsonify({"containers": states})
    except Exception:
        return jsonify({"containers": []})


@app.route("/api/logs/<target>")
def api_logs(target):
    """Fetch logs for a service or a specific container."""
    tail = request.args.get("tail", 100, type=int)
    # Try service logs first
    logs = log_collector.fetch_service_logs(target, tail=tail)
    if "[ERROR]" in logs:
        # Fallback to container logs
        logs = log_collector.fetch_logs(target, tail=tail)
    return jsonify({"target": target, "logs": logs})


# ═══════════════════════════════════════════════════════════
#  ROUTES — Health & Metrics
# ═══════════════════════════════════════════════════════════

@app.route("/api/health")
def api_health():
    states = monitor.get_all_states()
    total = len(states)
    healthy = sum(1 for s in states if s["status"] == "running" and s["health"] != "unhealthy")
    pct = int(healthy / total * 100) if total > 0 else 100
    return jsonify({
        "total_containers": total,
        "healthy": healthy,
        "unhealthy": total - healthy,
        "health_pct": pct,
    })


@app.route("/api/metrics")
def api_metrics():
    health_summary = monitor.get_failure_summary()
    recovery_summary = recovery_engine.get_summary()
    return jsonify({
        "health": health_summary,
        "recovery": recovery_summary,
        "ai_analyses": len(ai_analyzer.analysis_history),
        "disaster_mode": recovery_engine.disaster_mode,
    })


# ═══════════════════════════════════════════════════════════
#  ROUTES — Failures & AI
# ═══════════════════════════════════════════════════════════

@app.route("/api/failures")
def api_failures():
    active = monitor.get_active_failures()
    return jsonify({
        "active": active,
        "total": len(monitor.failure_history),
    })


@app.route("/api/ai/history")
def api_ai_history():
    return jsonify({"analyses": ai_analyzer.get_history()})


# ═══════════════════════════════════════════════════════════
#  ROUTES — Recovery & Deployment
# ═══════════════════════════════════════════════════════════

@app.route("/api/recovery")
def api_recovery():
    return jsonify(recovery_engine.get_summary())


@app.route("/api/deployment")
def api_deployment():
    return jsonify(deployer.get_all())


@app.route("/api/deploy", methods=["POST"])
def api_deploy():
    data = request.get_json() or {}
    service = data.get("service", "")
    image = data.get("image", "")
    port = SERVICE_PORTS.get(service, 9001)

    if not service or not image:
        return jsonify({"error": "Provide 'service' and 'image'"}), 400

    def run_deploy():
        deployer.deploy(service, image, port)
    threading.Thread(target=run_deploy, daemon=True).start()
    return jsonify({"status": "deploying", "service": service, "image": image})


@app.route("/api/scale", methods=["POST"])
def api_scale():
    data = request.get_json() or {}
    service = data.get("service", "")
    replicas = data.get("replicas", 2)
    recovery_engine.scale_service(service, replicas)
    return jsonify({"status": "scaled", "service": service, "replicas": replicas})


# ═══════════════════════════════════════════════════════════
#  ROUTES — Timeline
# ═══════════════════════════════════════════════════════════

@app.route("/api/timeline")
def api_timeline():
    return jsonify({"entries": timeline_entries[-50:]})


# ═══════════════════════════════════════════════════════════
#  ROUTES — Simulation
# ═══════════════════════════════════════════════════════════

@app.route("/api/simulate/kill-container", methods=["POST"])
def sim_kill():
    data = request.get_json() or {}
    service_name = data.get("service", "healstack_api-gateway")
    try:
        containers = docker_client.containers.list(
            filters={"label": f"com.docker.swarm.service.name={service_name}"}
        )
        if containers:
            c = containers[0]
            c.kill()
            push_timeline("simulation", service_name, f"💀 Killed container {c.short_id}")
            return jsonify({"status": "killed", "container": c.short_id})
        return jsonify({"error": "No running container found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)[:100]}), 500


@app.route("/api/simulate/crash-service", methods=["POST"])
def sim_crash():
    data = request.get_json() or {}
    port = data.get("port", 9001)
    try:
        import urllib.request
        req = urllib.request.Request(f"http://localhost:{port}/simulate/crash")
        urllib.request.urlopen(req, timeout=3)
        return jsonify({"status": "crash triggered"})
    except Exception:
        return jsonify({"status": "crash signal sent"})


@app.route("/api/simulate/toggle-health", methods=["POST"])
def sim_toggle():
    data = request.get_json() or {}
    port = data.get("port", 9001)
    try:
        import urllib.request
        req = urllib.request.Request(f"http://localhost:{port}/simulate/toggle-health")
        urllib.request.urlopen(req, timeout=3)
        return jsonify({"status": "health toggled"})
    except Exception:
        return jsonify({"status": "toggle signal sent"})


# ═══════════════════════════════════════════════════════════
#  SSE EVENT STREAM
# ═══════════════════════════════════════════════════════════

@app.route("/api/events/stream")
def sse_stream():
    def generate():
        idx = len(event_stream)
        while True:
            while idx < len(event_stream):
                yield f"data: {json.dumps(event_stream[idx])}\n\n"
                idx += 1
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ═══════════════════════════════════════════════════════════
#  SYSTEM INIT
# ═══════════════════════════════════════════════════════════

def init_system():
    global monitor, log_collector, ai_analyzer, recovery_engine, deployer, docker_client

    docker_client = docker.from_env()
    log_collector = LogCollector()
    ai_analyzer = AIAnalyzer()
    recovery_engine = RecoveryEngine()
    deployer = BlueGreenDeployer(event_callback=lambda t, d: push_event(t, d))

    monitor = HealthMonitor(stack_name="healstack", check_interval=5.0)
    monitor.on_failure(on_failure_detected)
    monitor.start()

    push_event("system", {"message": "Self-healing infrastructure online"})

    info = docker_client.info()
    swarm = info.get("Swarm", {})
    print(f"\n{'='*60}")
    print(f"  SERVER SELF-HEALING PLATFORM")
    print(f"  Swarm: {swarm.get('LocalNodeState', 'unknown')}")
    print(f"  Nodes: {swarm.get('Nodes', 0)}  | Managers: {swarm.get('Managers', 0)}")
    print(f"  Monitor: 5s  | Services: {len(SERVICE_PORTS)}")
    print(f"  Dashboard: http://localhost:8000")
    print(f"{'='*60}\n")


init_system()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
