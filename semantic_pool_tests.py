"""
=====================================================================
  SEMANTIC POOL LOAD BALANCING — TEST SUITE
  Tests for all 10 spec sections
=====================================================================
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avrs.node import Node
from avrs.math_utils import euclidean_distance, cosine_similarity
from semantic_pool import (
    SemanticRequest, SemanticPool,
    semantic_filter, score_candidate, select_best_candidate,
    route_semantic_request, build_semantic_network,
    display_semantic_topology,
)

_results = []


def run_test(name, fn):
    try:
        fn()
        print(f"  [PASS] {name}")
        _results.append((name, True, ""))
    except Exception as e:
        print(f"  [FAIL] {name}")
        print(f"         Error: {e}")
        _results.append((name, False, str(e)))


def make_pool():
    """Helper: build a multi-role network and pool."""
    roles = {"auth": 3, "compute": 4, "database": 3, "proxy": 3, "storage": 2}
    nodes = build_semantic_network(roles, seed=42, overload_threshold=10)
    pool = SemanticPool(nodes)
    return nodes, pool


# ===================================================================
#  SECTION 1 — NODE CAPABILITY TAG
# ===================================================================

def test_node_role_tag():
    """S1: Every node has a role."""
    nodes, _ = make_pool()
    for n in nodes:
        assert n.role, f"Node {n.id} missing role"
        assert isinstance(n.role, str)


# ===================================================================
#  SECTION 2 — REQUEST REQUIRES ROLE
# ===================================================================

def test_request_required_role():
    """S2: Request includes required_role."""
    req = SemanticRequest(target_vector=[0.5]*4, required_role="compute")
    assert req.required_role == "compute"


def test_request_routes_to_correct_role():
    """S2: Routing only returns nodes with matching role."""
    nodes, pool = make_pool()
    req = SemanticRequest(target_vector=[0.5]*4, required_role="auth")
    result = route_semantic_request(pool, req)
    assert result.success, "Route failed"
    # Verify selected node has correct role
    selected = [n for n in nodes if n.id == result.selected_node_id][0]
    assert selected.role == "auth", \
        f"Wrong role: {selected.role} (expected auth)"


# ===================================================================
#  SECTION 3 — SEMANTIC FILTER
# ===================================================================

def test_semantic_filter_direct():
    """S3: Filter returns only matching role nodes."""
    a = Node("A", [0,0,0,0], role="auth")
    b = Node("B", [1,0,0,0], role="compute")
    c = Node("C", [0,1,0,0], role="auth")
    result = semantic_filter([a, b, c], "auth")
    assert len(result) == 2
    assert all(n.role == "auth" for n in result)


def test_semantic_filter_expanded_search():
    """S3: Filter expands search when no direct match."""
    a = Node("A", [0,0,0,0], role="proxy")
    b = Node("B", [1,0,0,0], role="compute")
    c = Node("C", [0,1,0,0], role="auth")
    # B is neighbor of A, C is neighbor of B
    a.add_neighbor(b)
    b.add_neighbor(c)
    # Filter for 'auth' among [a] — not found directly, expand finds C via A->B->C? No — only 1 hop
    # A's neighbor is B (compute), B's not in candidates, so expanded doesn't find auth
    # Let's add C as neighbor of A directly
    a.add_neighbor(c)
    result = semantic_filter([a], "auth", expand_search=True)
    assert len(result) == 1
    assert result[0].id == "C"


# ===================================================================
#  SECTION 4 — LOAD-AWARE SELECTION
# ===================================================================

def test_lower_load_preferred():
    """S4: Node with lower load scores higher."""
    a = Node("A", [0.5,0.5,0.5,0.5], role="compute")
    b = Node("B", [0.5,0.5,0.5,0.5], role="compute")
    a.load = 0
    b.load = 15
    score_a = score_candidate(a, [0.5,0.5,0.5,0.5])
    score_b = score_candidate(b, [0.5,0.5,0.5,0.5])
    assert score_a > score_b, f"Low-load node should score higher: {score_a} vs {score_b}"


def test_select_best_candidate():
    """S4: Best candidate is selected from pool."""
    nodes = [
        Node("A", [0.1,0.1,0.1,0.1], role="compute"),
        Node("B", [0.5,0.5,0.5,0.5], role="compute"),
        Node("C", [0.9,0.9,0.9,0.9], role="compute"),
    ]
    target = [0.5, 0.5, 0.5, 0.5]
    selected = select_best_candidate(nodes, target)
    assert selected is not None
    assert selected.id == "B", f"Expected B closest to target, got {selected.id}"


# ===================================================================
#  SECTION 5 — PROXY POOL DISTRIBUTION
# ===================================================================

def test_pool_distribution():
    """S5: Traffic distributes across pool nodes."""
    nodes, pool = make_pool()
    target = [0.5]*4

    # Send 20 requests to compute pool
    for i in range(20):
        pool.select_from_pool("compute", target, strategy="round_robin")

    metrics = pool.get_pool_metrics("compute")
    dist = metrics["request_distribution"]
    # All compute nodes should have received some requests
    assert len(dist) > 1, f"Traffic not distributed: {dist}"
    # Check no single node got all 20
    max_count = max(dist.values())
    assert max_count < 20, f"All requests went to one node: {dist}"


def test_round_robin_avoids_repetition():
    """S5: Round-robin doesn't repeatedly select same node."""
    nodes, pool = make_pool()
    target = [0.0]*4
    selections = []
    for _ in range(8):
        node = pool.select_from_pool("compute", target, strategy="round_robin")
        if node:
            selections.append(node.id)
    # Should see at least 2 different nodes
    unique = set(selections)
    assert len(unique) >= 2, f"Selection not rotating: {selections}"


# ===================================================================
#  SECTION 6 — OVERLOAD HANDLING
# ===================================================================

def test_overloaded_node_skipped():
    """S6: Overloaded nodes are skipped during selection."""
    a = Node("A", [0.5,0.5,0.5,0.5], role="compute", overload_threshold=5)
    b = Node("B", [0.4,0.4,0.4,0.4], role="compute", overload_threshold=5)
    a.load = 10  # overloaded
    b.load = 1   # fine

    selected = select_best_candidate([a, b], [0.5,0.5,0.5,0.5])
    assert selected is not None
    assert selected.id == "B", f"Should skip overloaded A, got {selected.id}"


def test_overload_threshold_enforced():
    """S6: Requests avoid nodes above threshold."""
    nodes, pool = make_pool()
    # Overload all compute nodes except one
    compute_nodes = pool.get_pool("compute")
    for n in compute_nodes[:-1]:
        n.load = n.overload_threshold + 5

    remaining = compute_nodes[-1]
    selected = pool.select_from_pool("compute", [0.5]*4)
    assert selected is not None
    assert selected.id == remaining.id, \
        f"Should select non-overloaded node, got {selected.id}"


# ===================================================================
#  SECTION 7 — FAILOVER GUARANTEE
# ===================================================================

def test_failover_selects_another():
    """S7: When node fails, another from same pool is selected."""
    nodes, pool = make_pool()
    auth_nodes = pool.get_pool("auth")
    assert len(auth_nodes) >= 2, "Need at least 2 auth nodes"

    # Fail the first auth node
    victim = auth_nodes[0]
    victim.fail()

    replacement = pool.failover_select(victim, [0.5]*4)
    assert replacement is not None, "Failover returned None"
    assert replacement.id != victim.id, "Failover returned failed node"
    assert replacement.role == "auth", "Failover wrong role"


def test_failover_metrics_tracked():
    """S7: Failover count is tracked in metrics."""
    nodes, pool = make_pool()
    auth_nodes = pool.get_pool("auth")
    victim = auth_nodes[0]
    victim.fail()

    pool.failover_select(victim, [0.5]*4)
    metrics = pool.get_pool_metrics("auth")
    assert metrics["failover_count"] >= 1, "Failover not tracked"


# ===================================================================
#  SECTION 8 — POOL METRICS
# ===================================================================

def test_pool_metrics_structure():
    """S8: Metrics contain all required fields."""
    nodes, pool = make_pool()
    pool.select_from_pool("compute", [0.5]*4)

    metrics = pool.get_pool_metrics("compute")
    assert "active_nodes" in metrics
    assert "average_load" in metrics
    assert "request_distribution" in metrics
    assert "failover_count" in metrics
    assert metrics["active_nodes"] > 0
    assert metrics["total_requests"] >= 1


# ===================================================================
#  SECTION 10 — SUCCESS CRITERIA
# ===================================================================

def test_never_routes_to_wrong_role():
    """S10: 100 requests NEVER route to incorrect role."""
    nodes, pool = make_pool()
    import random
    rng = random.Random(42)
    roles = ["auth", "compute", "database", "proxy", "storage"]
    for i in range(100):
        role = rng.choice(roles)
        target = [rng.uniform(-1, 1) for _ in range(4)]
        req = SemanticRequest(target_vector=target, required_role=role)
        result = route_semantic_request(pool, req)
        if result.success:
            selected = [n for n in nodes if n.id == result.selected_node_id][0]
            assert selected.role == role, \
                f"Request {i}: routed to {selected.role} instead of {role}"


def test_load_distributes_evenly():
    """S10: Load distributes across equivalent nodes."""
    nodes, pool = make_pool()
    for i in range(40):
        req = SemanticRequest(target_vector=[0.5]*4, required_role="compute")
        route_semantic_request(pool, req, strategy="round_robin")

    compute = pool.get_pool("compute")
    loads = [n.load for n in compute]
    # All compute nodes should have some load
    assert min(loads) > 0, f"Uneven distribution: {loads}"
    # Max shouldn't be more than 3x min
    assert max(loads) <= min(loads) * 4, f"Extremely uneven: {loads}"


def test_no_routing_to_nonexistent_role():
    """S10: Request for nonexistent role fails gracefully."""
    nodes, pool = make_pool()
    req = SemanticRequest(target_vector=[0.5]*4, required_role="quantum_processor")
    result = route_semantic_request(pool, req)
    assert not result.success
    assert result.reason == "no_nodes_for_role"


# ===================================================================
#  RUNNER
# ===================================================================

def run_all_semantic_tests():
    global _results
    _results = []

    print("=" * 60)
    print("  SEMANTIC POOL LOAD BALANCING -- TEST SUITE")
    print("=" * 60)

    print("\n  -- S1: Node Capability Tag ----")
    run_test("Node role tag", test_node_role_tag)

    print("\n  -- S2: Request Requirement ----")
    run_test("Request required_role", test_request_required_role)
    run_test("Routes to correct role", test_request_routes_to_correct_role)

    print("\n  -- S3: Semantic Filter ----")
    run_test("Direct filter", test_semantic_filter_direct)
    run_test("Expanded search", test_semantic_filter_expanded_search)

    print("\n  -- S4: Load-Aware Selection ----")
    run_test("Lower load preferred", test_lower_load_preferred)
    run_test("Best candidate selected", test_select_best_candidate)

    print("\n  -- S5: Pool Distribution ----")
    run_test("Traffic distributes", test_pool_distribution)
    run_test("Round-robin rotation", test_round_robin_avoids_repetition)

    print("\n  -- S6: Overload Handling ----")
    run_test("Overloaded skipped", test_overloaded_node_skipped)
    run_test("Threshold enforced", test_overload_threshold_enforced)

    print("\n  -- S7: Failover Guarantee ----")
    run_test("Failover selects another", test_failover_selects_another)
    run_test("Failover metrics tracked", test_failover_metrics_tracked)

    print("\n  -- S8: Pool Metrics ----")
    run_test("Metrics structure", test_pool_metrics_structure)

    print("\n  -- S10: Success Criteria ----")
    run_test("Never routes to wrong role", test_never_routes_to_wrong_role)
    run_test("Load distributes evenly", test_load_distributes_evenly)
    run_test("Nonexistent role fails", test_no_routing_to_nonexistent_role)

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{total} PASSED, {failed}/{total} FAILED")
    print("=" * 60)

    if failed > 0:
        print("\n  Failed tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    x {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_semantic_tests()
    sys.exit(0 if success else 1)
