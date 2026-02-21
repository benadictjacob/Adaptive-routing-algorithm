"""
═══════════════════════════════════════════════════════════════════════
  DATA SERVICE — Real Docker Container
═══════════════════════════════════════════════════════════════════════

Simulates database operations.
Can trigger connection errors, timeouts, and data corruption.
"""

import os
import sys
import time
import random
from flask import Flask, jsonify, request

app = Flask(__name__)

SERVICE_NAME = os.environ.get("SERVICE_NAME", "data-service")
INSTANCE_ID = os.environ.get("HOSTNAME", "unknown")
START_TIME = time.time()
data_store = {"users": 150, "orders": 3420, "products": 89}
query_count = 0
should_fail = False


@app.route("/")
def root():
    return jsonify({
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "status": "ok",
        "queries_served": query_count,
    })


@app.route("/health")
def health():
    global should_fail
    if should_fail:
        return jsonify({"status": "unhealthy", "reason": "database connection refused"}), 500

    return jsonify({
        "status": "healthy",
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "queries_served": query_count,
        "db_status": "connected",
    })


@app.route("/data/query")
def query_data():
    """Simulate a database query."""
    global query_count
    query_count += 1
    time.sleep(random.uniform(0.01, 0.05))
    return jsonify({"data": data_store, "query_id": query_count})


@app.route("/simulate/crash")
def simulate_crash():
    """Crash with a database connection error traceback."""
    print(f"[FATAL] {SERVICE_NAME}: Database connection lost!", file=sys.stderr)
    print(f"Traceback (most recent call last):", file=sys.stderr)
    print(f'  File "app.py", line 48, in query_handler', file=sys.stderr)
    print(f"    conn = db_pool.get_connection(timeout=5)", file=sys.stderr)
    print(f'  File "db_pool.py", line 112, in get_connection', file=sys.stderr)
    print(f"    raise ConnectionRefusedError(host, port)", file=sys.stderr)
    print(f"ConnectionRefusedError: [Errno 111] Connection refused: 'db-primary:5432'", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"The above exception was the direct cause of the following exception:", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f'  File "app.py", line 52, in query_handler', file=sys.stderr)
    print(f"    return execute_query(sql, params)", file=sys.stderr)
    print(f"RuntimeError: All database connections exhausted. Pool size: 10, active: 10, available: 0", file=sys.stderr)
    sys.stderr.flush()
    os._exit(1)


@app.route("/simulate/exception")
def simulate_exception():
    """Trigger a real TypeError."""
    result = len(42)  # This will crash with TypeError
    return jsonify({"result": result})


@app.route("/simulate/timeout")
def simulate_timeout():
    """Simulate a database query timeout."""
    print(f"[WARN] {SERVICE_NAME}: Query timeout — table lock detected", file=sys.stderr)
    time.sleep(30)
    return jsonify({"status": "timeout"})


@app.route("/simulate/toggle-health")
def toggle_health():
    global should_fail
    should_fail = not should_fail
    status = "unhealthy" if should_fail else "healthy"
    print(f"[INFO] {SERVICE_NAME}: Health toggled to {status}", file=sys.stderr)
    return jsonify({"health_status": status})


if __name__ == "__main__":
    print(f"[{SERVICE_NAME}] Starting on port 5000 (instance: {INSTANCE_ID})")
    app.run(host="0.0.0.0", port=5000, debug=False)
