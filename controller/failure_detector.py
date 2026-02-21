"""
═══════════════════════════════════════════════════════════════════════
  FAILURE DETECTION ENGINE (Section 3)
  Watches cluster state and emits structured failure events.
═══════════════════════════════════════════════════════════════════════

Detects:
  • Pod not running
  • Service unreachable (no healthy endpoints)
  • Node NotReady
  • Latency > threshold
"""

import time
import threading
from typing import List, Dict, Optional, Callable, Any
from controller.cluster import (
    Cluster, KubeNode, Pod, Deployment, Service,
    NodeStatus, PodStatus,
)


class FailureEvent:
    """Structured failure event emitted by the detector."""

    def __init__(
        self,
        kind: str,
        resource_type: str,
        resource_name: str,
        message: str,
        severity: str = "Warning",
        details: Optional[Dict] = None,
    ):
        self.kind = kind
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.message = message
        self.severity = severity
        self.details = details or {}
        self.timestamp = time.time()
        self.resolved = False

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
        }


class FailureDetector:
    """
    Continuously watches cluster state and emits FailureEvents.

    Callbacks registered via on_failure() are invoked immediately
    when a failure is detected, enabling zero-delay recovery.
    """

    def __init__(
        self,
        cluster: Cluster,
        latency_threshold_ms: float = 200.0,
        check_interval: float = 2.0,
    ):
        self.cluster = cluster
        self.latency_threshold_ms = latency_threshold_ms
        self.check_interval = check_interval
        self._callbacks: List[Callable[[FailureEvent], None]] = []
        self._active_failures: Dict[str, FailureEvent] = {}
        self.failure_history: List[FailureEvent] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── Callback Registration ────────────────────────────────────

    def on_failure(self, callback: Callable[[FailureEvent], None]):
        """Register a callback that fires when a failure is detected."""
        self._callbacks.append(callback)

    def _emit(self, event: FailureEvent):
        """Emit a failure event to all subscribers."""
        key = f"{event.resource_type}:{event.resource_name}:{event.kind}"
        if key in self._active_failures and not self._active_failures[key].resolved:
            return  # Already tracking this failure
        self._active_failures[key] = event
        self.failure_history.append(event)
        self.cluster._log_event(event.kind, event.message, event.severity)
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                self.cluster._log_event("CallbackError", str(e), "Error")

    # ── Detection Logic ──────────────────────────────────────────

    def detect_all(self) -> List[FailureEvent]:
        """Run all detection checks and return new failures."""
        events = []
        events.extend(self._detect_node_failures())
        events.extend(self._detect_pod_failures())
        events.extend(self._detect_service_failures())
        events.extend(self._detect_latency_violations())
        return events

    def _detect_node_failures(self) -> List[FailureEvent]:
        events = []
        for node in self.cluster.nodes:
            if node.status == NodeStatus.NOT_READY:
                ev = FailureEvent(
                    kind="NodeNotReady",
                    resource_type="Node",
                    resource_name=node.name,
                    message=f"Node '{node.name}' is NotReady — {node.pod_count} pods affected",
                    severity="Critical",
                    details={"pod_count": node.pod_count, "pods": [p.name for p in node.pods]},
                )
                events.append(ev)
                self._emit(ev)
        return events

    def _detect_pod_failures(self) -> List[FailureEvent]:
        events = []
        for pod in self.cluster.all_pods():
            if pod.status in (PodStatus.FAILED, PodStatus.CRASH_LOOP):
                ev = FailureEvent(
                    kind="PodFailure",
                    resource_type="Pod",
                    resource_name=pod.name,
                    message=f"Pod '{pod.name}' is {pod.status.value} (restarts: {pod.restart_count})",
                    severity="Warning" if pod.status == PodStatus.CRASH_LOOP else "Critical",
                    details={
                        "status": pod.status.value,
                        "restart_count": pod.restart_count,
                        "node": pod.node_name,
                        "deployment": pod.deployment_name,
                    },
                )
                events.append(ev)
                self._emit(ev)
        return events

    def _detect_service_failures(self) -> List[FailureEvent]:
        events = []
        all_pods = self.cluster.all_pods()
        for svc in self.cluster.services:
            endpoints = svc.get_healthy_endpoints(all_pods)
            if len(endpoints) == 0:
                ev = FailureEvent(
                    kind="ServiceUnreachable",
                    resource_type="Service",
                    resource_name=svc.name,
                    message=f"Service '{svc.name}' has 0 healthy endpoints",
                    severity="Critical",
                    details={"selector": svc.selector},
                )
                events.append(ev)
                self._emit(ev)
        return events

    def _detect_latency_violations(self) -> List[FailureEvent]:
        events = []
        for pod in self.cluster.all_pods():
            if pod.status == PodStatus.RUNNING and pod.latency_ms > self.latency_threshold_ms:
                ev = FailureEvent(
                    kind="HighLatency",
                    resource_type="Pod",
                    resource_name=pod.name,
                    message=f"Pod '{pod.name}' latency {pod.latency_ms:.0f}ms > threshold {self.latency_threshold_ms}ms",
                    severity="Warning",
                    details={"latency_ms": pod.latency_ms, "threshold": self.latency_threshold_ms},
                )
                events.append(ev)
                self._emit(ev)
        return events

    def resolve(self, resource_type: str, resource_name: str):
        """Mark an active failure as resolved."""
        for key, event in self._active_failures.items():
            if event.resource_type == resource_type and event.resource_name == resource_name:
                event.resolved = True

    # ── Continuous Monitoring Thread ─────────────────────────────

    def start(self):
        """Start continuous background detection."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            self.detect_all()
            time.sleep(self.check_interval)

    # ── Metrics ──────────────────────────────────────────────────

    def get_active_failures(self) -> List[Dict]:
        return [e.to_dict() for e in self._active_failures.values() if not e.resolved]

    def get_failure_summary(self) -> Dict:
        total = len(self.failure_history)
        active = sum(1 for e in self._active_failures.values() if not e.resolved)
        resolved = sum(1 for e in self._active_failures.values() if e.resolved)
        by_kind = {}
        for e in self.failure_history:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        return {
            "total_failures_detected": total,
            "active_failures": active,
            "resolved_failures": resolved,
            "by_kind": by_kind,
        }
