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
    A network node positioned in vector space.

    Attributes:
        id:         Unique identifier for this node.
        vector:     Fixed coordinate in the routing vector space.
        neighbors:  List of directly connected neighbor nodes.
        load:       Dynamic workload counter (increases when handling requests).
        trust:      Reliability score in [0, 1].
        alive:      Whether this node is active and can participate in routing.
    """

    def __init__(
        self,
        node_id: str,
        vector: Vector,
        trust: float = 1.0,
    ):
        self.id: str = node_id
        self.vector: Vector = vector
        self.neighbors: List[Node] = []
        self.load: int = 0
        self.trust: float = trust
        self.alive: bool = True

        # Optional route cache: maps a rounded target vector tuple → next-hop node id
        self._route_cache: Dict[tuple, str] = {}

    # ── State Management ──────────────────────────────────────────

    def increment_load(self) -> None:
        """Called when this node handles a request."""
        self.load += 1

    def fail(self) -> None:
        """Mark this node as inactive (simulate failure)."""
        self.alive = False

    def recover(self) -> None:
        """Bring this node back online."""
        self.alive = True

    # ── Neighbor Management ───────────────────────────────────────

    def add_neighbor(self, neighbor: Node) -> None:
        """Add a bidirectional neighbor link (if not already present)."""
        if neighbor not in self.neighbors and neighbor.id != self.id:
            self.neighbors.append(neighbor)

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

    # ── Display ───────────────────────────────────────────────────

    def __repr__(self) -> str:
        status = "ALIVE" if self.alive else "DOWN"
        return (
            f"Node({self.id} | vec={[round(v, 3) for v in self.vector]} | "
            f"load={self.load} | trust={self.trust:.2f} | {status})"
        )

    def short(self) -> str:
        """Short label for log output."""
        return f"{self.id}"
