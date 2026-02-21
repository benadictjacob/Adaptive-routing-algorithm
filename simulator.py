"""
═══════════════════════════════════════════════════════════════════════
  SIMULATOR MODULE
  Request execution, detailed logging, and performance metrics.
═══════════════════════════════════════════════════════════════════════

Implements:
  Section 4  — Request Structure
  Section 15 — Logging (per-hop decisions)
  Section 18 — Assertions (no infinite loops, no cycling, finite termination)
  Section 19 — Performance Metrics
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import time

from vector_math import Vector, euclidean_distance, cosine_similarity
from graph_builder import Node
from routing_engine import RoutingEngine


# ═══════════════════════════════════════════════════════════════════
#  REQUEST STRUCTURE (Section 4)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Request:
    """
    Each request contains:
      target_vector — used for routing
      sender_id     — origin identifier
      payload       — NEVER influences routing
    """
    target_vector: Vector
    sender_id: str = "client"
    payload: str = ""


# ═══════════════════════════════════════════════════════════════════
#  HOP RECORD
# ═══════════════════════════════════════════════════════════════════

@dataclass
class HopRecord:
    """Record of a single routing hop."""
    step: int
    node_id: str
    node_vector: List[float]
    distance_to_target: float
    candidates: List[dict] = field(default_factory=list)
    chosen_next: Optional[str] = None
    method: str = ""  # greedy, fallback, face, cache, none
    skipped: List[str] = field(default_factory=list)
    is_terminal: bool = False
    terminal_reason: str = ""
    failure: bool = False


# ═══════════════════════════════════════════════════════════════════
#  ROUTE RESULT
# ═══════════════════════════════════════════════════════════════════

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
    reroute_count: int = 0      # times fallback or face routing was used
    face_route_count: int = 0   # times face routing was activated
    final_distance: float = 0.0
    optimal_distance: float = 0.0  # distance of closest node to target


# ═══════════════════════════════════════════════════════════════════
#  SIMULATOR
# ═══════════════════════════════════════════════════════════════════

class Simulator:
    """
    Runs routing requests through the network and produces detailed logs.
    Tracks performance metrics across multiple requests.
    """

    def __init__(
        self,
        nodes: List[Node],
        engine: Optional[RoutingEngine] = None,
        verbose: bool = True,
    ):
        self.nodes = nodes
        self.engine = engine or RoutingEngine()
        self.verbose = verbose
        self._results: List[RouteResult] = []

    def get_node(self, node_id: str) -> Optional[Node]:
        """Lookup node by ID."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def find_closest_node(self, target: Vector) -> Optional[Node]:
        """Find the alive node closest to the target."""
        best = None
        best_dist = float('inf')
        for node in self.nodes:
            if not node.alive:
                continue
            d = euclidean_distance(list(node.vector), target)
            if d < best_dist:
                best_dist = d
                best = node
        return best

    # ── Route Execution ───────────────────────────────────────────

    def route_request(
        self,
        start: Node,
        request: Request,
    ) -> RouteResult:
        """
        Execute a routing request from start toward request.target_vector.

        Assertions (Section 18):
          - No infinite loops (hop limit enforced)
          - No packet cycling (visited set)
          - Finite termination guaranteed
        """
        target = request.target_vector
        closest_node = self.find_closest_node(target)
        optimal_dist = euclidean_distance(list(closest_node.vector), target) if closest_node else float('inf')

        result = RouteResult(
            request=request,
            start_node_id=start.id,
            optimal_distance=optimal_dist,
        )

        current = start
        visited = set()

        for step in range(self.engine.max_hops):
            # ASSERTION: no cycling — check before adding
            assert current.id not in visited, \
                f"ASSERTION FAILED: Packet cycle detected at {current.id}"

            result.path.append(current.id)
            visited.add(current.id)

            dist = euclidean_distance(list(current.vector), target)

            # Increment load on current node (Section 9)
            current.increment_load()

            # Check termination (Section 13)
            term_reason = self.engine.has_reached_target(current, target)
            if term_reason:
                hop = HopRecord(
                    step=step,
                    node_id=current.id,
                    node_vector=list(current.vector),
                    distance_to_target=round(dist, 4),
                    is_terminal=True,
                    terminal_reason=term_reason,
                )
                result.hops.append(hop)
                result.success = True
                result.final_node_id = current.id
                result.total_hops = step + 1
                result.final_distance = dist
                break

            # Select next hop (includes fallback + face routing)
            next_node, method, score_details = self.engine.select_next_hop(
                current, target, visited
            )

            # Build hop record
            skipped = [s["neighbor"] for s in score_details if s["neighbor"] in visited]
            hop = HopRecord(
                step=step,
                node_id=current.id,
                node_vector=[round(v, 4) for v in current.vector],
                distance_to_target=round(dist, 4),
                candidates=score_details,
                chosen_next=next_node.id if next_node else None,
                method=method,
                skipped=skipped,
            )

            if next_node is None:
                hop.failure = True
                result.hops.append(hop)
                result.success = False
                result.final_node_id = current.id
                result.total_hops = step + 1
                result.final_distance = dist
                break

            # Track rerouting
            if method in ("fallback", "face"):
                result.reroute_count += 1
            if method == "face":
                result.face_route_count += 1

            result.hops.append(hop)

            # Cache route (Section 14)
            if self.engine.use_cache:
                target_key = tuple(round(v, 4) for v in target)
                current.cache_route(target_key, next_node.id)

            # Forward
            current = next_node

        else:
            # Hit max_hops — guaranteed termination (Section 18)
            result.success = False
            result.final_node_id = current.id
            result.total_hops = self.engine.max_hops
            result.final_distance = euclidean_distance(list(current.vector), target)

        self._results.append(result)
        return result

    # ── Logging (Section 15) ──────────────────────────────────────

    @staticmethod
    def format_result(result: RouteResult) -> str:
        """Format a RouteResult into detailed human-readable log."""
        lines = []
        lines.append("═" * 70)
        lines.append("  ROUTING RESULT")
        lines.append("═" * 70)
        lines.append(f"  Target Vector : {[round(v, 4) for v in result.request.target_vector]}")
        lines.append(f"  Sender        : {result.request.sender_id}")
        lines.append(f"  Start Node    : {result.start_node_id}")
        lines.append(f"  Final Node    : {result.final_node_id}")
        lines.append(f"  Success       : {'YES' if result.success else 'FAILED'}")
        lines.append(f"  Total Hops    : {result.total_hops}")
        lines.append(f"  Path          : {' → '.join(result.path)}")
        lines.append(f"  Reroutes      : {result.reroute_count}")
        lines.append(f"  Face Routes   : {result.face_route_count}")
        lines.append(f"  Final Distance: {result.final_distance:.4f}")
        lines.append(f"  Optimal Dist  : {result.optimal_distance:.4f}")
        lines.append("─" * 70)

        for hop in result.hops:
            lines.append(f"  Step {hop.step}: {hop.node_id}  (method={hop.method})")
            lines.append(f"    Vector     : {hop.node_vector}")
            lines.append(f"    Dist→Target: {hop.distance_to_target}")

            if hop.candidates:
                lines.append("    Candidates :")
                for sc in hop.candidates:
                    flag = "✓" if sc.get("improves") else " "
                    lines.append(
                        f"      {flag} {sc['neighbor']:>5}  score={sc['score']:+.4f}  "
                        f"load={sc['load']:.0f}  trust={sc['trust']:.2f}  "
                        f"dist={sc['distance']:.4f}"
                    )

            if hop.skipped:
                lines.append(f"    Skipped    : {hop.skipped}")

            if hop.is_terminal:
                lines.append(f"    ✓ REACHED TARGET ({hop.terminal_reason})")
            elif hop.failure:
                lines.append("    ✗ ROUTING FAILED (no valid next hop)")
            elif hop.chosen_next:
                lines.append(f"    → Forwarding to {hop.chosen_next}")

        lines.append("═" * 70)
        return "\n".join(lines)

    # ── Performance Metrics (Section 19) ──────────────────────────

    def get_metrics(self) -> Dict[str, float]:
        """
        Compute performance metrics across all tracked requests.

        Returns dict with:
          average_hops, success_rate, reroute_count,
          failure_recovery_rate, path_stretch_ratio, routing_efficiency
        """
        if not self._results:
            return {
                "total_requests": 0,
                "average_hops": 0,
                "success_rate": 0,
                "total_reroutes": 0,
                "failure_recovery_rate": 0,
                "path_stretch_ratio": 0,
                "routing_efficiency": 0,
            }

        total = len(self._results)
        successes = sum(1 for r in self._results if r.success)
        total_hops = sum(r.total_hops for r in self._results)
        total_reroutes = sum(r.reroute_count for r in self._results)

        # Failure recovery rate: of requests that used rerouting, how many succeeded
        rerouted = [r for r in self._results if r.reroute_count > 0]
        recovery_rate = (
            sum(1 for r in rerouted if r.success) / len(rerouted)
            if rerouted else 1.0
        )

        # Path stretch ratio: actual hops / optimal straight-line hops
        stretch_values = []
        for r in self._results:
            if r.success and r.optimal_distance > 0:
                # Estimate optimal hops as euclidean dist / avg hop distance
                if r.total_hops > 0:
                    stretch_values.append(r.final_distance / r.optimal_distance)

        avg_stretch = sum(stretch_values) / len(stretch_values) if stretch_values else 1.0

        # Routing efficiency: success_rate * (1 / avg_hops)
        avg_hops = total_hops / total if total > 0 else 0
        efficiency = (successes / total) * (1.0 / max(avg_hops, 1)) if total > 0 else 0

        return {
            "total_requests": total,
            "average_hops": round(avg_hops, 2),
            "success_rate": round(successes / total, 4) if total > 0 else 0,
            "total_reroutes": total_reroutes,
            "failure_recovery_rate": round(recovery_rate, 4),
            "path_stretch_ratio": round(avg_stretch, 4),
            "routing_efficiency": round(efficiency, 4),
        }

    def print_metrics(self) -> None:
        """Print a formatted performance summary."""
        m = self.get_metrics()
        print("\n" + "═" * 50)
        print("  PERFORMANCE METRICS SUMMARY")
        print("═" * 50)
        print(f"  Total Requests       : {m['total_requests']}")
        print(f"  Average Hops         : {m['average_hops']}")
        print(f"  Success Rate         : {m['success_rate']*100:.1f}%")
        print(f"  Total Reroutes       : {m['total_reroutes']}")
        print(f"  Failure Recovery Rate : {m['failure_recovery_rate']*100:.1f}%")
        print(f"  Path Stretch Ratio   : {m['path_stretch_ratio']:.4f}")
        print(f"  Routing Efficiency   : {m['routing_efficiency']:.4f}")
        print("═" * 50)

    def reset_metrics(self) -> None:
        """Clear accumulated metrics."""
        self._results = []
