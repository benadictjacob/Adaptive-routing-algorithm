"""
Unit tests for the Adaptive Vector Routing System.

Covers:
  - Math utilities (cosine similarity, distance, vector ops)
  - Node behavior (load, failure, neighbors, cache)
  - Network generation (K-NN connectivity)
  - Routing engine (scoring, termination, next-hop)
  - Simulation (end-to-end routing, load behavior, failure handling)
"""

import sys
import os
import unittest
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avrs.math_utils import (
    cosine_similarity,
    euclidean_distance,
    dot_product,
    magnitude,
    vector_subtract,
)
from avrs.node import Node
from avrs.network import Network
from avrs.routing import RoutingEngine
from avrs.simulation import Simulation, Request


# ═══════════════════════════════════════════════════════════════════
#  MATH UTILS TESTS
# ═══════════════════════════════════════════════════════════════════

class TestMathUtils(unittest.TestCase):
    """Tests for geometric math utilities."""

    def test_cosine_identical_vectors(self):
        """Identical vectors should have cosine similarity of 1."""
        self.assertAlmostEqual(cosine_similarity([1, 2, 3], [1, 2, 3]), 1.0, places=5)

    def test_cosine_opposite_vectors(self):
        """Opposite vectors should have cosine similarity of -1."""
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), -1.0, places=5)

    def test_cosine_orthogonal_vectors(self):
        """Orthogonal vectors should have cosine similarity of 0."""
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0, places=5)

    def test_cosine_zero_vector(self):
        """Zero vector should return 0 (not crash)."""
        self.assertEqual(cosine_similarity([0, 0], [1, 2]), 0.0)

    def test_euclidean_distance_same_point(self):
        """Distance from a point to itself should be 0."""
        self.assertEqual(euclidean_distance([1, 2, 3], [1, 2, 3]), 0.0)

    def test_euclidean_distance_known(self):
        """Test with known values: distance([0,0], [3,4]) = 5."""
        self.assertAlmostEqual(euclidean_distance([0, 0], [3, 4]), 5.0, places=5)

    def test_dot_product(self):
        """dot([1,2,3], [4,5,6]) = 4+10+18 = 32."""
        self.assertEqual(dot_product([1, 2, 3], [4, 5, 6]), 32)

    def test_magnitude(self):
        """magnitude([3,4]) = 5."""
        self.assertAlmostEqual(magnitude([3, 4]), 5.0, places=5)

    def test_vector_subtract(self):
        """[5,3,1] - [1,2,3] = [4,1,-2]."""
        self.assertEqual(vector_subtract([5, 3, 1], [1, 2, 3]), [4, 1, -2])

    def test_dimension_mismatch_raises(self):
        """Mismatched dimensions should raise ValueError."""
        with self.assertRaises(ValueError):
            cosine_similarity([1, 2], [1, 2, 3])
        with self.assertRaises(ValueError):
            euclidean_distance([1], [1, 2])


# ═══════════════════════════════════════════════════════════════════
#  NODE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNode(unittest.TestCase):
    """Tests for the Node data structure."""

    def setUp(self):
        self.node = Node("A", [1.0, 0.0])

    def test_initial_state(self):
        """New node should be alive with zero load."""
        self.assertTrue(self.node.alive)
        self.assertEqual(self.node.load, 0)
        self.assertEqual(self.node.trust, 1.0)

    def test_increment_load(self):
        """Load should increase by 1 each call."""
        self.node.increment_load()
        self.node.increment_load()
        self.assertEqual(self.node.load, 2)

    def test_fail_and_recover(self):
        """Failing a node sets alive=False; recovering restores it."""
        self.node.fail()
        self.assertFalse(self.node.alive)
        self.node.recover()
        self.assertTrue(self.node.alive)

    def test_add_neighbor(self):
        """Neighbors should be added without duplicates."""
        b = Node("B", [0.0, 1.0])
        self.node.add_neighbor(b)
        self.node.add_neighbor(b)  # duplicate
        self.assertEqual(len(self.node.neighbors), 1)

    def test_get_alive_neighbors(self):
        """Dead neighbors should be filtered out."""
        b = Node("B", [0.0, 1.0])
        c = Node("C", [1.0, 1.0])
        self.node.add_neighbor(b)
        self.node.add_neighbor(c)
        c.fail()
        alive = self.node.get_alive_neighbors()
        self.assertEqual(len(alive), 1)
        self.assertEqual(alive[0].id, "B")

    def test_route_cache(self):
        """Cache should store and retrieve next-hop IDs."""
        key = (0.5, 0.5)
        self.node.cache_route(key, "B")
        self.assertEqual(self.node.get_cached_route(key), "B")
        self.assertIsNone(self.node.get_cached_route((0.9, 0.9)))


# ═══════════════════════════════════════════════════════════════════
#  NETWORK TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNetwork(unittest.TestCase):
    """Tests for network graph generation."""

    def setUp(self):
        self.net = Network.generate(n_nodes=10, k_neighbors=3, dimensions=4, seed=99)

    def test_node_count(self):
        """Network should have the requested number of nodes."""
        self.assertEqual(len(self.net.nodes), 10)

    def test_minimum_connectivity(self):
        """Each node should have at least K neighbors (bidirectional may add more)."""
        for node in self.net.nodes:
            self.assertGreaterEqual(len(node.neighbors), 3)

    def test_no_self_neighbor(self):
        """No node should be its own neighbor."""
        for node in self.net.nodes:
            neighbor_ids = [n.id for n in node.neighbors]
            self.assertNotIn(node.id, neighbor_ids)

    def test_get_node(self):
        """Lookup by ID should work."""
        node = self.net.get_node("N000")
        self.assertIsNotNone(node)
        self.assertEqual(node.id, "N000")

    def test_find_closest_node(self):
        """find_closest_node should return the nearest alive node."""
        closest = self.net.find_closest_node([0.0, 0.0, 0.0, 0.0])
        self.assertIsNotNone(closest)

    def test_deterministic_seed(self):
        """Same seed should produce same network."""
        net2 = Network.generate(n_nodes=10, k_neighbors=3, dimensions=4, seed=99)
        for n1, n2 in zip(self.net.nodes, net2.nodes):
            self.assertEqual(n1.id, n2.id)
            self.assertEqual(n1.vector, n2.vector)


# ═══════════════════════════════════════════════════════════════════
#  ROUTING ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestRoutingEngine(unittest.TestCase):
    """Tests for the routing decision function."""

    def setUp(self):
        self.engine = RoutingEngine()
        # Build a small manual network
        #   A at origin, B toward target, C away from target
        self.a = Node("A", [0.0, 0.0])
        self.b = Node("B", [0.8, 0.8])  # closer to target
        self.c = Node("C", [-0.5, -0.5])  # away from target
        self.a.add_neighbor(self.b)
        self.a.add_neighbor(self.c)
        self.target = [1.0, 1.0]

    def test_better_neighbor_scores_higher(self):
        """Node B (toward target) should score higher than C (away)."""
        score_b = self.engine.score_neighbor(self.a, self.b, self.target)
        score_c = self.engine.score_neighbor(self.a, self.c, self.target)
        self.assertGreater(score_b, score_c)

    def test_select_next_hop_chooses_best(self):
        """select_next_hop should pick B over C."""
        best = self.engine.select_next_hop(self.a, self.target)
        self.assertEqual(best.id, "B")

    def test_load_reduces_score(self):
        """High load should reduce the score of a neighbor."""
        score_fresh = self.engine.score_neighbor(self.a, self.b, self.target)
        self.b.load = 20  # max normalized load
        score_loaded = self.engine.score_neighbor(self.a, self.b, self.target)
        self.assertLess(score_loaded, score_fresh)

    def test_dead_neighbor_excluded(self):
        """Dead neighbors should not appear in scored list."""
        self.b.fail()
        scored = self.engine.score_all_neighbors(self.a, self.target)
        neighbor_ids = [n.id for n, _ in scored]
        self.assertNotIn("B", neighbor_ids)

    def test_termination_at_local_minimum(self):
        """A node closer than all neighbors should terminate."""
        # D is very close to target
        d = Node("D", [0.95, 0.95])
        e = Node("E", [0.5, 0.5])
        d.add_neighbor(e)
        self.assertTrue(self.engine.has_reached_target(d, self.target))

    def test_no_termination_when_neighbor_closer(self):
        """A node with a closer neighbor should NOT terminate."""
        self.assertFalse(self.engine.has_reached_target(self.a, self.target))


# ═══════════════════════════════════════════════════════════════════
#  SIMULATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSimulation(unittest.TestCase):
    """End-to-end tests for the simulation runner."""

    def setUp(self):
        self.net = Network.generate(n_nodes=20, k_neighbors=4, dimensions=4, seed=42)
        self.engine = RoutingEngine()
        self.sim = Simulation(self.net, self.engine)

    def test_basic_routing_succeeds(self):
        """A basic routing request should find a path."""
        start = self.net.get_node("N000")
        req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
        result = self.sim.route_request(start, req)
        self.assertTrue(result.success)
        self.assertGreater(result.total_hops, 0)
        self.assertGreater(len(result.path), 0)

    def test_load_increases_with_routing(self):
        """Nodes on the path should have their load incremented."""
        start = self.net.get_node("N000")
        req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
        result = self.sim.route_request(start, req)
        # Every node in the path should have load >= 1
        for nid in result.path:
            node = self.net.get_node(nid)
            self.assertGreaterEqual(node.load, 1)

    def test_failure_doesnt_crash(self):
        """Routing should handle a dead node without crashing."""
        # Kill a central node
        self.net.get_node("N010").fail()
        start = self.net.get_node("N000")
        req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
        # Should not raise
        result = self.sim.route_request(start, req)
        self.assertIsNotNone(result)

    def test_path_avoids_dead_node(self):
        """A dead node should not appear in any routed path."""
        self.net.get_node("N010").fail()
        start = self.net.get_node("N000")
        req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
        result = self.sim.route_request(start, req)
        self.assertNotIn("N010", result.path)

    def test_result_format_not_empty(self):
        """Formatted output should produce a non-empty string."""
        start = self.net.get_node("N000")
        req = Request(target_vector=[0.5, 0.5, 0.5, 0.5])
        result = self.sim.route_request(start, req)
        formatted = Simulation.format_result(result)
        self.assertIn("ROUTING RESULT", formatted)
        self.assertIn("N000", formatted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
