"""
SECTION 1 — NODE SERVICE ENDPOINTS

Nodes must expose:
- /execute
- /health
- /metrics

Nodes must run as independent processes or containers.
"""

import time
import json
import logging
from typing import Dict, Optional, Any
from flask import Flask, jsonify, request
from avrs.node import Node
from avrs.trust_system import TrustSystem


logger = logging.getLogger(__name__)


class NodeService:
    """
    HTTP service endpoints for a node.
    
    SECTION 1: Provides /execute, /health, /metrics endpoints.
    """
    
    def __init__(self, node: Node, trust_system: Optional[TrustSystem] = None):
        """
        Initialize node service.
        
        Args:
            node: Node instance to serve
            trust_system: Trust system for recording outcomes
        """
        self.node = node
        self.trust_system = trust_system
        self.app = Flask(__name__)
        self._setup_routes()
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
    
    def _setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """SECTION 8: Health check endpoint."""
            if self.node.alive:
                return jsonify({
                    "status": "healthy",
                    "node_id": self.node.id,
                    "alive": True,
                    "timestamp": time.time()
                }), 200
            else:
                return jsonify({
                    "status": "unhealthy",
                    "node_id": self.node.id,
                    "alive": False,
                    "timestamp": time.time()
                }), 503
        
        @self.app.route('/execute', methods=['POST'])
        def execute():
            """SECTION 1: Execute request endpoint."""
            if not self.node.alive:
                return jsonify({
                    "error": "Node is not alive",
                    "node_id": self.node.id
                }), 503
            
            start_time = time.time()
            self._request_count += 1
            
            try:
                data = request.get_json() or {}
                payload = data.get('payload', '')
                
                # Simulate execution
                execution_time = self._simulate_execution()
                
                # Increment load
                self.node.increment_load()
                
                # Record success
                self._success_count += 1
                response_time_ms = (time.time() - start_time) * 1000
                
                if self.trust_system:
                    self.trust_system.record_success(self.node, response_time_ms)
                
                return jsonify({
                    "status": "success",
                    "node_id": self.node.id,
                    "result": f"Executed: {payload}",
                    "execution_time_ms": execution_time,
                    "response_time_ms": response_time_ms,
                    "load": self.node.load,
                    "capacity": self.node.capacity
                }), 200
                
            except Exception as e:
                self._error_count += 1
                response_time_ms = (time.time() - start_time) * 1000
                
                if self.trust_system:
                    self.trust_system.record_error(self.node)
                
                logger.error(f"Error executing request on {self.node.id}: {e}")
                return jsonify({
                    "error": str(e),
                    "node_id": self.node.id,
                    "response_time_ms": response_time_ms
                }), 500
        
        @self.app.route('/metrics', methods=['GET'])
        def metrics():
            """SECTION 1: Metrics endpoint."""
            return jsonify({
                "node_id": self.node.id,
                "load": self.node.load,
                "capacity": self.node.capacity,
                "load_ratio": self.node.get_load_ratio(),
                "trust": self.node.trust,
                "latency": self.node.latency,
                "alive": self.node.alive,
                "role": self.node.role,
                "neighbors": len(self.node.neighbors),
                "alive_neighbors": len(self.node.get_alive_neighbors()),
                "requests_total": self._request_count,
                "requests_success": self._success_count,
                "requests_error": self._error_count,
                "success_rate": (
                    self._success_count / self._request_count * 100
                    if self._request_count > 0 else 0.0
                )
            }), 200
    
    def _simulate_execution(self) -> float:
        """
        Simulate request execution.
        
        Returns:
            Execution time in milliseconds
        """
        # Simulate variable execution time based on node latency
        base_time = self.node.latency / 1000.0  # Convert ms to seconds
        # Add some randomness
        import random
        execution_time = base_time + random.uniform(0, base_time * 0.5)
        time.sleep(execution_time)
        return execution_time * 1000
    
    def run(self, host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
        """
        Run the Flask service.
        
        Args:
            host: Host to bind to
            port: Port to bind to
            debug: Enable debug mode
        """
        # Extract port from node URL if available
        if ':' in self.node.url:
            try:
                port = int(self.node.url.split(':')[-1])
            except:
                pass
        
        logger.info(f"Starting node service for {self.node.id} on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug, threaded=True)


def create_node_service(node: Node, trust_system: Optional[TrustSystem] = None) -> NodeService:
    """
    Factory function to create a node service.
    
    Args:
        node: Node instance
        trust_system: Optional trust system
        
    Returns:
        NodeService instance
    """
    return NodeService(node, trust_system)
