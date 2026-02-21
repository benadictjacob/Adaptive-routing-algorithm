"""
Network graph generation for the Adaptive Vector Routing System.

Supports two topology modes:
  1. Delaunay Triangulation (default) — guarantees greedy routing success
     by providing full angular coverage around every node.
  2. K-Nearest Neighbors (legacy) — simple proximity-based connections.

Why Delaunay?
  In a Delaunay tessellation, for any target point in the space, there is
  always at least one neighbor that is closer to that target than the
  current node. This eliminates local minima in greedy routing.
"""

import random
from typing import List, Optional

import numpy as np
from scipy.spatial import Delaunay

from avrs.node import Node
from avrs.math_utils import euclidean_distance, Vector


class Network:
    """
    A decentralized network of nodes in vector space.

    Default generation uses Delaunay triangulation which guarantees
    that greedy geographic routing will always find a path to the
    closest node to any target vector.
    """

    def __init__(self):
        self.nodes: List[Node] = []
        self._node_map: dict[str, Node] = {}
        self.topology: str = "delaunay"

    # ── Delaunay Construction (Default) ───────────────────────────

    @classmethod
    def generate(
        cls,
        n_nodes: int = 20,
        dimensions: int = 4,
        seed: Optional[int] = None,
        topology: str = "delaunay",
        k_neighbors: int = 4,
    ) -> "Network":
        """
        Build a network of nodes in vector space.

        Args:
            n_nodes:      Number of nodes to create.
            dimensions:   Dimensionality of each node's vector.
            seed:         Optional random seed for reproducibility.
            topology:     "delaunay" (default) or "knn".
            k_neighbors:  Only used when topology="knn".

        Returns:
            A fully connected Network instance.
        """
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        net = cls()
        net.topology = topology

        # Step 1: create nodes with random vectors
        vectors = []
        for i in range(n_nodes):
            vec = [random.uniform(-1.0, 1.0) for _ in range(dimensions)]
            node = Node(node_id=f"N{i:03d}", vector=vec)
            net.nodes.append(node)
            net._node_map[node.id] = node
            vectors.append(vec)

        # Step 2: connect nodes based on topology
        if topology == "delaunay":
            net._connect_delaunay(vectors)
        elif topology == "knn":
            net._connect_knn(k_neighbors)
        elif topology == "hybrid":
            net._connect_hybrid(vectors, k_neighbors)
        else:
            net._connect_delaunay(vectors)

        return net

    def _connect_delaunay(self, vectors: list) -> None:
        """
        Connect nodes using Delaunay triangulation.

        The Delaunay tessellation in N dimensions creates simplices
        (triangles in 2D, tetrahedra in 3D, etc.). We extract all
        edges from these simplices to form the routing graph.

        Key property: For any point P in the space, at least one
        Delaunay neighbor of any node is closer to P than the node
        itself. This guarantees greedy routing succeeds.
        """
        points = np.array(vectors)
        tri = Delaunay(points)

        # Extract unique edges from all simplices
        edge_set = set()
        for simplex in tri.simplices:
            # A simplex in 4D has 5 vertices → 10 edges
            for i in range(len(simplex)):
                for j in range(i + 1, len(simplex)):
                    a, b = simplex[i], simplex[j]
                    edge_set.add((min(a, b), max(a, b)))

        # Create bidirectional neighbor links
        for a_idx, b_idx in edge_set:
            node_a = self.nodes[a_idx]
            node_b = self.nodes[b_idx]
            node_a.add_neighbor(node_b)
            node_b.add_neighbor(node_a)

    def _connect_knn(self, k: int) -> None:
        """Connect each node to its K nearest neighbors (legacy mode)."""
        for node in self.nodes:
            distances = []
            for other in self.nodes:
                if other.id == node.id:
                    continue
                dist = euclidean_distance(node.vector, other.vector)
                distances.append((dist, other))

            distances.sort(key=lambda x: x[0])
            nearest = distances[:k]

            for _, neighbor in nearest:
                node.add_neighbor(neighbor)
                neighbor.add_neighbor(node)

    def _connect_hybrid(self, vectors: list, k: int) -> None:
        """
        Connect nodes using BOTH KNN and Delaunay.
        KNN provides the 'normal' efficient mesh, and Delaunay
        provides the 'worst case' routing guarantee.
        """
        self._connect_delaunay(vectors)
        self._connect_knn(k)

    # ── Lookup ────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[Node]:
        """Retrieve a node by its ID."""
        return self._node_map.get(node_id)

    def find_closest_node(self, target: Vector) -> Node:
        """Find the node whose vector is closest to the target vector."""
        best = None
        best_dist = float("inf")
        for node in self.nodes:
            if not node.alive:
                continue
            d = euclidean_distance(node.vector, target)
            if d < best_dist:
                best_dist = d
                best = node
        return best

    # ── Display ───────────────────────────────────────────────────

    def summary(self) -> str:
        """Return a compact network summary string."""
        total_edges = sum(len(n.neighbors) for n in self.nodes) // 2
        avg_neighbors = sum(len(n.neighbors) for n in self.nodes) / len(self.nodes)
        lines = [
            f"Network: {len(self.nodes)} nodes, {total_edges} edges "
            f"(topology={self.topology}, avg neighbors={avg_neighbors:.1f})"
        ]
        for node in self.nodes:
            neighbor_ids = [n.id for n in node.neighbors]
            lines.append(f"  {node.id} → {len(neighbor_ids)} neighbors: {neighbor_ids}")
        return "\n".join(lines)
