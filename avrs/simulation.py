"""
Simulation runner for the Adaptive Vector Routing System.

Executes routing requests step-by-step and produces detailed logs.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from avrs.node import Node
from avrs.network import Network
from avrs.routing import RoutingEngine
from avrs.math_utils import Vector, euclidean_distance


# ── Request Representation (Section 7) ────────────────────────────

@dataclass
class Request:
    """A routing request in the network."""
    target_vector: Vector
    sender_id: str = "client"
    payload: str = ""


# ── Hop Record ────────────────────────────────────────────────────

@dataclass
class HopRecord:
    """Record of a single routing hop."""
    step: int
    node_id: str
    node_vector: List[float]
    distance_to_target: float
    scores: List[dict] = field(default_factory=list)
    chosen_next: Optional[str] = None
    is_terminal: bool = False
    failure: bool = False


# ── Route Result ──────────────────────────────────────────────────

@dataclass
class RouteResult:
    """Complete result of a routing operation."""
    request: Request
    start_node_id: str
    path: List[str] = field(default_factory=list)
    hops: List[HopRecord] = field(default_factory=list)
    success: bool = False
    final_node_id: Optional[str] = None
    total_hops: int = 0


# ── Simulation Engine ────────────────────────────────────────────

class Simulation:
    """
    Runs routing requests through the network and records results.
    """

    MAX_HOPS = 50  # Safety limit to prevent infinite loops

    def __init__(self, network: Network, engine: Optional[RoutingEngine] = None):
        self.network = network
        self.engine = engine or RoutingEngine()

    def route_request(
        self,
        start_node: Node,
        request: Request,
    ) -> RouteResult:
        """
        Execute a routing request from start_node toward request.target_vector.

        Algorithm (Section 8):
          1. Current node receives request.
          2. Check if current node satisfies target condition.
          3. If yes → stop.
          4. Else evaluate all neighbors & choose best.
          5. Forward request.

        Returns:
            A RouteResult with full path and hop details.
        """
        result = RouteResult(
            request=request,
            start_node_id=start_node.id,
        )

        current = start_node
        visited = set()
        target = request.target_vector

        for step in range(self.MAX_HOPS):
            # Record visit
            result.path.append(current.id)
            visited.add(current.id)

            dist = euclidean_distance(current.vector, target)

            # Score neighbors
            scored = self.engine.score_all_neighbors(current, target)
            score_records = [
                {
                    "neighbor": n.id,
                    "score": round(s, 4),
                    "load": n.load,
                    "alive": n.alive,
                }
                for n, s in scored
            ]

            hop = HopRecord(
                step=step,
                node_id=current.id,
                node_vector=[round(v, 4) for v in current.vector],
                distance_to_target=round(dist, 4),
                scores=score_records,
            )

            # Increment load on current node (Section 10)
            current.increment_load()

            # Check termination (Section 12)
            if self.engine.has_reached_target(current, target):
                hop.is_terminal = True
                result.hops.append(hop)
                result.success = True
                result.final_node_id = current.id
                result.total_hops = step + 1
                break

            # Select next hop
            next_node = self.engine.select_next_hop(current, target)

            # Filter out already-visited nodes to avoid loops
            if next_node and next_node.id in visited:
                # Try other neighbors
                for candidate, _ in scored:
                    if candidate.id not in visited:
                        next_node = candidate
                        break
                else:
                    next_node = None

            if next_node is None:
                # No valid next hop → routing fails gracefully (Section 9)
                hop.failure = True
                result.hops.append(hop)
                result.success = False
                result.final_node_id = current.id
                result.total_hops = step + 1
                break

            hop.chosen_next = next_node.id
            result.hops.append(hop)

            # Cache route (Section 13)
            target_key = tuple(round(v, 4) for v in target)
            current.cache_route(target_key, next_node.id)

            # Forward
            current = next_node

        else:
            # Hit MAX_HOPS without termination
            result.success = False
            result.final_node_id = current.id
            result.total_hops = self.MAX_HOPS

        return result

    # ── Logging ───────────────────────────────────────────────────

    @staticmethod
    def format_result(result: RouteResult) -> str:
        """
        Format a RouteResult into a human-readable log string (Section 16).
        """
        lines = []
        lines.append("=" * 70)
        lines.append("  ROUTING RESULT")
        lines.append("=" * 70)
        lines.append(f"  Target Vector : {[round(v, 4) for v in result.request.target_vector]}")
        lines.append(f"  Start Node    : {result.start_node_id}")
        lines.append(f"  Final Node    : {result.final_node_id}")
        lines.append(f"  Success       : {'YES' if result.success else 'FAILED'}")
        lines.append(f"  Total Hops    : {result.total_hops}")
        lines.append(f"  Path          : {' → '.join(result.path)}")
        lines.append("-" * 70)

        for hop in result.hops:
            lines.append(f"  Step {hop.step}: {hop.node_id}")
            lines.append(f"    Vector   : {hop.node_vector}")
            lines.append(f"    Dist→Tgt : {hop.distance_to_target}")

            if hop.scores:
                lines.append("    Scores   :")
                for sc in hop.scores:
                    lines.append(
                        f"      {sc['neighbor']:>5}  score={sc['score']:+.4f}  "
                        f"load={sc['load']}  alive={sc['alive']}"
                    )

            if hop.is_terminal:
                lines.append("    ✓ REACHED TARGET (terminal node)")
            elif hop.failure:
                lines.append("    ✗ ROUTING FAILED (no valid next hop)")
            elif hop.chosen_next:
                lines.append(f"    → Forwarding to {hop.chosen_next}")

        lines.append("=" * 70)
        return "\n".join(lines)
