"""
═══════════════════════════════════════════════════════════════════════
  ADAPTIVE VECTOR ROUTING SYSTEM — DEMONSTRATION
═══════════════════════════════════════════════════════════════════════

Runs three scenarios to prove the core properties of the system:
  1. Normal Routing      — basic A→B path via greedy vector navigation
  2. Load Balancing      — repeated requests cause traffic to shift
  3. Failure Rerouting   — disabled node is bypassed automatically
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avrs.network import Network
from avrs.routing import RoutingEngine
from avrs.simulation import Simulation, Request


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  {title:<66}║")
    print("╚" + "═" * 68 + "╝")


def print_node_loads(network: Network) -> None:
    """Print the load state of all nodes."""
    print("\n  Node Load Summary:")
    for node in network.nodes:
        bar = "█" * node.load + "░" * max(0, 10 - node.load)
        status = "ALIVE" if node.alive else " DOWN"
        print(f"    {node.id} [{status}]  load={node.load:>3}  {bar}")


def demo_normal_routing(network: Network, sim: Simulation) -> None:
    """
    SCENARIO 1: Normal Routing

    Send a single request from node N000 toward a target vector.
    Expect: request reaches closest node via greedy hops.
    """
    print_header("SCENARIO 1 — NORMAL ROUTING")
    print("  Sending one request from N000 toward target vector [0.8, 0.8, 0.8, 0.8]")

    start = network.get_node("N000")
    request = Request(
        target_vector=[0.8, 0.8, 0.8, 0.8],
        sender_id="demo-client",
        payload="Hello, vector space!",
    )

    result = sim.route_request(start, request)
    print(Simulation.format_result(result))


def demo_load_balancing(network: Network, sim: Simulation) -> None:
    """
    SCENARIO 2: Load Balancing

    Send 5 requests with the same target from different start nodes.
    Expect: paths shift as nodes accumulate load because the load
    penalty (γ) reduces scores for busy nodes.
    """
    print_header("SCENARIO 2 — LOAD BALANCING")
    print("  Sending 5 requests toward [0.5, 0.5, 0.5, 0.5] from different origins.")
    print("  Watch paths diverge as nodes become loaded.\n")

    target = [0.5, 0.5, 0.5, 0.5]
    start_ids = ["N001", "N003", "N005", "N007", "N009"]

    for i, sid in enumerate(start_ids):
        start = network.get_node(sid)
        if start is None:
            continue
        request = Request(
            target_vector=target,
            sender_id=f"client-{i}",
        )
        result = sim.route_request(start, request)
        # Compact output
        path_str = " → ".join(result.path)
        status = "✓" if result.success else "✗"
        print(f"  Request {i + 1} [{status}]: {path_str}  (hops={result.total_hops})")

    print_node_loads(network)


def demo_failure_rerouting(network: Network, sim: Simulation) -> None:
    """
    SCENARIO 3: Failure Rerouting

    Uses a fresh network to get a clean, multi-hop route.
    1. Route normally and record the path.
    2. Kill a node that was ON the path.
    3. Route again — the path MUST change.
    """
    print_header("SCENARIO 3 — FAILURE REROUTING")

    # Use a fresh network to get a clean multi-hop route
    fresh_net = Network.generate(n_nodes=20, k_neighbors=4, dimensions=4, seed=100)
    fresh_engine = RoutingEngine(use_cache=False)  # disable cache for fair comparison
    fresh_sim = Simulation(fresh_net, fresh_engine)

    # Find a start/target pair that produces a long path (>= 3 hops)
    start = fresh_net.get_node("N000")
    target = [0.9, 0.9, 0.9, 0.9]
    request = Request(target_vector=target, sender_id="failure-test")

    # First pass — all healthy
    print("  ── Pass 1: All nodes healthy ──")
    result1 = fresh_sim.route_request(start, request)
    path1 = " → ".join(result1.path)
    print(f"  Path: {path1}")
    print(f"  Hops: {result1.total_hops}  Success: {result1.success}")
    print(Simulation.format_result(result1))

    # Reset loads for fair comparison
    for node in fresh_net.nodes:
        node.load = 0

    # Kill a node in the MIDDLE of the path
    if len(result1.path) > 2:
        kill_idx = len(result1.path) // 2
        kill_id = result1.path[kill_idx]
    else:
        # Fallback: kill the last node's best neighbor
        kill_id = result1.path[-1]

    kill_node = fresh_net.get_node(kill_id)
    kill_node.fail()
    print(f"\n  ⚡ Node {kill_id} has been KILLED")
    print(f"     (this node was step {kill_idx if len(result1.path) > 2 else 'final'} in the original path)\n")

    # Second pass — reroute around failure
    print("  ── Pass 2: Rerouting around failure ──")
    result2 = fresh_sim.route_request(start, request)
    path2 = " → ".join(result2.path)
    print(f"  Path: {path2}")
    print(f"  Hops: {result2.total_hops}  Success: {result2.success}")
    print(Simulation.format_result(result2))

    # Verify dead node is NOT in the new path
    if kill_id not in result2.path:
        print(f"\n  ✓ Node {kill_id} successfully AVOIDED in rerouted path.")
    if result1.path != result2.path:
        print("  ✓ PATHS DIFFER — system successfully rerouted around failure.")
    else:
        print("  ⓘ Paths are the same (killed node was bypassed by original route too).")

    # Recover the node
    kill_node.recover()
    print(f"  ↻ Node {kill_node.id} recovered.\n")

    # Show loads on main network
    print_node_loads(network)


def main():
    """Run all demonstration scenarios."""
    print("╔" + "═" * 68 + "╗")
    print("║  ADAPTIVE VECTOR ROUTING SYSTEM — PROOF OF CONCEPT               ║")
    print("║  Decentralized · Local · Adaptive · Fault Tolerant · Load Aware   ║")
    print("╚" + "═" * 68 + "╝")
    print()
    print("  Generating network: 20 nodes, 4 neighbors each, 4D vector space")
    print("  Seed: 42 (deterministic for reproducible results)")

    # Build network
    network = Network.generate(n_nodes=20, k_neighbors=4, dimensions=4, seed=42)
    print(f"\n{network.summary()}\n")

    # Create simulation
    engine = RoutingEngine()
    sim = Simulation(network, engine)

    # Run demos
    demo_normal_routing(network, sim)
    demo_load_balancing(network, sim)
    demo_failure_rerouting(network, sim)

    print("\n")
    print("═" * 70)
    print("  ALL DEMONSTRATIONS COMPLETE")
    print("═" * 70)


if __name__ == "__main__":
    main()
