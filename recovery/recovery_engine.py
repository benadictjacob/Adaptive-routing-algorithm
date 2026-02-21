"""
═══════════════════════════════════════════════════════════════════════
  AUTOMATED RECOVERY ENGINE (Section 4)
  Auto-restart pods, recreate deployments, reschedule workloads.
═══════════════════════════════════════════════════════════════════════

Zero manual intervention required.
Subscribes to FailureEvents from the FailureDetector.
"""

import time
import threading
from typing import List, Dict, Optional
from controller.cluster import (
    Cluster, KubeNode, Pod, Deployment,
    NodeStatus, PodStatus,
)
from controller.failure_detector import FailureEvent


class RecoveryAction:
    """Record of a recovery action taken."""

    def __init__(self, action_type: str, resource: str, message: str):
        self.action_type = action_type
        self.resource = resource
        self.message = message
        self.timestamp = time.time()
        self.success = True

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "resource": self.resource,
            "message": self.message,
            "timestamp": self.timestamp,
            "success": self.success,
        }


class RecoveryEngine:
    """
    Automated recovery engine.

    Handles:
      • Pod restart on crash/failure
      • Deployment replica reconciliation
      • Workload rescheduling from failed nodes
      • New node spin-up when capacity exhausted
    """

    def __init__(self, cluster: Cluster, max_restarts: int = 5):
        self.cluster = cluster
        self.max_restarts = max_restarts
        self.actions: List[RecoveryAction] = []
        self._lock = threading.Lock()

    def handle_failure(self, event: FailureEvent):
        """Central failure handler — routes to specific recovery logic."""
        if event.kind == "PodFailure":
            self._recover_pod(event)
        elif event.kind == "NodeNotReady":
            self._recover_node(event)
        elif event.kind == "ServiceUnreachable":
            self._recover_service(event)
        elif event.kind == "HighLatency":
            pass  # Latency events are informational — no auto-recovery

    # ── Pod Recovery ─────────────────────────────────────────────

    def _recover_pod(self, event: FailureEvent):
        """Restart a crashed/failed pod."""
        pod_name = event.resource_name
        pod = self._find_pod(pod_name)
        if not pod:
            return

        with self._lock:
            if pod.restart_count >= self.max_restarts:
                # Too many restarts — recreate the deployment
                if pod.deployment_name:
                    self._recreate_deployment_pod(pod)
                return

            # Restart the pod
            pod.start()
            action = RecoveryAction(
                "PodRestart",
                pod_name,
                f"Restarted pod '{pod_name}' (restart #{pod.restart_count})"
            )
            self.actions.append(action)
            self.cluster._log_event("Recovery", action.message)

    def _recreate_deployment_pod(self, failed_pod: Pod):
        """Remove a bad pod and create a fresh one for the deployment."""
        dep = self.cluster.get_deployment(failed_pod.deployment_name)
        if not dep:
            return

        # Remove the old pod from its node
        if failed_pod.node_name:
            node = self.cluster.get_node(failed_pod.node_name)
            if node:
                node.remove_pod(failed_pod.name)

        # Remove from deployment's pod list
        dep.pods = [p for p in dep.pods if p.name != failed_pod.name]

        # Create a replacement
        new_idx = len(dep.pods)
        new_pod = dep.create_pod(new_idx)
        self.cluster.schedule_pod(new_pod)

        action = RecoveryAction(
            "PodRecreated",
            new_pod.name,
            f"Replaced failed pod '{failed_pod.name}' with '{new_pod.name}' in deployment '{dep.name}'"
        )
        self.actions.append(action)
        self.cluster._log_event("Recovery", action.message)

    # ── Node Recovery ────────────────────────────────────────────

    def _recover_node(self, event: FailureEvent):
        """Reschedule all pods from a failed node to healthy nodes."""
        node_name = event.resource_name
        node = self.cluster.get_node(node_name)
        if not node:
            return

        with self._lock:
            orphaned_pods = list(node.pods)
            evicted_count = 0

            for pod in orphaned_pods:
                # Remove from failed node
                node.remove_pod(pod.name)
                pod.status = PodStatus.PENDING
                pod.health_ok = False

                # Reschedule to a healthy node
                new_node = self.cluster.schedule_pod(pod)
                if new_node:
                    evicted_count += 1

            action = RecoveryAction(
                "WorkloadRescheduled",
                node_name,
                f"Rescheduled {evicted_count}/{len(orphaned_pods)} pods from failed node '{node_name}'"
            )
            self.actions.append(action)
            self.cluster._log_event("Recovery", action.message, "Critical")

            # If no capacity left, spin up a new node
            ready_nodes = self.cluster.get_ready_nodes()
            if not any(n.can_schedule() for n in ready_nodes):
                self._spin_new_node()

    def _spin_new_node(self):
        """Spin up a new node when all existing nodes are at capacity."""
        node_num = len(self.cluster.nodes)
        new_node = KubeNode(
            name=f"node-{node_num:02d}",
            cpu_cores=4,
            memory_gb=8.0,
        )
        self.cluster.add_node(new_node)

        action = RecoveryAction(
            "NodeSpunUp",
            new_node.name,
            f"Spun up new node '{new_node.name}' to handle capacity shortage"
        )
        self.actions.append(action)
        self.cluster._log_event("Recovery", action.message, "Warning")

    # ── Service Recovery ─────────────────────────────────────────

    def _recover_service(self, event: FailureEvent):
        """Reconcile deployments to ensure services have healthy endpoints."""
        svc = self.cluster.get_service(event.resource_name)
        if not svc:
            return

        with self._lock:
            # Find all deployments that match this service's selector
            for dep in self.cluster.deployments:
                label_match = all(dep.labels.get(k) == v for k, v in svc.selector.items())
                if not label_match:
                    continue

                # Reconcile: ensure desired replicas are running
                self._reconcile_deployment(dep)

    def _reconcile_deployment(self, dep: Deployment):
        """Ensure a deployment has the correct number of running pods."""
        running = dep.get_running_pods()
        deficit = dep.replicas_desired - len(running)

        if deficit <= 0:
            return

        for i in range(deficit):
            new_idx = len(dep.pods)
            new_pod = dep.create_pod(new_idx)
            self.cluster.schedule_pod(new_pod)

        action = RecoveryAction(
            "DeploymentReconciled",
            dep.name,
            f"Reconciled deployment '{dep.name}': created {deficit} new pods (desired={dep.replicas_desired})"
        )
        self.actions.append(action)
        self.cluster._log_event("Recovery", action.message)

    # ── Reconcile All ────────────────────────────────────────────

    def reconcile_all(self):
        """Run reconciliation across all deployments."""
        for dep in self.cluster.deployments:
            self._reconcile_deployment(dep)

    # ── Utilities ────────────────────────────────────────────────

    def _find_pod(self, name: str) -> Optional[Pod]:
        for pod in self.cluster.all_pods():
            if pod.name == name:
                return pod
        return None

    def get_recovery_summary(self) -> Dict:
        by_type = {}
        for a in self.actions:
            by_type[a.action_type] = by_type.get(a.action_type, 0) + 1
        return {
            "total_actions": len(self.actions),
            "by_type": by_type,
            "recent": [a.to_dict() for a in self.actions[-20:]],
        }
