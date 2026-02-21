"""
SECTION 9 — TRUST SYSTEM

Trust must dynamically update.

Decrease trust if:
- node fails request
- slow response
- returns error

Increase trust if:
- successful execution
- low latency
- consistent responses

Routing must naturally avoid low trust nodes.
"""

import time
import logging
from typing import Optional
from avrs.node import Node


logger = logging.getLogger(__name__)


class TrustSystem:
    """
    Manages dynamic trust updates for nodes.
    
    SECTION 9: Updates trust based on node performance.
    """
    
    # Trust adjustment amounts
    TRUST_DECREASE_FAILURE = 0.3
    TRUST_DECREASE_SLOW = 0.1
    TRUST_DECREASE_ERROR = 0.2
    TRUST_INCREASE_SUCCESS = 0.05
    TRUST_INCREASE_FAST = 0.02
    
    # Thresholds
    SLOW_RESPONSE_MS = 500.0  # Response slower than this is considered slow
    FAST_RESPONSE_MS = 50.0   # Response faster than this gets bonus
    
    def __init__(
        self,
        min_trust: float = 0.0,
        max_trust: float = 1.0,
        initial_trust: float = 1.0
    ):
        """
        Initialize trust system.
        
        Args:
            min_trust: Minimum trust value
            max_trust: Maximum trust value
            initial_trust: Initial trust for new nodes
        """
        self.min_trust = min_trust
        self.max_trust = max_trust
        self.initial_trust = initial_trust
    
    def record_success(self, node: Node, response_time_ms: Optional[float] = None):
        """
        Record successful execution.
        
        SECTION 9: Increases trust for successful execution.
        Additional bonus for fast responses.
        
        Args:
            node: Node that succeeded
            response_time_ms: Response time in milliseconds (optional)
        """
        old_trust = node.trust
        
        # Base increase for success
        increase = self.TRUST_INCREASE_SUCCESS
        
        # Bonus for fast response
        if response_time_ms is not None and response_time_ms < self.FAST_RESPONSE_MS:
            increase += self.TRUST_INCREASE_FAST
        
        node.trust = min(self.max_trust, node.trust + increase)
        
        if node.trust != old_trust:
            logger.debug(
                f"Node {node.id} trust increased: {old_trust:.3f} -> {node.trust:.3f} "
                f"(success, response_time={response_time_ms}ms)"
            )
    
    def record_failure(self, node: Node):
        """
        Record request failure.
        
        SECTION 9: Decreases trust when node fails request.
        
        Args:
            node: Node that failed
        """
        old_trust = node.trust
        node.trust = max(self.min_trust, node.trust - self.TRUST_DECREASE_FAILURE)
        
        logger.warning(
            f"Node {node.id} trust decreased: {old_trust:.3f} -> {node.trust:.3f} (failure)"
        )
    
    def record_error(self, node: Node):
        """
        Record error response.
        
        SECTION 9: Decreases trust when node returns error.
        
        Args:
            node: Node that returned error
        """
        old_trust = node.trust
        node.trust = max(self.min_trust, node.trust - self.TRUST_DECREASE_ERROR)
        
        logger.warning(
            f"Node {node.id} trust decreased: {old_trust:.3f} -> {node.trust:.3f} (error)"
        )
    
    def record_slow_response(self, node: Node, response_time_ms: float):
        """
        Record slow response.
        
        SECTION 9: Decreases trust for slow responses.
        
        Args:
            node: Node with slow response
            response_time_ms: Response time in milliseconds
        """
        if response_time_ms < self.SLOW_RESPONSE_MS:
            return  # Not slow enough
        
        old_trust = node.trust
        node.trust = max(self.min_trust, node.trust - self.TRUST_DECREASE_SLOW)
        
        logger.debug(
            f"Node {node.id} trust decreased: {old_trust:.3f} -> {node.trust:.3f} "
            f"(slow response: {response_time_ms}ms)"
        )
    
    def reset_trust(self, node: Node, trust: Optional[float] = None):
        """
        Reset node trust to initial or specified value.
        
        Args:
            node: Node to reset
            trust: Trust value to set (uses initial_trust if None)
        """
        node.trust = trust if trust is not None else self.initial_trust
        logger.info(f"Node {node.id} trust reset to {node.trust:.3f}")
    
    def get_trust(self, node: Node) -> float:
        """Get current trust value for a node."""
        return node.trust
    
    def is_trusted(self, node: Node, threshold: float = 0.3) -> bool:
        """
        Check if node trust is above threshold.
        
        Args:
            node: Node to check
            threshold: Minimum trust threshold
            
        Returns:
            True if node trust >= threshold
        """
        return node.trust >= threshold
