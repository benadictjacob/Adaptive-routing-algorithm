"""Quick verification of semantic clustering, toggle, and failover routing."""
import requests, json

BASE = "http://127.0.0.1:5000"

# 1. Check network structure
print("=" * 60)
print("1. NETWORK STRUCTURE")
print("=" * 60)
r = requests.get(f"{BASE}/api/network")
d = r.json()
print(f"Architecture: {d['label']}")
print(f"Total nodes: {len(d['nodes'])}")
print(f"\nRoles:")
for ro in d['roles']:
    print(f"  {ro['name']:16s}  color_idx={ro['color_idx']}  count={ro['count']}  center={ro['center']}")

print(f"\nFirst 10 nodes:")
for n in d['nodes'][:10]:
    print(f"  {n['id']}: role={n['role']:16s} cluster={n['cluster']} alive={n['alive']} vec={n['vector']}")

# 2. Test toggle
print("\n" + "=" * 60)
print("2. TOGGLE NODE N000")
print("=" * 60)
r = requests.post(f"{BASE}/api/node/N000/toggle")
print(f"Response: {r.json()}")

r2 = requests.get(f"{BASE}/api/network")
n000 = [n for n in r2.json()['nodes'] if n['id'] == 'N000'][0]
print(f"N000 after toggle: alive={n000['alive']}")

# 3. Test routing with failed node — should route to same-section
print("\n" + "=" * 60)
print("3. ROUTING WITH FAILED NODE (same-section failover)")
print("=" * 60)
# Route toward api_gateway center [0.8, 0.8, 0.2, 0.2] with N000 dead
r = requests.post(f"{BASE}/api/route", json={
    "start": "N003",  # start from auth_service 
    "target": [0.8, 0.8, 0.2, 0.2]  # target = api_gateway center
})
route = r.json()
print(f"Adaptive: success={route['adaptive']['success']}, path={route['adaptive']['path']}")
if route.get('trad'):
    print(f"Traditional: success={route['trad']['success']}, path={route['trad']['path']}")

# Check that the path ends at an api_gateway node (same section as target)
net = requests.get(f"{BASE}/api/network").json()
node_map = {n['id']: n for n in net['nodes']}
if route['adaptive']['path']:
    last = route['adaptive']['path'][-1]
    print(f"\nFinal node: {last}, role={node_map[last]['role']}, vec={node_map[last]['vector']}")
    print(f"Target was api_gateway center [0.8, 0.8, 0.2, 0.2]")
    if node_map[last]['role'] == 'api_gateway':
        print("✓ PASSED: Routed to same-section (api_gateway) node!")
    else:
        print(f"→ Routed to {node_map[last]['role']} (nearest reachable node)")

# 4. Recover N000
print("\n" + "=" * 60)
print("4. RECOVER N000")
print("=" * 60)
r = requests.post(f"{BASE}/api/node/N000/toggle")
print(f"Response: {r.json()}")

print("\n✓ All verification complete!")
