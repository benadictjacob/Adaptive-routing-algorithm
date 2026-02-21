"""
═══════════════════════════════════════════════════════════════════════
  ROUTING ENGINE MODULE
  Local greedy routing with adaptive scoring, fallback, and face routing.
═══════════════════════════════════════════════════════════════════════

Implements:
  Section 5  — Routing Decision Function (weighted scoring)
  Section 7  — Fallback Routing (try next best)
  Section 8  — Face Routing Mode activation
  Section 9  — Load Adaptation
  Section 10 — Trust System
  Section 11 — Failure Handling
  Section 13 — Termination Conditions
  Section 14 — Route Memory (Cache)

PROHIBITED (Section 21): No global pathfinding, no BFS/Dijkstra/A*,
no central coordinators, no routing tables.
All routing is LOCAL and GREEDY.
"""

from typing import Optional, List, Tuple

from vector_math import (
    Vector,
    cosine_similarity,
    euclidean_distance,
    vector_subtract,
)
from graph_builder import Node
from topology_engine import face_route_full


# ── Scoring Weights (Section 5) ──────────────────────────────────

ALPHA = 0.50   # cosine similarity (direction alignment)
BETA  = 0.30   # distance gain (closer to target)
GAMMA = 0.15   # load penalty
DELTA = 0.05   # trust bonus


class RoutingEngine:
    """
    Computes per-neighbor scores and selects the greedy next hop.

    Score formula (Section 5):
        score = 0.5*cosine + 0.3*distance_gain - 0.15*load + 0.05*trust

    Termination (Section 13):
        - current node is closest to target
        - cosine similarity > 0.99
        - hop limit reached
    """

    def __init__(
        self,
        alpha: float = ALPHA,
        beta: float = BETA,
        gamma: float = GAMMA,
        delta: float = DELTA,
        cosine_threshold: float = 0.99,  # Section 13: similarity > 0.99
        max_hops: int = 50,
        use_cache: bool = True,
        use_face_routing: bool = True,
    ):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta
        self.cosine_threshold = cosine_threshold
        self.max_hops = max_hops
        self.use_cache = use_cache
        self.use_face_routing = use_face_routing

    # ── Scoring (Section 5) ───────────────────────────────────────

    def score_neighbor(
        self, current: Node, neighbor: Node, target: Vector
    ) -> float:
        """
        Compute the routing score for a single neighbor.

        C = current vector, T = target vector, N = neighbor vector
        direction_to_target   = T − C
        direction_to_neighbor = N − C
        cosine = dot(A,B) / (‖A‖‖B‖)
        distance_gain = dist(C,T) − dist(N,T)

        score = 0.5*cosine + 0.3*distance_gain - 0.15*load + 0.05*trust
        """
        direction_to_target = vector_subtract(target, list(current.vector))
        direction_to_neighbor = vector_subtract(list(neighbor.vector), list(current.vector))

        cosine = cosine_similarity(direction_to_target, direction_to_neighbor)

        dist_current = euclidean_distance(list(current.vector), target)
        dist_neighbor = euclidean_distance(list(neighbor.vector), target)
        distance_gain = dist_current - dist_neighbor

        # Normalize load to [0,1] range (cap at 20)
        normalized_load = min(neighbor.load / 20.0, 1.0) if neighbor.load > 0 else 0.0

        score = (
            self.alpha * cosine
            + self.beta * distance_gain
            - self.gamma * normalized_load
            + self.delta * neighbor.trust
        )
        return score

    def score_all_neighbors(
        self, current: Node, target: Vector
    ) -> List[Tuple[Node, float]]:
        """Score all alive neighbors and return sorted list (best first)."""
        alive_neighbors = current.get_alive_neighbors()
        scored = []
        for neighbor in alive_neighbors:
            s = self.score_neighbor(current, neighbor, target)
            scored.append((neighbor, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Termination Check (Section 13) ────────────────────────────

    def has_reached_target(self, current: Node, target: Vector) -> str:
        """
        Check termination conditions.
        Returns reason string if terminated, empty string otherwise.

        Conditions:
          1. Current node is closest (local minimum)
          2. Cosine similarity > 0.99
        """
        current_dist = euclidean_distance(list(current.vector), target)

        # Condition 1: local minimum (no alive neighbor is closer)
        alive_neighbors = current.get_alive_neighbors()
        if alive_neighbors:
            all_farther = all(
                euclidean_distance(list(n.vector), target) >= current_dist - 1e-10
                for n in alive_neighbors
            )
            if all_farther:
                return "local_minimum"

        # Also terminal if no neighbors at all
        if not alive_neighbors:
            return "no_neighbors"

        # Condition 2: high cosine similarity
        cos = cosine_similarity(list(current.vector), target)
        if cos > self.cosine_threshold:
            return "high_similarity"

        return ""

    # ── Next-Hop Selection with Fallback (Sections 7, 8) ──────────

    def select_next_hop(
        self,
        current: Node,
        target: Vector,
        visited: set,
    ) -> Tuple[Optional[Node], str, List[dict]]:
        """
        Choose the best next hop with fallback logic.

        Section 7 fallback: if best neighbor doesn't reduce distance,
        try next best, repeat. If none improve, activate face routing.

        Returns:
            (next_node, method, score_details)
            method is "greedy", "fallback", "face", "cache", or "none"
        """
        score_details = []

        # Check cache first (Section 14)
        if self.use_cache:
            target_key = tuple(round(v, 4) for v in target)
            cached_id = current.get_cached_route(target_key)
            if cached_id is not None:
                for n in current.get_alive_neighbors():
                    if n.id == cached_id and n.id not in visited:
                        return n, "cache", []

        # Score all alive neighbors
        scored = self.score_all_neighbors(current, target)
        dist_current = euclidean_distance(list(current.vector), target)

        for neighbor, score in scored:
            dist_nb = euclidean_distance(list(neighbor.vector), target)
            improves = dist_nb < dist_current - 1e-10
            score_details.append({
                "neighbor": neighbor.id,
                "score": round(score, 4),
                "load": neighbor.load,
                "trust": round(neighbor.trust, 2),
                "distance": round(dist_nb, 4),
                "improves": improves,
                "alive": neighbor.alive,
            })

        # Try greedy: best scoring neighbor that hasn't been visited
        for neighbor, score in scored:
            if neighbor.id not in visited:
                dist_nb = euclidean_distance(list(neighbor.vector), target)
                if dist_nb < dist_current - 1e-10:
                    return neighbor, "greedy", score_details

        # Fallback (Section 7): try next best even if doesn't strictly improve distance
        for neighbor, score in scored:
            if neighbor.id not in visited:
                return neighbor, "fallback", score_details

        # Face routing (Section 8): all neighbors visited or none improve
        if self.use_face_routing:
            face_node, face_path = face_route_full(current, target, max_face_steps=30)
            if face_node is not None:
                return face_node, "face", score_details

        return None, "none", score_details
