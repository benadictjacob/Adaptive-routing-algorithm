"""
═══════════════════════════════════════════════════════════════════════
  AUTH SERVICE — Real Docker Container
═══════════════════════════════════════════════════════════════════════

Simulates authentication/token validation.
Can trigger memory errors, import failures, and crashes.
"""

import os
import sys
import time
import random
from flask import Flask, jsonify, request

app = Flask(__name__)

SERVICE_NAME = os.environ.get("SERVICE_NAME", "auth-service")
INSTANCE_ID = os.environ.get("HOSTNAME", "unknown")
START_TIME = time.time()
token_store = {}
should_fail = False


@app.route("/")
def root():
    return jsonify({
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "status": "ok",
        "active_tokens": len(token_store),
    })


@app.route("/health")
def health():
    global should_fail
    if should_fail:
        return jsonify({"status": "unhealthy", "reason": "auth database unreachable"}), 500

    return jsonify({
        "status": "healthy",
        "service": SERVICE_NAME,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "active_tokens": len(token_store),
    })


@app.route("/auth/validate", methods=["POST"])
def validate_token():
    """Validate a token — simulates real auth work."""
    data = request.json or {}
    token = data.get("token", "")
    # Simulate processing time
    time.sleep(random.uniform(0.01, 0.1))
    valid = len(token) > 5
    return jsonify({"valid": valid, "token": token[:8] + "..."})


@app.route("/simulate/crash")
def simulate_crash():
    """Crash with a real MemoryError-style traceback."""
    print(f"[FATAL] {SERVICE_NAME}: Out of memory during token validation!", file=sys.stderr)
    print(f"Traceback (most recent call last):", file=sys.stderr)
    print(f'  File "app.py", line 55, in validate_batch', file=sys.stderr)
    print(f"    tokens = load_all_tokens()", file=sys.stderr)
    print(f'  File "app.py", line 72, in load_all_tokens', file=sys.stderr)
    print(f"    cache = [0] * (10**10)", file=sys.stderr)
    print(f"MemoryError: unable to allocate 80.0 GiB", file=sys.stderr)
    sys.stderr.flush()
    os._exit(137)


@app.route("/simulate/exception")
def simulate_exception():
    """Trigger a real ImportError."""
    import nonexistent_crypto_module  # noqa: This WILL crash
    return jsonify({"status": "unreachable"})


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
