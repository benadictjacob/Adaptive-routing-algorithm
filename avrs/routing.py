"""
Routing engine for the Adaptive Vector Routing System.

Implements the weighted scoring function and greedy next-hop selection.
No global path search — all decisions are local.
"""

from typing import Optional

from avrs.node import Node
from avrs.math_utils import (
    Vector,
    cosine_similarity,
    euclidean_distance,
    vector_subtract,
)


# ── Default Scoring Weights (Section 4) ──────────────────────────

ALPHA = 0.50   # direction importance (cosine)
BETA  = 0.30   # distance improvement
GAMMA = 0.15   # load penalty
DELTA = 0.05   # trust bonus


class RoutingEngine:
    """
    Computes per-neighbor scores and selects the greedy next hop.

    Score formula:
        score = α·cosine + β·distance_gain − γ·load + δ·trust

    Termination:
        The current node is a local minimum (no neighbor is closer)
        OR cosine similarity to target exceeds the threshold.
    """

    def __init__(
        self,
        alpha: float = ALPHA,
        beta: float = BETA,
        gamma: float = GAMMA,
        delta: float = DELTA,
        cosine_threshold: float = 0.95,
        use_cache: bool = True,
    ):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.delta = delta
        self.cosine_threshold = cosine_threshold
        self.use_cache = use_cache

    # ── Scoring ───────────────────────────────────────────────────

    def score_neighbor(
        self, current: Node, neighbor: Node, target: Vector
    ) -> float:
        """
        Compute the routing score for a single neighbor.

        Args:
            current:   The node currently holding the request.
            neighbor:  A candidate next-hop node.
            target:    The destination vector.

        Returns:
            A float score (higher is better).
        """
        # Direction vectors
        direction_to_target   = vector_subtract(target, current.vector)
        direction_to_neighbor = vector_subtract(neighbor.vector, current.vector)

        # Cosine similarity between direction-to-target and direction-to-neighbor
        cosine = cosine_similarity(direction_to_target, direction_to_neighbor)

        # Distance gain: how much closer the neighbor is to the target
        dist_current  = euclidean_distance(current.vector, target)
        dist_neighbor = euclidean_distance(neighbor.vector, target)
        distance_gain = dist_current - dist_neighbor

        # --- Peer Offloading (Proxy Logic) ---
        # If current node is loaded, prioritize neighbors that "do the same thing" (same role)
        peer_bonus = 0.0
        if neighbor.role == current.role and current.id != neighbor.id:
            # Bonus scales with current load: the busier we are, the more we want to offload to a peer
            if current.load > 10:
                peer_bonus = 0.25  # Significant priority for proxies during congestion
            else:
                peer_bonus = 0.05  # Subtle preference for same-section routing

        # Normalize load to [0, 1] range for consistent scoring
        # We cap at 20 to prevent extreme penalty
        normalized_load = min(neighbor.load / 20.0, 1.0) if neighbor.load > 0 else 0.0

        score = (
            self.alpha * cosine
            + self.beta * distance_gain
            - self.gamma * normalized_load
            + self.delta * neighbor.trust
            + peer_bonus  # Priority for semantic proxies
        )

        return score

    def score_all_neighbors(
        self, current: Node, target: Vector
    ) -> list[tuple[Node, float]]:
        """
        Score all alive neighbors and return sorted list (best first).
        """
        alive_neighbors = current.get_alive_neighbors()
        scored = []
        for neighbor in alive_neighbors:
            s = self.score_neighbor(current, neighbor, target)
            scored.append((neighbor, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Next-Hop Selection ────────────────────────────────────────

    def select_next_hop(
        self, current: Node, target: Vector
    ) -> Optional[Node]:
        """
        Choose the best next hop, or None if no valid hop exists.

        Uses route cache if enabled (Section 13).
        """
        # Check cache first
        if self.use_cache:
            target_key = tuple(round(v, 4) for v in target)
            cached_id = current.get_cached_route(target_key)
            if cached_id is not None:
                # Validate cached node is still alive and a neighbor
                for n in current.get_alive_neighbors():
                    if n.id == cached_id:
                        return n
                # Cache miss (node died or removed), fall through

        scored = self.score_all_neighbors(current, target)
        if not scored:
            return None

        best_node, best_score = scored[0]
        return best_node

    # ── Termination Check ─────────────────────────────────────────

    def has_reached_target(self, current: Node, target: Vector) -> bool:
        """
        Check if routing should terminate at the current node.

        Termination conditions (Section 12):
          1. Current node is a local minimum (closer than all neighbors).
          2. Cosine similarity between current vector and target > threshold.
        """
        current_dist = euclidean_distance(current.vector, target)

        # Condition 1: local minimum
        alive_neighbors = current.get_alive_neighbors()
        if alive_neighbors:
            all_farther = all(
                euclidean_distance(n.vector, target) >= current_dist
                for n in alive_neighbors
            )
            if all_farther:
                return True

        # Condition 2: high cosine similarity to target direction
        cos = cosine_similarity(current.vector, target)
        if cos > self.cosine_threshold:
            return True

        return False
