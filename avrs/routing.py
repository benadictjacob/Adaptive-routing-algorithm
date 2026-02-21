"""
Routing engine for the Adaptive Vector Routing System.

Implements the weighted scoring function and greedy next-hop selection.
No global path search — all decisions are local.

SECTION 5 — ROUTING DECISION FUNCTION:
score = 0.5 × semantic_similarity + 0.2 × trust - 0.2 × load_ratio - 0.1 × latency

SECTION 6 — CAPACITY FILTER:
Before scoring, router must discard nodes where load ≥ capacity.
"""

from typing import Optional, List, Tuple

from avrs.node import Node
from avrs.math_utils import (
    Vector,
    cosine_similarity,
    euclidean_distance,
    vector_subtract,
)


# ── Default Scoring Weights (Section 5) ──────────────────────────

SEMANTIC_WEIGHT = 0.5   # semantic similarity
TRUST_WEIGHT = 0.2      # trust score
LOAD_PENALTY = 0.2      # load ratio penalty
LATENCY_PENALTY = 0.1   # latency penalty


class RoutingEngine:
    """
    Computes per-neighbor scores and selects the greedy next hop.

    SECTION 5 — ROUTING DECISION FUNCTION:
    score = 0.5 × semantic_similarity + 0.2 × trust - 0.2 × load_ratio - 0.1 × latency

    SECTION 6 — CAPACITY FILTER:
    Nodes where load ≥ capacity are discarded before scoring.

    Termination:
        The current node is a local minimum (no neighbor is closer)
        OR cosine similarity to target exceeds the threshold.
    """

    def __init__(
        self,
        semantic_weight: float = SEMANTIC_WEIGHT,
        trust_weight: float = TRUST_WEIGHT,
        load_penalty: float = LOAD_PENALTY,
        latency_penalty: float = LATENCY_PENALTY,
        cosine_threshold: float = 0.95,
        use_cache: bool = True,
    ):
        self.semantic_weight = semantic_weight
        self.trust_weight = trust_weight
        self.load_penalty = load_penalty
        self.latency_penalty = latency_penalty
        self.cosine_threshold = cosine_threshold
        self.use_cache = use_cache

    # ── Scoring ───────────────────────────────────────────────────

    def score_neighbor(
        self, current: Node, neighbor: Node, target: Vector
    ) -> float:
        """
        SECTION 5 — Compute the routing score for a single neighbor.
        
        Formula: score = 0.5 × semantic_similarity + 0.2 × trust - 0.2 × load_ratio - 0.1 × latency

        Args:
            current:   The node currently holding the request.
            neighbor:  A candidate next-hop node.
            target:    The destination vector (request's semantic embedding).

        Returns:
            A float score (higher is better).
        """
        # SECTION 4: Semantic similarity (cosine similarity between node vector and request vector)
        semantic_similarity = cosine_similarity(neighbor.vector, target)
        
        # Trust score (already normalized to [0, 1])
        trust = neighbor.trust
        
        # Load ratio (normalized load / capacity, clamped to [0, 1])
        load_ratio = neighbor.get_load_ratio()
        
        # Latency (normalized to [0, 1] range, assuming max latency of 1000ms)
        # Lower latency is better, so we use (1 - normalized_latency)
        normalized_latency = min(neighbor.latency / 1000.0, 1.0)
        latency_factor = 1.0 - normalized_latency
        
        # SECTION 5: Exact formula from specification
        score = (
            self.semantic_weight * semantic_similarity
            + self.trust_weight * trust
            - self.load_penalty * load_ratio
            - self.latency_penalty * (1.0 - latency_factor)  # Penalty increases with latency
        )

        return score
    
    def filter_by_capacity(self, nodes: List[Node]) -> List[Node]:
        """
        SECTION 6 — CAPACITY FILTER (MANDATORY)
        
        Before scoring, router must discard nodes where load ≥ capacity.
        
        Args:
            nodes: List of candidate nodes
            
        Returns:
            List of nodes that are below capacity
        """
        return [node for node in nodes if not node.is_at_capacity()]

    def score_all_neighbors(
        self, current: Node, target: Vector, target_role: Optional[str] = None
    ) -> list[tuple[Node, float]]:
        """
        Score all alive neighbors and return sorted list (best first).
        
        SECTION 6: Applies capacity filter before scoring.
        SECTION 2: Filters by service section (role) if target_role is provided.
        
        Args:
            current: Current node
            target: Target vector
            target_role: Optional target service role for filtering
            
        Returns:
            List of (node, score) tuples, sorted by score (best first)
        """
        # Get alive neighbors
        alive_neighbors = current.get_alive_neighbors()
        
        # SECTION 2: Filter by service section if target_role specified
        if target_role:
            alive_neighbors = [n for n in alive_neighbors if n.role == target_role]
        
        # SECTION 6: Apply capacity filter (mandatory)
        available_neighbors = self.filter_by_capacity(alive_neighbors)
        
        # Score remaining neighbors
        scored = []
        for neighbor in available_neighbors:
            s = self.score_neighbor(current, neighbor, target)
            scored.append((neighbor, s))
        
        # Sort by score (highest first)
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ── Next-Hop Selection ────────────────────────────────────────

    def select_next_hop(
        self, current: Node, target: Vector, target_role: Optional[str] = None,
        recent_nodes: Optional[List[str]] = None
    ) -> Optional[Node]:
        """
        Choose the best next hop, or None if no valid hop exists.

        SECTION 6: Only selects from nodes below capacity.
        SECTION 2: Only selects nodes matching target_role if specified.
        SECTION 12: Load balancing - avoids repeated routing to same node.
        
        Uses route cache if enabled (Section 13).
        
        Args:
            current: Current node
            target: Target vector
            target_role: Optional target service role
            recent_nodes: List of recently used node IDs (for load balancing)
            
        Returns:
            Best next hop node, or None if no valid hop exists
        """
        recent_nodes = recent_nodes or []
        
        # Check cache first
        if self.use_cache:
            target_key = tuple(round(v, 4) for v in target)
            cached_id = current.get_cached_route(target_key)
            if cached_id is not None:
                # Validate cached node is still alive, a neighbor, and below capacity
                for n in current.get_alive_neighbors():
                    if n.id == cached_id and not n.is_at_capacity():
                        if target_role is None or n.role == target_role:
                            # SECTION 12: Prefer nodes not recently used
                            if n.id not in recent_nodes:
                                return n
                            # If cached node was recently used, fall through to scoring

        scored = self.score_all_neighbors(current, target, target_role)
        if not scored:
            return None

        # SECTION 12: Load balancing - prefer nodes not recently used
        # If multiple nodes have similar scores, prefer one not recently used
        best_score = scored[0][1]
        score_threshold = best_score * 0.95  # Within 5% of best score
        
        # Find all nodes within score threshold
        candidates = [(node, score) for node, score in scored if score >= score_threshold]
        
        # Prefer nodes not in recent_nodes
        for node, score in candidates:
            if node.id not in recent_nodes:
                return node
        
        # If all candidates were recently used, return best anyway
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
