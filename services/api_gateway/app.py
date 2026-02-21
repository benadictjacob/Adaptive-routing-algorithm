"""
═══════════════════════════════════════════════════════════════════════
  API GATEWAY SERVICE — Real Docker Container
═══════════════════════════════════════════════════════════════════════

Lightweight Flask microservice that acts as the cluster entry point.
Has a /health endpoint and built-in failure simulation triggers.
"""

import os
import sys
import time
import random
import traceback
from flask import Flask, jsonify, request

app = Flask(__name__)

SERVICE_NAME = os.environ.get("SERVICE_NAME", "api-gateway")
INSTANCE_ID = os.environ.get("HOSTNAME", "unknown")
START_TIME = time.time()
request_count = 0
should_fail = False


@app.route("/")
def root():
    global request_count
    request_count += 1
    return jsonify({
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "status": "ok",
        "requests_served": request_count,
    })


@app.route("/health")
def health():
    """Health check endpoint — Docker HEALTHCHECK calls this."""
    global should_fail
    if should_fail:
        return jsonify({"status": "unhealthy", "reason": "simulated failure"}), 500

    return jsonify({
        "status": "healthy",
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "requests_served": request_count,
    })


@app.route("/simulate/crash")
def simulate_crash():
    """Trigger a REAL process crash — the container will restart."""
    print(f"[FATAL] {SERVICE_NAME}: Simulated crash triggered!", file=sys.stderr)
    print(f"Traceback (most recent call last):", file=sys.stderr)
    print(f'  File "app.py", line 42, in process_request', file=sys.stderr)
    print(f"    result = handle_data(payload)", file=sys.stderr)
    print(f'  File "app.py", line 67, in handle_data', file=sys.stderr)
    print(f"    return data['key'] / 0", file=sys.stderr)
    print(f"ZeroDivisionError: division by zero", file=sys.stderr)
    sys.stderr.flush()
    os._exit(1)


@app.route("/simulate/exception")
def simulate_exception():
    """Trigger an unhandled exception — generates a real traceback."""
    data = {"users": [1, 2, 3]}
    # This will crash with a real KeyError
    return jsonify({"result": data["nonexistent_key"]})


@app.route("/simulate/slow")
def simulate_slow():
    """Simulate high latency / timeout."""
    delay = random.uniform(5, 15)
    print(f"[WARN] {SERVICE_NAME}: Simulating {delay:.1f}s delay", file=sys.stderr)
    time.sleep(delay)
    return jsonify({"status": "slow_response", "delay_seconds": delay})


@app.route("/simulate/toggle-health")
def toggle_health():
    """Toggle health status between healthy/unhealthy."""
    global should_fail
    should_fail = not should_fail
    status = "unhealthy" if should_fail else "healthy"
    print(f"[INFO] {SERVICE_NAME}: Health toggled to {status}", file=sys.stderr)
    return jsonify({"health_status": status})


if __name__ == "__main__":
    print(f"[{SERVICE_NAME}] Starting on port 5000 (instance: {INSTANCE_ID})")
    app.run(host="0.0.0.0", port=5000, debug=False)
