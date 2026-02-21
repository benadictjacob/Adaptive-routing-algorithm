"""Quick API verification script."""
import urllib.request
import json

BASE = "http://localhost:5000"

def api_get(path):
    r = urllib.request.urlopen(BASE + path)
    return json.loads(r.read())

def api_post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(BASE + path, body, {"Content-Type": "application/json"})
    r = urllib.request.urlopen(req)
    return json.loads(r.read())

# Test 1: Network
net = api_get("/api/network")
print(f"[OK] Network: {len(net['nodes'])} nodes, {len(net['edges'])} edges")

# Test 2: Route
route = api_post("/api/route", {"start": "N000", "target": [0.8, 0.8, 0.8, 0.8]})
print(f"[OK] Route: {' -> '.join(route['path'])}  success={route['success']}  hops={route['total_hops']}")

# Test 3: Fail a node
fail = api_post("/api/node/N012/fail")
print(f"[OK] Fail N012: alive={fail['alive']}")

# Test 4: Route again (should avoid N012)
route2 = api_post("/api/route", {"start": "N000", "target": [0.8, 0.8, 0.8, 0.8]})
print(f"[OK] Route (N012 down): {' -> '.join(route2['path'])}  success={route2['success']}")
assert "N012" not in route2["path"], "FAIL: N012 should not be in path!"
print("[OK] N012 successfully avoided!")

# Test 5: Recover
api_post("/api/node/N012/recover")
print("[OK] N012 recovered")

# Test 6: Stress test
stress = api_post("/api/stress", {"count": 50})
print(f"[OK] Stress: {stress['count']} requests, {stress['success_rate']}% success, avg {stress['average_hops']} hops")

# Test 7: Metrics
metrics = api_get("/api/metrics")
print(f"[OK] Metrics: {metrics['total_requests']} total, {metrics['success_rate']}% success")

# Test 8: Dashboard HTML
r = urllib.request.urlopen(BASE + "/")
html = r.read().decode()
assert "AVRS" in html
print(f"[OK] Dashboard HTML served ({len(html)} bytes)")

# Reset
api_post("/api/reset")
print("[OK] Reset complete")

print("\n=== ALL API TESTS PASSED ===")
