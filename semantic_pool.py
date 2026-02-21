"""
=====================================================================
  SEMANTIC POOL LOAD BALANCING MODULE
  Sections 1-10 of the Semantic Pool Specification
=====================================================================

Ensures requests route ONLY to nodes capable of the requested task 
and distributes traffic across equivalent nodes in the same pool.
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from vector_math import euclidean_distance, cosine_similarity


# ===================================================================
#  SECTION 1 — NODE CAPABILITY TAG
# ===================================================================

VALID_ROLES = {"auth", "proxy", "image_processor", "database", "compute", "storage", "gateway", "general"}


class SemanticNode:
    """
    Node with a semantic_role describing its capability.
    Wraps existing Node objects or can stand alone.
    """

    def __init__(
        self,
        node_id: str,
        vector: list,
        semantic_role: str = "general",
        trust: float = 1.0,
        overload_threshold: int = 20,
    ):
        self.id = node_id
        self.vector = tuple(vector)
        self.semantic_role = semantic_role
        self.neighbors: List["SemanticNode"] = []
        self.load: int = 0
        self.trust: float = trust
        self.alive: bool = True
        self.overload_threshold = overload_threshold

    def add_neighbor(self, other: "SemanticNode"):
        if other not in self.neighbors and other is not self:
            self.neighbors.append(other)

    def is_overloaded(self) -> bool:
        return self.load >= self.overload_threshold

    def increment_load(self):
        self.load += 1

    def reset_load(self):
        self.load = 0

    def fail(self):
        self.alive = False

    def recover(self):
        self.alive = True

    def __repr__(self):
        return f"SemanticNode({self.id}, role={self.semantic_role}, load={self.load})"


# ===================================================================
#  SECTION 2 — REQUEST REQUIREMENT TAG
# ===================================================================

@dataclass
class SemanticRequest:
    """Request that specifies which semantic role it needs."""
    target_vector: list
    required_role: str
    sender_id: str = ""
    payload: str = ""


# ===================================================================
#  SECTION 3 — SEMANTIC FILTER STAGE
# ===================================================================

def semantic_filter(
    candidates: List[SemanticNode],
    required_role: str,
    expand_search: bool = True,
) -> List[SemanticNode]:
    """
    Filter candidate nodes by semantic_role == required_role.
    If none found and expand_search is True, expand one hop outward.
    """
    # Direct match among candidates
    matched = [
        n for n in candidates
        if n.alive and n.semantic_role == required_role
    ]
    if matched:
        return matched

    # Expand search: look at neighbors of candidates
    if expand_search:
        seen = set(n.id for n in candidates)
        expanded = []
        for c in candidates:
            for nb in c.neighbors:
                if nb.id not in seen and nb.alive and nb.semantic_role == required_role:
                    expanded.append(nb)
                    seen.add(nb.id)
        if expanded:
            return expanded

    return []


# ===================================================================
#  SECTION 4 — LOAD-AWARE SELECTION
# ===================================================================

def score_candidate(
    node: SemanticNode,
    target_vector: list,
    distance_weight: float = 0.5,
    load_weight: float = 0.3,
    trust_weight: float = 0.2,
    max_load_normalizer: int = 20,
) -> float:
    """
    Score = distance_weight * (1 - normalized_distance)
          - load_weight * normalized_load
          + trust_weight * trust

    Lower load -> higher score.
    """
    dist = euclidean_distance(list(node.vector), target_vector)
    max_dist = 4.0  # max possible in 4D-unit space
    norm_dist = min(dist / max_dist, 1.0)
    norm_load = min(node.load / max(max_load_normalizer, 1), 1.0)

    score = (
        distance_weight * (1.0 - norm_dist)
        - load_weight * norm_load
        + trust_weight * node.trust
    )
    return score


def select_best_candidate(
    candidates: List[SemanticNode],
    target_vector: list,
    **kwargs,
) -> Optional[SemanticNode]:
    """
    From filtered candidates, pick the one with highest score.
    Section 6: skip overloaded nodes.
    """
    viable = [n for n in candidates if n.alive and not n.is_overloaded()]
    if not viable:
        # Fallback: try even overloaded ones if all else fails
        viable = [n for n in candidates if n.alive]
    if not viable:
        return None

    scored = [(score_candidate(n, target_vector, **kwargs), n) for n in viable]
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ===================================================================
#  SECTION 5 — PROXY POOL DISTRIBUTION
# ===================================================================

class SemanticPool:
    """
    Manages semantic node pools and distributes traffic.
    """

    def __init__(self, nodes: List[SemanticNode]):
        self.nodes = nodes
        self._pools: Dict[str, List[SemanticNode]] = {}
        self._round_robin_idx: Dict[str, int] = {}
        self._metrics: Dict[str, dict] = {}
        self._rebuild_pools()

    def _rebuild_pools(self):
        """Group alive nodes by semantic_role."""
        self._pools.clear()
        for n in self.nodes:
            if n.alive:
                self._pools.setdefault(n.semantic_role, []).append(n)
        # Init round-robin counters
        for role in self._pools:
            if role not in self._round_robin_idx:
                self._round_robin_idx[role] = 0
            if role not in self._metrics:
                self._metrics[role] = {
                    "total_requests": 0,
                    "per_node_requests": {},
                    "failover_count": 0,
                }

    def get_pool(self, role: str) -> List[SemanticNode]:
        """Get all alive nodes in a role pool."""
        return [n for n in self._pools.get(role, []) if n.alive]

    def get_all_roles(self) -> List[str]:
        return list(self._pools.keys())

    # ── Section 5: Proportional distribution ───────────────────

    def select_from_pool(
        self,
        role: str,
        target_vector: list,
        strategy: str = "best_score",
    ) -> Optional[SemanticNode]:
        """
        Select a node from the pool for the given role.

        Strategies:
          - "best_score": pick highest-scoring non-overloaded node
          - "round_robin": rotate across pool nodes
        """
        pool = self.get_pool(role)
        if not pool:
            return None

        # Track request
        if role not in self._metrics:
            self._metrics[role] = {
                "total_requests": 0,
                "per_node_requests": {},
                "failover_count": 0,
            }
        self._metrics[role]["total_requests"] += 1

        if strategy == "round_robin":
            # Simple round-robin for even distribution
            non_overloaded = [n for n in pool if not n.is_overloaded()]
            if not non_overloaded:
                non_overloaded = pool  # fallback
            idx = self._round_robin_idx.get(role, 0) % len(non_overloaded)
            selected = non_overloaded[idx]
            self._round_robin_idx[role] = idx + 1
        else:
            # Score-based selection (default)
            selected = select_best_candidate(pool, target_vector)
            if not selected:
                return None

        selected.increment_load()
        self._metrics[role]["per_node_requests"].setdefault(selected.id, 0)
        self._metrics[role]["per_node_requests"][selected.id] += 1
        return selected

    # ── Section 7: Failover guarantee ──────────────────────────

    def failover_select(
        self,
        failed_node: SemanticNode,
        target_vector: list,
    ) -> Optional[SemanticNode]:
        """
        When a node fails, select another from the same pool.
        """
        role = failed_node.semantic_role
        pool = [n for n in self.get_pool(role) if n.id != failed_node.id]
        if not pool:
            return None

        # Track failover
        if role in self._metrics:
            self._metrics[role]["failover_count"] += 1

        result = select_best_candidate(pool, target_vector)
        if result:
            result.increment_load()
        return result

    # ── Section 8: Pool metrics ────────────────────────────────

    def get_pool_metrics(self, role: str) -> dict:
        """Return per-role metrics."""
        pool = self.get_pool(role)
        m = self._metrics.get(role, {
            "total_requests": 0,
            "per_node_requests": {},
            "failover_count": 0,
        })
        loads = [n.load for n in pool] if pool else [0]
        return {
            "role": role,
            "active_nodes": len(pool),
            "average_load": sum(loads) / len(loads) if loads else 0,
            "request_distribution": dict(m.get("per_node_requests", {})),
            "failover_count": m.get("failover_count", 0),
            "total_requests": m.get("total_requests", 0),
        }

    def get_all_metrics(self) -> Dict[str, dict]:
        """Return metrics for all roles."""
        return {role: self.get_pool_metrics(role) for role in self._pools}

    def print_metrics(self):
        """Pretty-print pool metrics."""
        print("\n" + "=" * 60)
        print("  SEMANTIC POOL METRICS")
        print("=" * 60)
        for role in sorted(self._pools.keys()):
            m = self.get_pool_metrics(role)
            print(f"\n  [{role.upper()}]")
            print(f"    Active nodes: {m['active_nodes']}")
            print(f"    Avg load:     {m['average_load']:.1f}")
            print(f"    Requests:     {m['total_requests']}")
            print(f"    Failovers:    {m['failover_count']}")
            if m['request_distribution']:
                print(f"    Distribution: {m['request_distribution']}")
        print("=" * 60)


# ===================================================================
#  SECTION 9 — SIMULATION DISPLAY
# ===================================================================

def display_semantic_topology(pool: SemanticPool):
    """Print a visual summary of semantic regions and node roles."""
    print("\n" + "=" * 60)
    print("  SEMANTIC TOPOLOGY MAP")
    print("=" * 60)

    for role in sorted(pool.get_all_roles()):
        nodes = pool.get_pool(role)
        print(f"\n  [{role.upper()}] ({len(nodes)} nodes)")
        for n in nodes:
            load_bar = "#" * min(n.load, 20) + "." * max(0, 20 - n.load)
            status = "ALIVE" if n.alive else "DOWN "
            overload = " OVERLOADED" if n.is_overloaded() else ""
            print(f"    {n.id:>8} [{status}] load={n.load:>3} [{load_bar}]{overload}")

    print("=" * 60)


# ===================================================================
#  FULL ROUTING WITH SEMANTIC AWARENESS
# ===================================================================

@dataclass
class SemanticRouteResult:
    """Result of a semantic-aware routing request."""
    success: bool
    selected_node_id: str = ""
    role: str = ""
    hops_searched: int = 0
    was_failover: bool = False
    reason: str = ""


def route_semantic_request(
    pool: SemanticPool,
    request: SemanticRequest,
    strategy: str = "best_score",
) -> SemanticRouteResult:
    """
    Route a request to the best node matching required_role.
    Enforces: role match, overload avoidance, pool distribution.
    """
    role = request.required_role

    # Check if pool exists for this role
    available = pool.get_pool(role)
    if not available:
        return SemanticRouteResult(
            success=False,
            role=role,
            reason="no_nodes_for_role",
        )

    # Select from pool
    selected = pool.select_from_pool(role, request.target_vector, strategy)
    if not selected:
        return SemanticRouteResult(
            success=False,
            role=role,
            hops_searched=len(available),
            reason="all_nodes_unavailable",
        )

    return SemanticRouteResult(
        success=True,
        selected_node_id=selected.id,
        role=role,
        hops_searched=len(available),
    )


# ===================================================================
#  HELPER: BUILD SEMANTIC NETWORK
# ===================================================================

def build_semantic_network(
    roles: Dict[str, int],
    dimensions: int = 4,
    k: int = 4,
    seed: int = 42,
    overload_threshold: int = 20,
) -> List[SemanticNode]:
    """
    Build a network of SemanticNodes with assigned roles.

    Args:
        roles: mapping of role_name -> count, e.g. {"auth": 3, "compute": 5}
    """
    rng = random.Random(seed)
    nodes = []
    idx = 0
    for role, count in roles.items():
        for _ in range(count):
            vec = [rng.uniform(-1, 1) for _ in range(dimensions)]
            node = SemanticNode(
                f"S{idx:03d}",
                vec,
                semantic_role=role,
                overload_threshold=overload_threshold,
            )
            nodes.append(node)
            idx += 1

    # Connect: each node connects to its K nearest neighbors
    for n in nodes:
        dists = []
        for other in nodes:
            if other is n:
                continue
            d = euclidean_distance(list(n.vector), list(other.vector))
            dists.append((d, other))
        dists.sort(key=lambda x: x[0])
        for _, nb in dists[:k]:
            n.add_neighbor(nb)
            nb.add_neighbor(n)

    return nodes
