"""
═══════════════════════════════════════════════════════════════════════
  PROXY SERVER (Sections 1, 8)
  Health-aware reverse proxy with instant traffic rerouting.
═══════════════════════════════════════════════════════════════════════

Never forwards traffic to an unhealthy pod.
Reroutes instantly when a pod or service fails.
"""

import time
from typing import List, Dict, Optional
from controller.cluster import Cluster, Service, Pod, PodStatus


class ProxyRequest:
    """A simulated incoming traffic request."""

    def __init__(self, service_name: str, client_id: str = "client", payload: str = ""):
        self.service_name = service_name
        self.client_id = client_id
        self.payload = payload
        self.timestamp = time.time()


class ProxyResponse:
    """Result of routing a request through the proxy."""

    def __init__(
        self,
        success: bool,
        target_pod: Optional[str] = None,
        target_node: Optional[str] = None,
        latency_ms: float = 0.0,
        message: str = "",
        rerouted: bool = False,
    ):
        self.success = success
        self.target_pod = target_pod
        self.target_node = target_node
        self.latency_ms = latency_ms
        self.message = message
        self.rerouted = rerouted
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "target_pod": self.target_pod,
            "target_node": self.target_node,
            "latency_ms": round(self.latency_ms, 1),
            "message": self.message,
            "rerouted": self.rerouted,
            "timestamp": self.timestamp,
        }


class ProxyServer:
    """
    Health-aware reverse proxy.

    Routes traffic only to healthy service endpoints.
    Tracks request metrics per service.
    """

    def __init__(self, cluster: Cluster):
        self.cluster = cluster
        self.request_log: List[Dict] = []
        self.service_stats: Dict[str, Dict] = {}

    def route_request(self, req: ProxyRequest) -> ProxyResponse:
        """Route a request to a healthy pod via the service."""
        svc = self.cluster.get_service(req.service_name)
        if not svc:
            resp = ProxyResponse(
                success=False,
                message=f"Service '{req.service_name}' not found"
            )
            self._log(req, resp)
            return resp

        # Get a healthy pod via round-robin
        target = svc.route_request(self.cluster.all_pods())
        if not target:
            resp = ProxyResponse(
                success=False,
                message=f"No healthy endpoints for service '{req.service_name}'",
                rerouted=True,
            )
            self._log(req, resp)
            return resp

        # Simulate request processing
        target.cpu_usage += 0.01
        target.latency_ms += 2.0  # slight latency increase under load

        resp = ProxyResponse(
            success=True,
            target_pod=target.name,
            target_node=target.node_name,
            latency_ms=target.latency_ms,
            message=f"Request routed to pod '{target.name}' on node '{target.node_name}'"
        )
        self._log(req, resp)
        return resp

    def route_batch(self, service_name: str, count: int = 10) -> List[ProxyResponse]:
        """Route multiple requests for stress testing."""
        results = []
        for i in range(count):
            req = ProxyRequest(service_name, client_id=f"batch-{i}")
            results.append(self.route_request(req))
        return results

    def _log(self, req: ProxyRequest, resp: ProxyResponse):
        entry = {
            "service": req.service_name,
            "client": req.client_id,
            "success": resp.success,
            "target_pod": resp.target_pod,
            "latency_ms": resp.latency_ms,
            "rerouted": resp.rerouted,
            "timestamp": resp.timestamp,
        }
        self.request_log.append(entry)
        # Keep last 1000 entries
        if len(self.request_log) > 1000:
            self.request_log = self.request_log[-1000:]

        # Update service stats
        svc = req.service_name
        if svc not in self.service_stats:
            self.service_stats[svc] = {"total": 0, "success": 0, "failed": 0, "rerouted": 0, "total_latency": 0.0}
        self.service_stats[svc]["total"] += 1
        if resp.success:
            self.service_stats[svc]["success"] += 1
            self.service_stats[svc]["total_latency"] += resp.latency_ms
        else:
            self.service_stats[svc]["failed"] += 1
        if resp.rerouted:
            self.service_stats[svc]["rerouted"] += 1

    def get_service_stats(self, service_name: str) -> Dict:
        stats = self.service_stats.get(service_name, {})
        if not stats:
            return {"error": "No stats available"}
        avg_lat = (stats["total_latency"] / stats["success"]) if stats["success"] > 0 else 0
        return {
            "service": service_name,
            "total_requests": stats["total"],
            "successful": stats["success"],
            "failed": stats["failed"],
            "rerouted": stats["rerouted"],
            "success_rate_pct": round(stats["success"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
            "avg_latency_ms": round(avg_lat, 1),
        }

    def get_all_stats(self) -> Dict:
        return {svc: self.get_service_stats(svc) for svc in self.service_stats}
