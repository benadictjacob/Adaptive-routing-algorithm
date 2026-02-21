"""
SECTION 13 — OBSERVABILITY

System must log:
- routing decisions
- score calculations
- failures
- reroutes
- security blocks

Metrics must include:
- average hops
- success rate
- reroute count
- latency
- load distribution
"""

import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict, deque
from avrs.node import Node


logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Record of a single routing decision."""
    timestamp: float
    current_node: str
    target_vector: List[float]
    candidates: List[Dict]  # List of {node_id, score, load, trust, latency}
    chosen_node: Optional[str]
    reason: str  # Why this node was chosen or why routing failed


@dataclass
class RouteMetrics:
    """Metrics for a completed route."""
    route_id: str
    start_node: str
    final_node: str
    success: bool
    total_hops: int
    total_latency_ms: float
    reroute_count: int = 0
    failures: List[str] = field(default_factory=list)


class Observability:
    """
    Comprehensive logging and metrics collection.
    
    SECTION 13: Logs routing decisions, scores, failures, reroutes, and security blocks.
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize observability system.
        
        Args:
            max_history: Maximum number of records to keep in history
        """
        self.max_history = max_history
        self.routing_decisions: deque = deque(maxlen=max_history)
        self.route_metrics: deque = deque(maxlen=max_history)
        self.security_blocks: deque = deque(maxlen=max_history)
        self.failures: deque = deque(maxlen=max_history)
        self.reroutes: deque = deque(maxlen=max_history)
        
        # Aggregate metrics
        self.total_requests = 0
        self.successful_routes = 0
        self.failed_routes = 0
        self.total_hops = 0
        self.total_reroutes = 0
        self.total_latency_ms = 0.0
        
        # Per-node metrics
        self.node_request_counts: Dict[str, int] = defaultdict(int)
        self.node_success_counts: Dict[str, int] = defaultdict(int)
        self.node_failure_counts: Dict[str, int] = defaultdict(int)
        self.node_load_samples: Dict[str, List[float]] = defaultdict(list)
    
    def log_routing_decision(
        self,
        current_node: Node,
        target_vector: List[float],
        candidates: List[tuple[Node, float]],
        chosen_node: Optional[Node],
        reason: str = ""
    ):
        """
        Log a routing decision.
        
        SECTION 13: Records routing decisions with score calculations.
        
        Args:
            current_node: Node making the decision
            target_vector: Target vector
            candidates: List of (node, score) tuples
            chosen_node: Selected next hop (None if failed)
            reason: Reason for selection or failure
        """
        decision = RoutingDecision(
            timestamp=time.time(),
            current_node=current_node.id,
            target_vector=[round(v, 4) for v in target_vector],
            candidates=[
                {
                    "node_id": node.id,
                    "score": round(score, 4),
                    "load": node.load,
                    "capacity": node.capacity,
                    "trust": round(node.trust, 3),
                    "latency": node.latency,
                    "alive": node.alive,
                    "at_capacity": node.is_at_capacity()
                }
                for node, score in candidates
            ],
            chosen_node=chosen_node.id if chosen_node else None,
            reason=reason
        )
        
        self.routing_decisions.append(decision)
        
        logger.debug(
            f"Routing decision at {current_node.id}: "
            f"chosen={chosen_node.id if chosen_node else 'NONE'}, "
            f"candidates={len(candidates)}, reason={reason}"
        )
    
    def log_route_completion(self, metrics: RouteMetrics):
        """
        Log completion of a route.
        
        Args:
            metrics: Route metrics
        """
        self.route_metrics.append(metrics)
        self.total_requests += 1
        
        if metrics.success:
            self.successful_routes += 1
            self.node_success_counts[metrics.final_node] += 1
        else:
            self.failed_routes += 1
            self.node_failure_counts[metrics.final_node] += 1
        
        self.total_hops += metrics.total_hops
        self.total_reroutes += metrics.reroute_count
        self.total_latency_ms += metrics.total_latency_ms
        
        # Track node request counts
        self.node_request_counts[metrics.start_node] += 1
        if metrics.final_node:
            self.node_request_counts[metrics.final_node] += 1
        
        logger.info(
            f"Route completed: {metrics.route_id} "
            f"({metrics.start_node} -> {metrics.final_node}), "
            f"success={metrics.success}, hops={metrics.total_hops}, "
            f"reroutes={metrics.reroute_count}"
        )
    
    def log_failure(self, node_id: str, reason: str, context: Optional[Dict] = None):
        """
        Log a failure event.
        
        SECTION 13: Records failures.
        
        Args:
            node_id: Node that failed
            reason: Failure reason
            context: Additional context
        """
        failure_record = {
            "timestamp": time.time(),
            "node_id": node_id,
            "reason": reason,
            "context": context or {}
        }
        self.failures.append(failure_record)
        self.node_failure_counts[node_id] += 1
        
        logger.warning(f"Failure at {node_id}: {reason}")
    
    def log_reroute(self, original_node: str, new_node: str, reason: str):
        """
        Log a reroute event.
        
        SECTION 13: Records reroutes.
        
        Args:
            original_node: Original target node
            new_node: New target node
            reason: Reason for reroute
        """
        reroute_record = {
            "timestamp": time.time(),
            "original_node": original_node,
            "new_node": new_node,
            "reason": reason
        }
        self.reroutes.append(reroute_record)
        self.total_reroutes += 1
        
        logger.info(f"Reroute: {original_node} -> {new_node} (reason: {reason})")
    
    def log_security_block(self, request_id: str, reason: str, client_id: Optional[str] = None):
        """
        Log a security block event.
        
        SECTION 13: Records security blocks.
        
        Args:
            request_id: Request identifier
            reason: Block reason
            client_id: Client identifier (optional)
        """
        block_record = {
            "timestamp": time.time(),
            "request_id": request_id,
            "client_id": client_id,
            "reason": reason
        }
        self.security_blocks.append(block_record)
        
        logger.warning(f"Security block: {request_id} (reason: {reason})")
    
    def record_node_load(self, node_id: str, load: float):
        """
        Record node load sample.
        
        Args:
            node_id: Node identifier
            load: Current load value
        """
        samples = self.node_load_samples[node_id]
        samples.append(load)
        # Keep only recent samples
        if len(samples) > 100:
            samples.pop(0)
    
    def get_metrics_summary(self) -> Dict:
        """
        Get summary of all metrics.
        
        SECTION 13: Returns average hops, success rate, reroute count, latency, load distribution.
        
        Returns:
            Dictionary with metrics summary
        """
        success_rate = (
            (self.successful_routes / self.total_requests * 100)
            if self.total_requests > 0 else 0.0
        )
        
        avg_hops = (
            (self.total_hops / self.total_requests)
            if self.total_requests > 0 else 0.0
        )
        
        avg_latency_ms = (
            (self.total_latency_ms / self.total_requests)
            if self.total_requests > 0 else 0.0
        )
        
        avg_reroutes = (
            (self.total_reroutes / self.total_requests)
            if self.total_requests > 0 else 0.0
        )
        
        # Load distribution (average load per node)
        load_distribution = {}
        for node_id, samples in self.node_load_samples.items():
            if samples:
                load_distribution[node_id] = {
                    "avg": sum(samples) / len(samples),
                    "max": max(samples),
                    "min": min(samples),
                    "samples": len(samples)
                }
        
        return {
            "total_requests": self.total_requests,
            "successful_routes": self.successful_routes,
            "failed_routes": self.failed_routes,
            "success_rate_percent": round(success_rate, 2),
            "average_hops": round(avg_hops, 2),
            "average_latency_ms": round(avg_latency_ms, 2),
            "total_reroutes": self.total_reroutes,
            "average_reroutes_per_request": round(avg_reroutes, 2),
            "load_distribution": load_distribution,
            "node_request_counts": dict(self.node_request_counts),
            "node_success_counts": dict(self.node_success_counts),
            "node_failure_counts": dict(self.node_failure_counts)
        }
    
    def get_recent_decisions(self, limit: int = 10) -> List[RoutingDecision]:
        """Get recent routing decisions."""
        return list(self.routing_decisions)[-limit:]
    
    def get_recent_failures(self, limit: int = 10) -> List[Dict]:
        """Get recent failures."""
        return list(self.failures)[-limit:]
    
    def get_recent_reroutes(self, limit: int = 10) -> List[Dict]:
        """Get recent reroutes."""
        return list(self.reroutes)[-limit:]
    
    def reset(self):
        """Reset all metrics."""
        self.routing_decisions.clear()
        self.route_metrics.clear()
        self.security_blocks.clear()
        self.failures.clear()
        self.reroutes.clear()
        self.total_requests = 0
        self.successful_routes = 0
        self.failed_routes = 0
        self.total_hops = 0
        self.total_reroutes = 0
        self.total_latency_ms = 0.0
        self.node_request_counts.clear()
        self.node_success_counts.clear()
        self.node_failure_counts.clear()
        self.node_load_samples.clear()
