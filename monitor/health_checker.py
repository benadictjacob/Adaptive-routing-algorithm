"""
═══════════════════════════════════════════════════════════════════════
  HEALTH CHECKER (Section 7, 9)
  Periodic health polling, latency tracking, metrics collection.
═══════════════════════════════════════════════════════════════════════

Polls simulated /health endpoints on all pods.
Tracks per-pod and per-service metrics over time.
"""

import time
import threading
from typing import List, Dict, Optional
from collections import defaultdict
from controller.cluster import Cluster, Pod, PodStatus


class HealthRecord:
    """Time-series health record for a single pod."""

    def __init__(self, pod_name: str, max_history: int = 100):
        self.pod_name = pod_name
        self.checks: List[Dict] = []
        self.max_history = max_history
        self.total_checks = 0
        self.total_healthy = 0
        self.total_unhealthy = 0

    def record(self, healthy: bool, latency_ms: float):
        self.total_checks += 1
        if healthy:
            self.total_healthy += 1
        else:
            self.total_unhealthy += 1
        self.checks.append({
            "timestamp": time.time(),
            "healthy": healthy,
            "latency_ms": round(latency_ms, 1),
        })
        if len(self.checks) > self.max_history:
            self.checks = self.checks[-self.max_history:]

    @property
    def uptime_pct(self) -> float:
        if self.total_checks == 0:
            return 100.0
        return round(self.total_healthy / self.total_checks * 100, 1)

    @property
    def avg_latency(self) -> float:
        recent = [c["latency_ms"] for c in self.checks[-20:] if c["healthy"]]
        return round(sum(recent) / len(recent), 1) if recent else 0.0

    def to_dict(self) -> dict:
        return {
            "pod_name": self.pod_name,
            "total_checks": self.total_checks,
            "uptime_pct": self.uptime_pct,
            "avg_latency_ms": self.avg_latency,
            "recent": self.checks[-10:],
        }


class HealthChecker:
    """
    Periodically polls pod /health endpoints and tracks metrics.

    Runs in a background thread. Results are queryable via API.
    """

    def __init__(self, cluster: Cluster, interval: float = 3.0):
        self.cluster = cluster
        self.interval = interval
        self.records: Dict[str, HealthRecord] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.last_check_time = 0.0
        # Service-level aggregates
        self.service_metrics: Dict[str, Dict] = defaultdict(lambda: {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "avg_latency_ms": 0.0,
        })

    def check_all(self):
        """Run health checks on every pod in the cluster."""
        self.last_check_time = time.time()
        for pod in self.cluster.all_pods():
            # Get or create record
            if pod.name not in self.records:
                self.records[pod.name] = HealthRecord(pod.name)

            # Run simulated health check
            healthy = pod.check_health()
            latency = pod.latency_ms if healthy else 0.0
            self.records[pod.name].record(healthy, latency)

    def get_pod_health(self, pod_name: str) -> Optional[Dict]:
        rec = self.records.get(pod_name)
        return rec.to_dict() if rec else None

    def get_all_health(self) -> List[Dict]:
        return [rec.to_dict() for rec in self.records.values()]

    def get_cluster_health_summary(self) -> Dict:
        """Aggregate health across the entire cluster."""
        all_pods = self.cluster.all_pods()
        total = len(all_pods)
        healthy = sum(1 for p in all_pods if p.health_ok and p.status == PodStatus.RUNNING)
        unhealthy = total - healthy

        all_latencies = []
        for rec in self.records.values():
            recent = [c["latency_ms"] for c in rec.checks[-5:] if c["healthy"]]
            all_latencies.extend(recent)

        avg_latency = round(sum(all_latencies) / len(all_latencies), 1) if all_latencies else 0.0

        # Per-node health
        node_health = {}
        for node in self.cluster.nodes:
            running = sum(1 for p in node.pods if p.status == PodStatus.RUNNING and p.health_ok)
            node_health[node.name] = {
                "status": node.status.value,
                "healthy_pods": running,
                "total_pods": node.pod_count,
            }

        return {
            "total_pods": total,
            "healthy_pods": healthy,
            "unhealthy_pods": unhealthy,
            "cluster_health_pct": round(healthy / total * 100, 1) if total > 0 else 100.0,
            "avg_latency_ms": avg_latency,
            "node_health": node_health,
            "last_check": self.last_check_time,
        }

    # ── Background Runner ────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            self.check_all()
            time.sleep(self.interval)
