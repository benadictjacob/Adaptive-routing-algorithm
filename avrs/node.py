"""
Node data structure for the Adaptive Vector Routing System.

Each node represents a service in the decentralized network.
It knows only its own vector, its neighbors, and its local state.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from avrs.math_utils import Vector


class Node:
    """
    A universal network node positioned in vector space.
    Consolidates functionality for routing, topology, semantics, and security.

    Attributes:
        id:         Unique identifier for this node.
        vector:     Fixed coordinate (List[float]) in the routing vector space.
        role:       Semantic role/capability (e.g., 'database', 'auth').
        neighbors:  List of directly connected neighbor nodes.
        load:       Dynamic workload counter.
        trust:      Reliability score in [0, 1].
        alive:      Whether this node is active and can participate in routing.
        overload_threshold: Maximum load before considered 'overloaded'.
    """

    def __init__(
        self,
        node_id: str,
        vector: Vector,
        role: str = "default",
        trust: float = 1.0,
        overload_threshold: float = 20.0,
    ):
        self.id: str = node_id
        self.vector: Vector = list(vector)  # Ensure list for consistency
        self.role: str = role
        self.neighbors: List[Node] = []
        self.load: float = 0.0
        self.trust: float = max(0.0, min(1.0, trust))
        self.alive: bool = True
        self.overload_threshold: float = overload_threshold

        # Optional route cache: maps a rounded target vector tuple → next-hop node id
        self._route_cache: Dict[tuple, str] = {}

    # ── State Management ──────────────────────────────────────────

    def increment_load(self, amount: float = 1.0) -> None:
        """Increment workload counter."""
        self.load += amount

    def reset_load(self) -> None:
        """Reset load to zero."""
        self.load = 0.0

    def is_overloaded(self) -> bool:
        """Check if load exceeds threshold."""
        return self.load >= self.overload_threshold

    def fail(self) -> None:
        """Mark this node as inactive (simulate failure)."""
        self.alive = False

    def recover(self) -> None:
        """Bring this node back online."""
        self.alive = True

    # ── Trust Management (Section 10) ──────────────────────────────

    def reduce_trust(self, amount: float = 0.3) -> None:
        """Dynamically reduce trust score."""
        self.trust = max(0.0, self.trust - amount)

    def restore_trust(self, amount: float = 1.0) -> None:
        """Restore trust to desired level."""
        self.trust = max(0.0, min(1.0, amount))

    # ── Neighbor Management ───────────────────────────────────────

    def add_neighbor(self, neighbor: Node) -> None:
        """Add a bidirectional neighbor link (if not already present)."""
        if neighbor not in self.neighbors and neighbor.id != self.id:
            self.neighbors.append(neighbor)

    def remove_neighbor(self, neighbor: Node) -> None:
        """Remove a neighbor link."""
        self.neighbors = [n for n in self.neighbors if n.id != neighbor.id]

    def get_alive_neighbors(self) -> List[Node]:
        """Return only neighbors that are currently alive."""
        return [n for n in self.neighbors if n.alive]

    # ── Route Cache (Optional Optimization, Section 13) ───────────

    def cache_route(self, target_key: tuple, next_hop_id: str) -> None:
        """Cache a successful next-hop for a target vector key."""
        self._route_cache[target_key] = next_hop_id

    def get_cached_route(self, target_key: tuple) -> Optional[str]:
        """Retrieve a cached next-hop, or None."""
        return self._route_cache.get(target_key)

    def clear_cache(self) -> None:
        """Clear the route cache."""
        self._route_cache.clear()

    # ── Display ───────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "ALIVE" if self.alive else "DOWN"
        role_info = f" | role={self.role}" if self.role != "default" else ""
        return (
            f"Node({self.id}{role_info} | vec={[round(v, 3) for v in self.vector]} | "
            f"load={self.load:.1f} | trust={self.trust:.2f} | {status})"
        )

    def short(self) -> str:
        """Short label for log output."""
        return f"{self.id}"
