"""
Simulation runner for the Adaptive Vector Routing System.

Executes routing requests step-by-step and produces detailed logs.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from avrs.node import Node
from avrs.network import Network
from avrs.routing import RoutingEngine
from avrs.math_utils import Vector, euclidean_distance
from avrs.service_grouping import ServiceGrouping
from avrs.trust_system import TrustSystem
from avrs.observability import Observability, RouteMetrics


# ── Request Representation (Section 3) ────────────────────────────

@dataclass
class Request:
    """
    SECTION 3 — REQUEST STRUCTURE
    
    Each request must contain:
    - request_text: The semantic description of the request
    - target_vector: Generated automatically from request_text
    - client_id: Identifier of the requesting client
    - timestamp: Request timestamp
    - nonce: Unique nonce for replay protection
    - payload: Request payload (ignored for routing)
    """
    request_text: str
    target_vector: Vector
    client_id: str = "client"
    timestamp: float = 0.0
    nonce: str = ""
    payload: str = ""
    
    @classmethod
    def create(cls, request_text: str, client_id: str = "client", 
               payload: str = "", embedder=None) -> "Request":
        """
        Create a request with auto-generated target_vector.
        
        Args:
            request_text: Semantic description of the request
            client_id: Client identifier
            payload: Request payload
            embedder: VectorEmbedder instance (uses default if None)
        """
        import time
        import secrets
        from avrs.vector_embedding import get_embedder
        
        if embedder is None:
            embedder = get_embedder()
        
        target_vector = embedder.embed_request(request_text)
        
        return cls(
            request_text=request_text,
            target_vector=target_vector,
            client_id=client_id,
            timestamp=time.time(),
            nonce=secrets.token_hex(16),
            payload=payload
        )


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
    reroute_count: int = 0
    total_latency_ms: float = 0.0
    failures: List[str] = field(default_factory=list)


# ── Simulation Engine ────────────────────────────────────────────

class Simulation:
    """
    Runs routing requests through the network and records results.
    
    Integrates:
    - Service grouping (SECTION 2)
    - Capacity filtering (SECTION 6)
    - Trust system (SECTION 9)
    - Self-healing (SECTION 11)
    - Observability (SECTION 13)
    """

    MAX_HOPS = 50  # Safety limit to prevent infinite loops

    def __init__(
        self,
        network: Network,
        engine: Optional[RoutingEngine] = None,
        service_grouping: Optional[ServiceGrouping] = None,
        trust_system: Optional[TrustSystem] = None,
        observability: Optional[Observability] = None
    ):
        self.network = network
        self.engine = engine or RoutingEngine()
        self.service_grouping = service_grouping or ServiceGrouping(network)
        self.trust_system = trust_system or TrustSystem()
        self.observability = observability or Observability()

    def route_request(
        self,
        start_node: Node,
        request: Request,
    ) -> RouteResult:
        """
        Execute a routing request from start_node toward request.target_vector.

        SECTION 2: Uses service grouping to determine target role.
        SECTION 6: Applies capacity filtering.
        SECTION 9: Updates trust based on outcomes.
        SECTION 11: Self-healing - reroutes on node failure.
        SECTION 13: Logs all decisions and metrics.

        Returns:
            A RouteResult with full path and hop details.
        """
        route_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        result = RouteResult(
            request=request,
            start_node_id=start_node.id,
        )

        # SECTION 2: Determine target service role
        target_role = self.service_grouping.determine_target_role(request.request_text)
        
        # Check if target section has any alive nodes
        if target_role and not self.service_grouping.has_alive_nodes(target_role):
            result.success = False
            result.final_node_id = start_node.id
            result.failures.append(f"Target section '{target_role}' has no alive nodes")
            self.observability.log_failure(start_node.id, f"No alive nodes in section {target_role}")
            return result

        current = start_node
        visited = set()
        target = request.target_vector
        last_hop_start_time = time.time()

        for step in range(self.MAX_HOPS):
            # Record visit
            result.path.append(current.id)
            visited.add(current.id)

            # SECTION 11: Check if current node failed during execution
            if not current.alive:
                result.failures.append(f"Node {current.id} failed during execution")
                self.observability.log_failure(current.id, "Node failed during execution")
                
                # Self-healing: Try to reroute
                result.reroute_count += 1
                self.observability.log_reroute(current.id, "unknown", "node_failure")
                
                # Find alternative node
                scored = self.engine.score_all_neighbors(current, target, target_role)
                # Remove visited nodes
                scored = [(n, s) for n, s in scored if n.id not in visited]
                
                if scored:
                    current = scored[0][0]
                    self.observability.log_reroute("failed_node", current.id, "self_healing")
                    continue
                else:
                    # No alternative available
                    result.success = False
                    result.final_node_id = current.id
                    break

            dist = euclidean_distance(current.vector, target)

            # SECTION 6: Score neighbors (capacity filter applied automatically)
            # SECTION 2: Filter by target role
            scored = self.engine.score_all_neighbors(current, target, target_role)
            
            score_records = [
                {
                    "neighbor": n.id,
                    "score": round(s, 4),
                    "load": n.load,
                    "capacity": n.capacity,
                    "trust": round(n.trust, 3),
                    "latency": n.latency,
                    "alive": n.alive,
                    "at_capacity": n.is_at_capacity(),
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

            # SECTION 13: Log routing decision
            chosen_node = None
            reason = ""
            
            if scored:
                chosen_node = scored[0][0]
                reason = f"Best score: {scored[0][1]:.4f}"
            else:
                reason = "No available candidates (all at capacity or wrong role)"
            
            self.observability.log_routing_decision(
                current, target, scored, chosen_node, reason
            )

            # Increment load on current node
            current.increment_load()
            self.observability.record_node_load(current.id, current.load)

            # Check termination
            if self.engine.has_reached_target(current, target):
                # Check if we're in the right service section
                if target_role and current.role != target_role:
                    # Not in target section, continue routing
                    pass
                else:
                    hop.is_terminal = True
                    result.hops.append(hop)
                    result.success = True
                    result.final_node_id = current.id
                    result.total_hops = step + 1
                    
                    # SECTION 9: Record success
                    hop_latency = (time.time() - last_hop_start_time) * 1000
                    self.trust_system.record_success(current, hop_latency)
                    result.total_latency_ms += hop_latency
                    break

            # Select next hop
            next_node = self.engine.select_next_hop(current, target, target_role)

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
                # No valid next hop → routing fails gracefully
                hop.failure = True
                result.hops.append(hop)
                result.success = False
                result.final_node_id = current.id
                result.total_hops = step + 1
                
                # SECTION 9: Record failure
                self.trust_system.record_failure(current)
                break

            hop.chosen_next = next_node.id
            result.hops.append(hop)

            # Cache route
            target_key = tuple(round(v, 4) for v in target)
            current.cache_route(target_key, next_node.id)

            # Record hop latency
            hop_latency = (time.time() - last_hop_start_time) * 1000
            result.total_latency_ms += hop_latency
            last_hop_start_time = time.time()

            # Forward
            current = next_node

        else:
            # Hit MAX_HOPS without termination
            result.success = False
            result.final_node_id = current.id
            result.total_hops = self.MAX_HOPS
            self.trust_system.record_failure(current)

        # SECTION 13: Log route completion
        route_metrics = RouteMetrics(
            route_id=route_id,
            start_node=start_node.id,
            final_node=result.final_node_id or start_node.id,
            success=result.success,
            total_hops=result.total_hops,
            total_latency_ms=result.total_latency_ms,
            reroute_count=result.reroute_count,
            failures=result.failures
        )
        self.observability.log_route_completion(route_metrics)

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
