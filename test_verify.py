"""Quick verification of all API endpoints."""
import urllib.request
import json

BASE = "http://localhost:8000"

def get(path):
    r = urllib.request.urlopen(f"{BASE}{path}", timeout=5)
    return json.loads(r.read())

endpoints = [
    ("/api/services", "Services"),
    ("/api/containers", "Containers"),
    ("/api/health", "Health"),
    ("/api/metrics", "Metrics"),
    ("/api/failures", "Failures"),
    ("/api/ai/history", "AI History"),
    ("/api/recovery", "Recovery"),
    ("/api/deployment", "Deployment"),
    ("/api/timeline", "Timeline"),
]

print("=" * 50)
print("  API ENDPOINT VERIFICATION")
print("=" * 50)

for path, name in endpoints:
    try:
        data = get(path)
        print(f"  ✅ {name:15s} {path}")
    except Exception as e:
        print(f"  ❌ {name:15s} {path} — {e}")

# Show key data
h = get("/api/health")
print(f"\n  Containers: {h['total_containers']} | Health: {h['health_pct']}%")

s = get("/api/services")
for svc in s["services"]:
    print(f"  {svc['name']}: {svc['replicas_running']}/{svc['replicas_desired']}")
