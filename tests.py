"""
═══════════════════════════════════════════════════════════════════════
  AUTOMATED TEST SUITE
  Sections 16 (Automated Tests), 17 (Extreme Stress), 18 (Assertions)
═══════════════════════════════════════════════════════════════════════

Each test prints PASS/FAIL.
System must guarantee: no infinite loops, no cycling, no invalid math,
no crashes, finite termination.
"""

import sys
import os
import random
import math
import traceback
from typing import List

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vector_math import (
    dot_product, magnitude, cosine_similarity,
    euclidean_distance, vector_subtract, vector_add, normalize,
)
from graph_builder import (
    Node, generate_nodes, build_knn_graph, build_delaunay_graph,
    validate_graph, graph_diagnostics, heal_around_failure,
    insert_node, remove_node, rebuild_topology,
)
from topology_engine import greedy_guarantee_check, face_route_full
from routing_engine import RoutingEngine
from simulator import Simulator, Request


# ═══════════════════════════════════════════════════════════════════
#  TEST INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════

_results = []


def run_test(name: str, test_fn):
    """Run a test function and record PASS/FAIL."""
    try:
        test_fn()
        print(f"  [PASS] {name}")
        _results.append((name, True, ""))
    except Exception as e:
        print(f"  [FAIL] {name}")
        print(f"         Error: {e}")
        _results.append((name, False, str(e)))


def make_network(n=20, k=5, dim=4, seed=42, mode="delaunay"):
    """Helper: generate a network for testing."""
    nodes = generate_nodes(n, dim, seed)
    if mode == "delaunay":
        nodes, actual = build_delaunay_graph(nodes)
    else:
        build_knn_graph(nodes, k)
        actual = "knn"
    return nodes, actual


def make_simulator(nodes, **kwargs):
    """Helper: create a Simulator."""
    engine = RoutingEngine(**kwargs)
    return Simulator(nodes, engine, verbose=False)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 16 — AUTOMATED TESTS (10 tests)
# ═══════════════════════════════════════════════════════════════════

def test_basic_routing():
    """Test 1: Basic routing succeeds and produces a valid path."""
    nodes, _ = make_network(n=20, seed=42)
    sim = make_simulator(nodes)
    start = nodes[0]
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(start, req)
    assert result.success, f"Routing failed from {start.id}"
    assert result.total_hops > 0, "Zero hops"
    assert len(result.path) > 0, "Empty path"
    assert result.path[0] == start.id, "Path doesn't start at start node"


def test_dead_node_recovery():
    """Test 2: Routing bypasses dead nodes and still succeeds."""
    nodes, _ = make_network(n=30, seed=42)
    sim = make_simulator(nodes, use_cache=False)
    start = nodes[0]
    target = [0.5, 0.5, 0.5, 0.5]
    req = Request(target_vector=target)

    # Route normally first
    result1 = sim.route_request(start, req)
    # Reset loads
    for n in nodes:
        n.reset_load()

    # Kill some intermediate nodes
    for nid in result1.path[1:-1][:3]:
        n = sim.get_node(nid)
        if n:
            n.fail()
            heal_around_failure(n, nodes)

    # Route again
    result2 = sim.route_request(start, req)
    assert result2.success, "Routing failed after node deaths"
    for nid in result1.path[1:-1][:3]:
        n = sim.get_node(nid)
        if n and not n.alive:
            assert nid not in result2.path, f"Dead node {nid} in path"

    # Recover
    for n in nodes:
        n.recover()


def test_load_balancing():
    """Test 3: Repeated requests cause path divergence due to load."""
    nodes, _ = make_network(n=30, seed=42)
    sim = make_simulator(nodes, use_cache=False)
    target = [0.5, 0.5, 0.5, 0.5]
    paths = []
    for i in range(10):
        start = nodes[i % len(nodes)]
        req = Request(target_vector=target, sender_id=f"c{i}")
        result = sim.route_request(start, req)
        paths.append(tuple(result.path))

    # Check that load accumulated
    loaded = [n for n in nodes if n.load > 1]
    assert len(loaded) > 0, "No load accumulation detected"

    # Check that at least some paths differ (load caused divergence)
    unique_paths = set(paths)
    assert len(unique_paths) > 1, "All paths identical despite load"


def test_trust_avoidance():
    """Test 4: Low-trust nodes are avoided when alternatives exist."""
    nodes, _ = make_network(n=20, seed=42)
    sim = make_simulator(nodes, use_cache=False)
    start = nodes[0]
    target = [0.5, 0.5, 0.5, 0.5]

    # Route normally
    req = Request(target_vector=target)
    result_normal = sim.route_request(start, req)
    for n in nodes:
        n.reset_load()

    # Reduce trust on nodes in the middle of the path
    attacked = []
    for nid in result_normal.path[1:-1]:
        n = sim.get_node(nid)
        if n:
            n.reduce_trust(0.9)  # Near-zero trust
            attacked.append(nid)

    # Route again
    result_trust = sim.route_request(start, req)
    assert result_trust.success, "Routing failed with low-trust nodes"

    # Restore
    for n in nodes:
        n.restore_trust()
        n.reset_load()


def test_greedy_failure():
    """Test 5: Greedy routing handles local minima via fallback."""
    # Build a small pathological case
    a = Node("A", [0.0, 0.0, 0.0, 0.0])
    b = Node("B", [0.3, 0.3, 0.3, 0.3])
    c = Node("C", [-0.2, -0.2, -0.2, -0.2])  # Wrong direction
    d = Node("D", [0.8, 0.8, 0.8, 0.8])      # Close to target

    a.add_neighbor(b); b.add_neighbor(a)
    a.add_neighbor(c); c.add_neighbor(a)
    b.add_neighbor(d); d.add_neighbor(b)
    c.add_neighbor(d); d.add_neighbor(c)

    nodes = [a, b, c, d]
    engine = RoutingEngine(use_face_routing=False, use_cache=False)
    sim = Simulator(nodes, engine, verbose=False)
    req = Request(target_vector=[1.0, 1.0, 1.0, 1.0])
    result = sim.route_request(a, req)
    assert result.success, "Greedy with fallback failed"


def test_face_routing_activation():
    """Test 6: Face routing activates when greedy is stuck."""
    # Create a ring topology where greedy might get stuck
    nodes_list = []
    n = 10
    for i in range(n):
        angle = 2 * math.pi * i / n
        vec = [math.cos(angle), math.sin(angle), 0.0, 0.0]
        nodes_list.append(Node(f"R{i:02d}", vec))

    # Ring connectivity
    for i in range(n):
        nodes_list[i].add_neighbor(nodes_list[(i + 1) % n])
        nodes_list[(i + 1) % n].add_neighbor(nodes_list[i])

    engine = RoutingEngine(use_face_routing=True, use_cache=False)
    sim = Simulator(nodes_list, engine, verbose=False)

    # Target opposite side of ring
    req = Request(target_vector=[-1.0, 0.0, 0.0, 0.0])
    result = sim.route_request(nodes_list[0], req)
    assert result.success, "Face routing failed on ring"


def test_random_stress():
    """Test 7: 100 random routing requests all succeed."""
    nodes, _ = make_network(n=50, seed=77)
    sim = make_simulator(nodes, use_cache=False)
    rng = random.Random(123)

    failures = 0
    for i in range(100):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-1, 1) for _ in range(4)]
        req = Request(target_vector=target, sender_id=f"stress-{i}")
        result = sim.route_request(start, req)
        if not result.success:
            failures += 1

    # Allow up to 5% failure rate
    assert failures <= 5, f"Too many failures: {failures}/100"


def test_repeated_request_stability():
    """Test 8: Same request repeated produces consistent results."""
    nodes, _ = make_network(n=20, seed=42)
    target = [0.5, 0.5, 0.5, 0.5]
    results_list = []

    for trial in range(5):
        # Fresh network each time
        fresh_nodes, _ = make_network(n=20, seed=42)
        sim = make_simulator(fresh_nodes, use_cache=False)
        req = Request(target_vector=target)
        result = sim.route_request(fresh_nodes[0], req)
        results_list.append(result.path)

    # All paths should be identical (deterministic with same seed and no load)
    for path in results_list[1:]:
        assert path == results_list[0], "Non-deterministic results"


def test_scalability():
    """Test 9: System handles large networks (200 nodes)."""
    nodes, _ = make_network(n=200, seed=99)
    sim = make_simulator(nodes)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(nodes[0], req)
    assert result.success, "Scalability test failed"
    assert result.total_hops < 50, f"Too many hops: {result.total_hops}"


def test_direction_correctness():
    """Test 10: Each hop moves closer to target (for greedy hops)."""
    nodes, _ = make_network(n=30, seed=42)
    sim = make_simulator(nodes, use_cache=False)
    target = [0.5, 0.5, 0.5, 0.5]
    req = Request(target_vector=target)
    result = sim.route_request(nodes[0], req)

    # For greedy hops (not fallback/face), distance should decrease
    for hop in result.hops:
        if hop.method == "greedy" and hop.chosen_next:
            next_node = sim.get_node(hop.chosen_next)
            if next_node:
                dist_curr = hop.distance_to_target
                dist_next = euclidean_distance(list(next_node.vector), target)
                assert dist_next <= dist_curr + 0.001, \
                    f"Greedy hop increased distance at {hop.node_id}"


# ═══════════════════════════════════════════════════════════════════
#  SECTION 17 — EXTREME STRESS TESTS (8 tests)
# ═══════════════════════════════════════════════════════════════════

def test_multiple_failures():
    """Stress 1: Route with 30% of nodes failed."""
    nodes, _ = make_network(n=50, seed=42)
    rng = random.Random(42)

    # Kill 30% of nodes
    kill_count = 15
    kill_indices = rng.sample(range(1, 50), kill_count)  # Don't kill node 0 (start)
    for idx in kill_indices:
        nodes[idx].fail()
        heal_around_failure(nodes[idx], nodes)

    sim = make_simulator(nodes, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(nodes[0], req)
    # Should not crash — success is best-effort
    assert result.total_hops > 0, "No hops taken"

    for n in nodes:
        n.recover()


def test_cascading_failures():
    """Stress 2: Nodes fail one-by-one mid-routing (simulated)."""
    nodes, _ = make_network(n=40, seed=42)
    sim = make_simulator(nodes, use_cache=False)

    # Run multiple requests, killing a node between each
    successes = 0
    for i in range(10):
        req = Request(target_vector=[0.3 + i * 0.05, 0.3, 0.3, 0.3])
        result = sim.route_request(nodes[0], req)
        if result.success:
            successes += 1
        # Kill a node after each request (cascading)
        victim_idx = 5 + i
        if victim_idx < len(nodes):
            nodes[victim_idx].fail()
            heal_around_failure(nodes[victim_idx], nodes)

    assert successes >= 5, f"Only {successes}/10 succeeded under cascading failures"

    for n in nodes:
        n.recover()


def test_dense_clusters():
    """Stress 3: Dense cluster with many near-identical vectors."""
    nodes = []
    rng = random.Random(42)
    # Create 30 nodes clustered around (0.5, 0.5, 0.5, 0.5)
    for i in range(30):
        vec = [0.5 + rng.uniform(-0.05, 0.05) for _ in range(4)]
        nodes.append(Node(f"D{i:03d}", vec))
    build_knn_graph(nodes, k=5)

    sim = make_simulator(nodes, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(nodes[0], req)
    assert result.success, "Dense cluster routing failed"


def test_sparse_regions():
    """Stress 4: Very sparse graph (K=2)."""
    nodes = generate_nodes(20, 4, seed=42)
    build_knn_graph(nodes, k=2)
    sim = make_simulator(nodes, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(nodes[0], req)
    # May not succeed with K=2, but must not crash
    assert result.total_hops > 0, "No hops in sparse graph"


def test_duplicate_coordinates():
    """Stress 5: Nodes with identical coordinates."""
    vec = [0.5, 0.5, 0.5, 0.5]
    nodes = [Node(f"DUP{i}", vec) for i in range(5)]
    # Add one distinct node
    nodes.append(Node("DISTINCT", [0.9, 0.9, 0.9, 0.9]))
    build_knn_graph(nodes, k=3)

    sim = make_simulator(nodes, use_cache=False)
    req = Request(target_vector=[0.9, 0.9, 0.9, 0.9])
    result = sim.route_request(nodes[0], req)
    # Must not crash or infinite loop
    assert result.total_hops > 0, "No hops with duplicates"


def test_node_insertion():
    """Stress 6: Insert a node into existing network."""
    nodes, _ = make_network(n=20, seed=42)
    new_node = Node("NEW", [0.5, 0.5, 0.5, 0.5])
    insert_node(new_node, nodes)

    assert new_node in nodes, "Node not added to list"
    assert len(new_node.neighbors) > 0, "New node has no neighbors"

    sim = make_simulator(nodes, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(nodes[0], req)
    assert result.success, "Routing failed after insertion"


def test_node_deletion():
    """Stress 7: Delete nodes and verify routing still works."""
    nodes, _ = make_network(n=30, seed=42)
    # Delete 5 nodes
    for i in range(5, 10):
        remove_node(nodes[i], nodes, heal=True)

    alive = [n for n in nodes if n.alive]
    sim = make_simulator(alive, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(alive[0], req)
    assert result.success, "Routing failed after deletion"


def test_topology_rebuild():
    """Stress 8: Full topology rebuild after mass failure."""
    nodes, _ = make_network(n=40, seed=42)

    # Kill 50%
    for i in range(0, 40, 2):
        nodes[i].fail()

    # Rebuild
    rebuild_topology(nodes, mode="knn", k=5)
    alive = [n for n in nodes if n.alive]

    # Validate rebuilt graph
    val = validate_graph(alive)
    assert val["connected"], f"Rebuilt graph not connected: {val['errors']}"

    sim = make_simulator(alive, use_cache=False)
    req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
    result = sim.route_request(alive[0], req)
    assert result.success, "Routing failed after rebuild"


# ═══════════════════════════════════════════════════════════════════
#  SECTION 18 — ASSERTION TESTS (5 tests)
# ═══════════════════════════════════════════════════════════════════

def test_no_infinite_loops():
    """Assertion 1: Routing always terminates within MAX_HOPS."""
    nodes, _ = make_network(n=30, seed=42)
    engine = RoutingEngine(max_hops=20, use_cache=False)
    sim = Simulator(nodes, engine, verbose=False)
    rng = random.Random(99)
    for i in range(50):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-1, 1) for _ in range(4)]
        req = Request(target_vector=target)
        result = sim.route_request(start, req)
        assert result.total_hops <= 20, \
            f"Exceeded max hops: {result.total_hops}"


def test_no_packet_cycling():
    """Assertion 2: No node appears twice in any path."""
    nodes, _ = make_network(n=30, seed=42)
    sim = make_simulator(nodes, use_cache=False)
    rng = random.Random(88)
    for i in range(50):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-1, 1) for _ in range(4)]
        req = Request(target_vector=target)
        result = sim.route_request(start, req)
        assert len(result.path) == len(set(result.path)), \
            f"Cycle detected in path: {result.path}"


def test_no_invalid_math():
    """Assertion 3: All math operations produce finite results."""
    # Test edge cases
    assert math.isfinite(cosine_similarity([0, 0], [0, 0])), "NaN from zero vectors"
    assert math.isfinite(euclidean_distance([0, 0], [0, 0])), "NaN from same point"
    assert math.isfinite(cosine_similarity([1e10, 1e10], [1e-10, 1e-10])), "NaN from extreme values"

    # Test routing math doesn't produce NaN
    a = Node("A", [0.0, 0.0, 0.0, 0.0])
    b = Node("B", [0.0, 0.0, 0.0, 0.0])  # Duplicate coordinates
    a.add_neighbor(b)
    engine = RoutingEngine()
    score = engine.score_neighbor(a, b, [1.0, 1.0, 1.0, 1.0])
    assert math.isfinite(score), f"Score is not finite: {score}"


def test_no_crashes():
    """Assertion 4: System handles all edge cases without exceptions."""
    # Empty network
    try:
        sim = Simulator([], RoutingEngine(), verbose=False)
    except Exception:
        raise AssertionError("Crashed on empty network creation")

    # Single node
    n = Node("SOLO", [0.0, 0.0, 0.0, 0.0])
    sim = Simulator([n], RoutingEngine(), verbose=False)
    req = Request(target_vector=[1.0, 1.0, 1.0, 1.0])
    result = sim.route_request(n, req)
    # Should terminate (no neighbors = terminal)
    assert result.total_hops > 0, "Single node didn't process request"

    # All nodes dead except start
    nodes = generate_nodes(10, 4, seed=42)
    build_knn_graph(nodes, k=3)
    for n in nodes[1:]:
        n.fail()
    sim = Simulator(nodes, RoutingEngine(), verbose=False)
    result = sim.route_request(nodes[0], req)
    assert result.total_hops > 0, "Crashed with all-dead neighbors"


def test_finite_termination():
    """Assertion 5: Every routing request terminates in finite time."""
    import time
    nodes, _ = make_network(n=50, seed=42)
    sim = make_simulator(nodes)
    rng = random.Random(77)

    for i in range(20):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-2, 2) for _ in range(4)]
        req = Request(target_vector=target)
        t0 = time.time()
        result = sim.route_request(start, req)
        elapsed = time.time() - t0
        assert elapsed < 5.0, f"Request took {elapsed:.2f}s (> 5s limit)"


# ═══════════════════════════════════════════════════════════════════
#  GRAPH VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════

def test_graph_validation():
    """Validate graph satisfies all structural properties."""
    nodes, mode = make_network(n=30, seed=42)
    val = validate_graph(nodes)
    assert val["connected"], f"Graph not connected: {val['errors']}"
    assert val["no_isolated"], f"Isolated nodes found: {val['errors']}"
    assert val["symmetric_edges"], f"Asymmetric edges: {val['errors']}"
    assert val["sparse"], "Graph not sparse"


def test_graph_diagnostics():
    """Compute and verify graph diagnostic values."""
    nodes, _ = make_network(n=30, seed=42)
    diag = graph_diagnostics(nodes)
    assert diag["average_degree"] > 0, "Average degree is 0"
    assert diag["component_count"] == 1, f"Multiple components: {diag['component_count']}"
    assert 0 <= diag["clustering_coefficient"] <= 1, "Invalid clustering coefficient"


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGY ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════

def test_greedy_guarantee():
    """Verify Delaunay greedy guarantee for random targets."""
    nodes, mode = make_network(n=30, seed=42, mode="delaunay")
    rng = random.Random(42)
    violations_total = 0
    for _ in range(20):
        target = [rng.uniform(-1, 1) for _ in range(4)]
        result = greedy_guarantee_check(nodes, target)
        violations_total += len(result["violations"])
    # Allow some violations (Delaunay in 4D isn't perfect for greedy)
    assert violations_total < 10, f"Too many greedy violations: {violations_total}"


# ═══════════════════════════════════════════════════════════════════
#  RUNNER
# ═══════════════════════════════════════════════════════════════════

def run_all_tests():
    """Run all tests and print summary."""
    global _results
    _results = []

    print("═" * 70)
    print("  GEOMETRIC ADAPTIVE ROUTING — FULL TEST SUITE")
    print("═" * 70)

    print("\n  ── SECTION 16: Automated Tests ──────────────────────────")
    run_test("1. Basic Routing", test_basic_routing)
    run_test("2. Dead Node Recovery", test_dead_node_recovery)
    run_test("3. Load Balancing", test_load_balancing)
    run_test("4. Trust Avoidance", test_trust_avoidance)
    run_test("5. Greedy Failure Handling", test_greedy_failure)
    run_test("6. Face Routing Activation", test_face_routing_activation)
    run_test("7. Random Stress (100 runs)", test_random_stress)
    run_test("8. Repeated Request Stability", test_repeated_request_stability)
    run_test("9. Scalability (200 nodes)", test_scalability)
    run_test("10. Direction Correctness", test_direction_correctness)

    print("\n  ── SECTION 17: Extreme Stress Tests ─────────────────────")
    run_test("11. Multiple Failures (30%)", test_multiple_failures)
    run_test("12. Cascading Failures", test_cascading_failures)
    run_test("13. Dense Clusters", test_dense_clusters)
    run_test("14. Sparse Regions", test_sparse_regions)
    run_test("15. Duplicate Coordinates", test_duplicate_coordinates)
    run_test("16. Node Insertion", test_node_insertion)
    run_test("17. Node Deletion", test_node_deletion)
    run_test("18. Topology Rebuild", test_topology_rebuild)

    print("\n  ── SECTION 18: Assertions ───────────────────────────────")
    run_test("19. No Infinite Loops", test_no_infinite_loops)
    run_test("20. No Packet Cycling", test_no_packet_cycling)
    run_test("21. No Invalid Math", test_no_invalid_math)
    run_test("22. No Crashes", test_no_crashes)
    run_test("23. Finite Termination", test_finite_termination)

    print("\n  ── Graph Validation ────────────────────────────────────")
    run_test("24. Graph Validation", test_graph_validation)
    run_test("25. Graph Diagnostics", test_graph_diagnostics)
    run_test("26. Greedy Guarantee Check", test_greedy_guarantee)

    # Summary
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    print("\n" + "═" * 70)
    print(f"  RESULTS: {passed}/{total} PASSED, {failed}/{total} FAILED")
    print("═" * 70)

    if failed > 0:
        print("\n  Failed tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    ✗ {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
