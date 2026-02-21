"""Quick test of the self-healing pipeline."""
import urllib.request
import json
import time

BASE = "http://localhost:8000"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=5)
    return json.loads(r.read())

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, 
                                headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=5)
    return json.loads(r.read())


print("=" * 60)
print("  TEST 1: Service Status")
print("=" * 60)
svcs = get("/api/services")["services"]
for s in svcs:
    print(f"  {s['name']}: {s['replicas_running']}/{s['replicas_desired']}")

print()
print("=" * 60)
print("  TEST 2: Cluster Health")
print("=" * 60)
h = get("/api/health")
print(f"  Health: {h['health_pct']}% | Healthy: {h['healthy']}/{h['total_containers']}")

print()
print("=" * 60)
print("  TEST 3: Kill API Gateway Container")
print("=" * 60)
try:
    result = post("/api/simulate/kill-container", {"service": "healstack_api-gateway"})
    print(f"  Killed: {result.get('container')}")
except Exception as e:
    print(f"  Error: {e}")

print("  Waiting 10s for recovery...")
time.sleep(10)

print()
print("=" * 60)
print("  TEST 4: Check Recovery")
print("=" * 60)
h2 = get("/api/health")
print(f"  Health: {h2['health_pct']}% | Containers: {h2['total_containers']}")

recovery = get("/api/recovery")
print(f"  Recovery actions: {recovery['total_actions']}")
for a in recovery.get("recent", []):
    print(f"    -> {a['action_type']}: {a['message']}")

print()
print("=" * 60)
print("  TEST 5: AI Analysis History")
print("=" * 60)
ai = get("/api/ai/history")
for a in ai.get("analyses", []):
    print(f"  {a['error_type']} ({a['severity']}): {a['root_cause'][:80]}")

print()
print("ALL TESTS COMPLETE")
