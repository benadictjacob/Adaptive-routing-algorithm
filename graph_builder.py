"""
═══════════════════════════════════════════════════════════════════════
  GRAPH BUILDER MODULE
  Network topology construction and validation.
═══════════════════════════════════════════════════════════════════════

Supports two topology modes:
  MODE A — K-Nearest Neighbor Graph (baseline)
  MODE B — Delaunay Triangulation Graph (advanced, with fallback)

Also provides graph validation, diagnostics, self-healing, and
dynamic node insertion/deletion.
"""

import random
import math
from typing import List, Optional, Dict, Tuple, Set
from collections import deque

from avrs.node import Node
from avrs.math_utils import Vector, euclidean_distance


# ═══════════════════════════════════════════════════════════════════
#  GRAPH CONSTRUCTION (Section 3)
# ═══════════════════════════════════════════════════════════════════
#  GRAPH CONSTRUCTION (Section 2)
# ═══════════════════════════════════════════════════════════════════

def generate_nodes(
    n_nodes: int,
    dimensions: int = 4,
    seed: Optional[int] = None,
    coord_range: Tuple[float, float] = (-1.0, 1.0),
) -> List[Node]:
    """Create n_nodes with random vectors in the given coordinate range."""
    if seed is not None:
        random.seed(seed)
    nodes = []
    for i in range(n_nodes):
        vec = [random.uniform(coord_range[0], coord_range[1]) for _ in range(dimensions)]
        nodes.append(Node(node_id=f"N{i:03d}", vector=vec))
    return nodes


def build_knn_graph(nodes: List[Node], k: int = 5) -> List[Node]:
    """
    MODE A — Nearest Neighbor Graph.
    Connect each node to K nearest neighbors. Edges are symmetric.
    """
    for node in nodes:
        distances = []
        for other in nodes:
            if other.id == node.id:
                continue
            dist = euclidean_distance(list(node.vector), list(other.vector))
            distances.append((dist, other))
        distances.sort(key=lambda x: x[0])
        for _, neighbor in distances[:k]:
            node.add_neighbor(neighbor)
            neighbor.add_neighbor(node)  # symmetric
    return nodes


def build_delaunay_graph(nodes: List[Node]) -> Tuple[List[Node], str]:
    """
    MODE B — Delaunay Triangulation Graph.
    Returns (nodes, topology_mode) where topology_mode is "delaunay" or "knn" (fallback).

    Falls back to KNN if:
      - scipy not available
      - fewer than dim+2 nodes
      - degenerate point configuration
    """
    try:
        import numpy as np
        from scipy.spatial import Delaunay
    except ImportError:
        print("  [WARN] scipy not available — falling back to KNN")
        build_knn_graph(nodes, k=5)
        return nodes, "knn"

    if len(nodes) < 2:
        build_knn_graph(nodes, k=min(5, len(nodes) - 1))
        return nodes, "knn"

    dim = len(nodes[0].vector)
    if len(nodes) < dim + 2:
        print(f"  [WARN] Need at least {dim + 2} nodes for Delaunay in {dim}D — falling back to KNN")
        build_knn_graph(nodes, k=min(5, len(nodes) - 1))
        return nodes, "knn"

    points = np.array([list(n.vector) for n in nodes])

    try:
        tri = Delaunay(points)
    except Exception as e:
        print(f"  [WARN] Delaunay failed ({e}) — falling back to KNN")
        build_knn_graph(nodes, k=5)
        return nodes, "knn"

    # Extract unique edges from all simplices
    edge_set: Set[Tuple[int, int]] = set()
    for simplex in tri.simplices:
        for i in range(len(simplex)):
            for j in range(i + 1, len(simplex)):
                a, b = simplex[i], simplex[j]
                edge_set.add((min(a, b), max(a, b)))

    # Create bidirectional links
    for a_idx, b_idx in edge_set:
        nodes[a_idx].add_neighbor(nodes[b_idx])
        nodes[b_idx].add_neighbor(nodes[a_idx])

    return nodes, "delaunay"


# ═══════════════════════════════════════════════════════════════════
#  GRAPH VALIDATION (Section 3)
# ═══════════════════════════════════════════════════════════════════

def validate_graph(nodes: List[Node]) -> Dict[str, any]:
    """
    Validate graph properties:
      - connected topology
      - no isolated nodes
      - symmetric edges
      - sparse connectivity
    Returns a dict with validation results.
    """
    results = {
        "connected": False,
        "no_isolated": True,
        "symmetric_edges": True,
        "sparse": True,
        "errors": [],
    }

    if not nodes:
        results["errors"].append("Empty node list")
        return results

    # Check isolated nodes
    for node in nodes:
        if len(node.neighbors) == 0:
            results["no_isolated"] = False
            results["errors"].append(f"Isolated node: {node.id}")

    # Check symmetry: if A→B then B→A
    for node in nodes:
        for neighbor in node.neighbors:
            if node not in neighbor.neighbors:
                results["symmetric_edges"] = False
                results["errors"].append(
                    f"Asymmetric edge: {node.id}→{neighbor.id} but not reverse"
                )

    # Check connectivity via BFS (note: BFS is for validation only, NOT for routing)
    alive_nodes = [n for n in nodes if n.alive]
    if alive_nodes:
        visited = set()
        queue = deque([alive_nodes[0]])
        visited.add(alive_nodes[0].id)
        while queue:
            current = queue.popleft()
            for nb in current.neighbors:
                if nb.id not in visited and nb.alive:
                    visited.add(nb.id)
                    queue.append(nb)
        results["connected"] = len(visited) == len(alive_nodes)
        if not results["connected"]:
            results["errors"].append(
                f"Graph not connected: {len(visited)}/{len(alive_nodes)} reachable"
            )

    # Sparse check: average degree < n (relaxed for high-D Delaunay)
    avg_deg = sum(len(n.neighbors) for n in nodes) / len(nodes)
    results["sparse"] = avg_deg < len(nodes)

    return results


def graph_diagnostics(nodes: List[Node]) -> Dict[str, float]:
    """
    Compute topology diagnostics:
      - average_degree
      - clustering_coefficient
      - component_count
    """
    if not nodes:
        return {"average_degree": 0, "clustering_coefficient": 0, "component_count": 0}

    # Average degree
    degrees = [len(n.neighbors) for n in nodes]
    avg_degree = sum(degrees) / len(nodes)

    # Clustering coefficient (proportion of neighbor pairs that are also connected)
    cc_values = []
    for node in nodes:
        k = len(node.neighbors)
        if k < 2:
            cc_values.append(0.0)
            continue
        neighbor_ids = {n.id for n in node.neighbors}
        triangles = 0
        for i, ni in enumerate(node.neighbors):
            for nj in node.neighbors[i + 1:]:
                if nj.id in {nb.id for nb in ni.neighbors}:
                    triangles += 1
        possible = k * (k - 1) / 2
        cc_values.append(triangles / possible if possible > 0 else 0.0)
    clustering_coefficient = sum(cc_values) / len(cc_values)

    # Component count
    visited: Set[str] = set()
    components = 0
    for node in nodes:
        if node.id not in visited:
            components += 1
            queue = deque([node])
            visited.add(node.id)
            while queue:
                curr = queue.popleft()
                for nb in curr.neighbors:
                    if nb.id not in visited:
                        visited.add(nb.id)
                        queue.append(nb)

    return {
        "average_degree": round(avg_degree, 2),
        "clustering_coefficient": round(clustering_coefficient, 4),
        "component_count": components,
    }


# ═══════════════════════════════════════════════════════════════════
#  SELF-HEALING NETWORK (Section 12)
# ═══════════════════════════════════════════════════════════════════

def heal_around_failure(failed_node: Node, all_nodes: List[Node], k: int = 3) -> int:
    """
    When a node fails, its neighbors locally repair the topology.
    Each neighbor of the failed node connects to the k nearest OTHER
    neighbors of the failed node that it wasn't already connected to.

    Returns number of new edges created.
    """
    new_edges = 0
    neighbors_of_failed = [n for n in failed_node.neighbors if n.alive]

    for node in neighbors_of_failed:
        # Find other alive neighbors of the failed node
        candidates = [
            n for n in neighbors_of_failed
            if n.id != node.id and n not in node.neighbors
        ]
        # Sort by distance and connect to closest k
        candidates.sort(
            key=lambda c: euclidean_distance(list(node.vector), list(c.vector))
        )
        for candidate in candidates[:k]:
            node.add_neighbor(candidate)
            candidate.add_neighbor(node)
            new_edges += 1

    return new_edges


def insert_node(new_node: Node, all_nodes: List[Node], k: int = 5) -> None:
    """
    Insert a new node and connect it to k nearest existing alive nodes.
    """
    candidates = [
        n for n in all_nodes if n.alive and n.id != new_node.id
    ]
    candidates.sort(
        key=lambda c: euclidean_distance(list(new_node.vector), list(c.vector))
    )
    for neighbor in candidates[:k]:
        new_node.add_neighbor(neighbor)
        neighbor.add_neighbor(new_node)
    all_nodes.append(new_node)


def remove_node(node: Node, all_nodes: List[Node], heal: bool = True) -> None:
    """
    Remove a node: mark as failed, optionally heal the neighborhood.
    """
    node.fail()
    if heal:
        heal_around_failure(node, all_nodes)


def rebuild_topology(nodes: List[Node], mode: str = "knn", k: int = 5) -> str:
    """
    Full topology rebuild — clear all edges and reconstruct.
    Only considers alive nodes.
    """
    # Clear all neighbor lists
    for node in nodes:
        node.neighbors = []

    alive_nodes = [n for n in nodes if n.alive]

    if mode == "delaunay":
        _, actual_mode = build_delaunay_graph(alive_nodes)
        return actual_mode
    else:
        build_knn_graph(alive_nodes, k=k)
        return "knn"
