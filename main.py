"""
═══════════════════════════════════════════════════════════════════════
  GEOMETRIC ADAPTIVE DECENTRALIZED ROUTING SYSTEM
  Main Entry Point — Demonstration & Full Validation
═══════════════════════════════════════════════════════════════════════

Language: Python
Principle: Each node is a point in vector space. Routing moves toward
           the neighbor whose direction best aligns with the target.
           No global routing tables. All decisions are LOCAL and GREEDY.
"""

import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vector_math import euclidean_distance
from graph_builder import (
    Node, generate_nodes, build_knn_graph, build_delaunay_graph,
    validate_graph, graph_diagnostics,
)
from topology_engine import greedy_guarantee_check
from routing_engine import RoutingEngine
from simulator import Simulator, Request
from tests import run_all_tests


def header(title: str) -> None:
    """Print a formatted section header."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  {title:<66}║")
    print("╚" + "═" * 68 + "╝")


def demo_knn_mode():
    """Demonstrate Mode A — Nearest Neighbor Graph."""
    header("MODE A — K-NEAREST NEIGHBOR GRAPH (K=5)")
    nodes = generate_nodes(n_nodes=30, dimensions=4, seed=42)
    build_knn_graph(nodes, k=5)

    val = validate_graph(nodes)
    diag = graph_diagnostics(nodes)
    print(f"  Nodes: {len(nodes)}")
    print(f"  Connected: {val['connected']}")
    print(f"  Symmetric: {val['symmetric_edges']}")
    print(f"  Avg Degree: {diag['average_degree']}")
    print(f"  Clustering: {diag['clustering_coefficient']}")
    print(f"  Components: {diag['component_count']}")

    engine = RoutingEngine(use_cache=False, use_face_routing=False)
    sim = Simulator(nodes, engine, verbose=False)

    # Run 5 sample routes
    print("\n  Sample Routes:")
    rng = random.Random(42)
    for i in range(5):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-0.5, 0.5) for _ in range(4)]
        req = Request(target_vector=target, sender_id=f"demo-{i}")
        result = sim.route_request(start, req)
        status = "✓" if result.success else "✗"
        path_str = " → ".join(result.path)
        print(f"    {status} Route {i+1}: {path_str}  (hops={result.total_hops})")

    sim.print_metrics()


def demo_delaunay_mode():
    """Demonstrate Mode B — Delaunay Triangulation Graph."""
    header("MODE B — DELAUNAY TRIANGULATION GRAPH")
    nodes = generate_nodes(n_nodes=30, dimensions=4, seed=42)
    nodes, topo = build_delaunay_graph(nodes)

    val = validate_graph(nodes)
    diag = graph_diagnostics(nodes)
    print(f"  Topology: {topo}")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Connected: {val['connected']}")
    print(f"  Symmetric: {val['symmetric_edges']}")
    print(f"  Avg Degree: {diag['average_degree']}")
    print(f"  Clustering: {diag['clustering_coefficient']}")
    print(f"  Components: {diag['component_count']}")

    # Greedy guarantee check
    rng = random.Random(42)
    total_violations = 0
    for _ in range(10):
        target = [rng.uniform(-1, 1) for _ in range(4)]
        gg = greedy_guarantee_check(nodes, target)
        total_violations += len(gg["violations"])
    print(f"  Greedy Violations (10 targets): {total_violations}")

    engine = RoutingEngine(use_cache=True, use_face_routing=True)
    sim = Simulator(nodes, engine, verbose=False)

    # Run 5 sample routes with detailed logging
    print("\n  Sample Routes:")
    rng = random.Random(42)
    for i in range(5):
        start = nodes[rng.randint(0, len(nodes) - 1)]
        target = [rng.uniform(-0.5, 0.5) for _ in range(4)]
        req = Request(target_vector=target, sender_id=f"demo-{i}")
        result = sim.route_request(start, req)
        status = "✓" if result.success else "✗"
        path_str = " → ".join(result.path)
        print(f"    {status} Route {i+1}: {path_str}  (hops={result.total_hops})")

    sim.print_metrics()


def demo_detailed_routing():
    """Show one request with full per-hop logging."""
    header("DETAILED ROUTING LOG (Section 15)")
    nodes = generate_nodes(n_nodes=20, dimensions=4, seed=42)
    nodes, _ = build_delaunay_graph(nodes)
    engine = RoutingEngine(use_cache=False)
    sim = Simulator(nodes, engine, verbose=True)

    start = nodes[0]
    req = Request(
        target_vector=[0.5, 0.5, 0.5, 0.5],
        sender_id="demo-detail",
        payload="Hello, vector space!",
    )
    result = sim.route_request(start, req)
    print(Simulator.format_result(result))


def demo_failure_and_healing():
    """Demonstrate failure handling and self-healing."""
    header("FAILURE HANDLING & SELF-HEALING (Sections 11-12)")
    nodes = generate_nodes(n_nodes=25, dimensions=4, seed=42)
    nodes, _ = build_delaunay_graph(nodes)
    engine = RoutingEngine(use_cache=False)
    sim = Simulator(nodes, engine, verbose=False)

    target = [0.5, 0.5, 0.5, 0.5]
    req = Request(target_vector=target)

    # Normal route
    result1 = sim.route_request(nodes[0], req)
    path1 = " → ".join(result1.path)
    print(f"  Normal path: {path1}  (hops={result1.total_hops})")

    # Reset loads
    for n in nodes:
        n.reset_load()

    # Kill nodes in path
    from graph_builder import heal_around_failure
    killed = []
    for nid in result1.path[1:-1][:2]:
        n = sim.get_node(nid)
        if n:
            n.fail()
            heal_around_failure(n, nodes)
            killed.append(nid)
            print(f"  ⚡ Killed node {nid} — self-healing activated")

    # Re-route
    result2 = sim.route_request(nodes[0], req)
    path2 = " → ".join(result2.path)
    print(f"  Healed path: {path2}  (hops={result2.total_hops})")

    for nid in killed:
        assert nid not in result2.path, f"Dead node {nid} in path!"
    print("  ✓ Dead nodes successfully avoided")

    # Recover
    for n in nodes:
        n.recover()


def demo_trust_system():
    """Demonstrate trust-aware routing."""
    header("TRUST-AWARE ROUTING (Section 10)")
    nodes = generate_nodes(n_nodes=20, dimensions=4, seed=42)
    nodes, _ = build_delaunay_graph(nodes)
    engine = RoutingEngine(use_cache=False)
    sim = Simulator(nodes, engine, verbose=False)

    target = [0.5, 0.5, 0.5, 0.5]
    req = Request(target_vector=target)

    result1 = sim.route_request(nodes[0], req)
    print(f"  Normal path: {' → '.join(result1.path)}")

    for n in nodes:
        n.reset_load()

    # Attack trust on intermediate nodes
    for nid in result1.path[1:-1]:
        n = sim.get_node(nid)
        if n:
            n.reduce_trust(0.9)
            print(f"  ⚠ Attacked trust on {nid} → trust={n.trust:.2f}")

    result2 = sim.route_request(nodes[0], req)
    print(f"  Low-trust path: {' → '.join(result2.path)}")

    if result1.path != result2.path:
        print("  ✓ Path changed — system avoided low-trust nodes")
    else:
        print("  ⓘ Path unchanged (no better alternative available)")

    for n in nodes:
        n.restore_trust()


def main():
    """Run complete demonstration and test suite."""
    print("╔" + "═" * 68 + "╗")
    print("║  GEOMETRIC ADAPTIVE DECENTRALIZED ROUTING SYSTEM                 ║")
    print("║  Local · Greedy · Adaptive · Fault Tolerant · Trust Aware        ║")
    print("║  No global tables · No central control · Pure vector navigation  ║")
    print("╚" + "═" * 68 + "╝")

    # Demonstrations
    demo_knn_mode()
    demo_delaunay_mode()
    demo_detailed_routing()
    demo_failure_and_healing()
    demo_trust_system()

    # Full Test Suite
    header("RUNNING FULL TEST SUITE (Sections 16-18)")
    all_pass = run_all_tests()

    # Final verdict
    print("\n")
    print("╔" + "═" * 68 + "╗")
    if all_pass:
        print("║  ✓ ALL TESTS PASSED — SYSTEM IS CORRECT                          ║")
    else:
        print("║  ✗ SOME TESTS FAILED — SEE ABOVE FOR DETAILS                     ║")
    print("╚" + "═" * 68 + "╝")

    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
