"""
SECTION 8 — HEALTH MONITORING

Router must continuously poll nodes:
- /health endpoint

If node does not respond:
- mark node.alive = False

Dead nodes must never be selected.
"""

import time
import threading
import logging
from typing import Dict, Optional
from avrs.node import Node
from avrs.network import Network


logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Continuously monitors node health by polling /health endpoints.
    
    SECTION 8: Marks nodes as dead if they don't respond to health checks.
    """
    
    def __init__(
        self,
        network: Network,
        poll_interval: float = 5.0,
        timeout: float = 2.0,
        max_failures: int = 3
    ):
        """
        Initialize health monitor.
        
        Args:
            network: Network to monitor
            poll_interval: Seconds between health checks
            timeout: Timeout for health check requests
            max_failures: Number of consecutive failures before marking node dead
        """
        self.network = network
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.max_failures = max_failures
        self._failure_counts: Dict[str, int] = {}  # node_id -> consecutive failures
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def start(self):
        """Start the health monitoring thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Health monitor started")
    
    def stop(self):
        """Stop the health monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Health monitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_all_nodes()
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
            
            time.sleep(self.poll_interval)
    
    def _check_all_nodes(self):
        """Check health of all nodes in the network."""
        for node in self.network.nodes:
            self._check_node_health(node)
    
    def _check_node_health(self, node: Node):
        """
        Check health of a single node.
        
        SECTION 8: Polls /health endpoint and marks node as dead if it fails.
        
        Args:
            node: Node to check
        """
        try:
            # In simulation mode, we check if node is marked as alive
            # In production, this would make an HTTP request to node.url/health
            health_ok = self._simulate_health_check(node)
            
            with self._lock:
                if health_ok:
                    # Reset failure count on success
                    self._failure_counts[node.id] = 0
                    # If node was dead but now responding, mark as recovered
                    if not node.alive:
                        node.recover()
                        logger.info(f"Node {node.id} recovered")
                else:
                    # Increment failure count
                    failures = self._failure_counts.get(node.id, 0) + 1
                    self._failure_counts[node.id] = failures
                    
                    if failures >= self.max_failures:
                        if node.alive:
                            node.fail()
                            logger.warning(f"Node {node.id} marked as dead after {failures} failures")
        except Exception as e:
            logger.error(f"Error checking health of node {node.id}: {e}")
            with self._lock:
                failures = self._failure_counts.get(node.id, 0) + 1
                self._failure_counts[node.id] = failures
                if failures >= self.max_failures and node.alive:
                    node.fail()
                    logger.warning(f"Node {node.id} marked as dead due to health check error")
    
    def _simulate_health_check(self, node: Node) -> bool:
        """
        Simulate health check for a node.
        
        In production, this would make an actual HTTP request:
        - GET {node.url}/health
        - Expect 200 OK response
        
        Args:
            node: Node to check
            
        Returns:
            True if node is healthy, False otherwise
        """
        # In simulation, if node.alive is False, it's already marked as dead
        # In production mode, this would be an actual HTTP request
        if not node.alive:
            return False
        
        # Simulate network latency
        time.sleep(0.01)  # 10ms simulated latency
        
        # For now, return True if node is marked alive
        # In production, this would check actual HTTP response
        return True
    
    def check_node_now(self, node: Node) -> bool:
        """
        Immediately check a node's health (synchronous).
        
        Args:
            node: Node to check
            
        Returns:
            True if node is healthy
        """
        return self._simulate_health_check(node)
    
    def get_failure_count(self, node_id: str) -> int:
        """Get consecutive failure count for a node."""
        return self._failure_counts.get(node_id, 0)
    
    def reset_failure_count(self, node_id: str):
        """Reset failure count for a node."""
        self._failure_counts[node_id] = 0
