"""
═══════════════════════════════════════════════════════════════════════
  KUBERNETES CLUSTER MODEL
  Simulated Kubernetes primitives: Node, Pod, Deployment, Service, Cluster
═══════════════════════════════════════════════════════════════════════

This module models a Kubernetes cluster entirely in Python.
No real cluster is required — all state is held in memory.
"""

import time
import uuid
import random
import threading
import copy
from typing import List, Dict, Optional, Any
from enum import Enum
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════
#  ENUMS — Status types for all K8s primitives
# ═══════════════════════════════════════════════════════════════════

class NodeStatus(Enum):
    READY = "Ready"
    NOT_READY = "NotReady"
    DRAINING = "Draining"


class PodStatus(Enum):
    RUNNING = "Running"
    PENDING = "Pending"
    CRASH_LOOP = "CrashLoopBackOff"
    FAILED = "Failed"
    TERMINATING = "Terminating"
    SUCCEEDED = "Succeeded"


class ServiceType(Enum):
    CLUSTER_IP = "ClusterIP"
    NODE_PORT = "NodePort"
    LOAD_BALANCER = "LoadBalancer"


# ═══════════════════════════════════════════════════════════════════
#  POD — The smallest deployable unit
# ═══════════════════════════════════════════════════════════════════

class Pod:
    """Simulated Kubernetes Pod."""

    def __init__(
        self,
        name: str,
        image: str = "app:latest",
        labels: Optional[Dict[str, str]] = None,
        node_name: Optional[str] = None,
    ):
        self.name = name
        self.uid = str(uuid.uuid4())[:8]
        self.image = image
        self.labels = labels or {}
        self.node_name = node_name
        self.status = PodStatus.PENDING
        self.restart_count = 0
        self.created_at = time.time()
        self.last_health_check = 0.0
        self.health_ok = True
        self.latency_ms = random.uniform(5.0, 50.0)
        self.cpu_usage = random.uniform(0.05, 0.3)
        self.memory_mb = random.uniform(64, 256)
        self.deployment_name: Optional[str] = None

    def check_health(self) -> bool:
        """Simulate a /health endpoint check."""
        self.last_health_check = time.time()
        if self.status != PodStatus.RUNNING:
            self.health_ok = False
            return False
        # Simulate occasional latency spikes
        self.latency_ms = random.uniform(5.0, 80.0)
        self.health_ok = True
        return True

    def crash(self):
        """Simulate pod crash."""
        self.status = PodStatus.CRASH_LOOP
        self.health_ok = False
        self.restart_count += 1

    def fail(self):
        """Simulate permanent pod failure."""
        self.status = PodStatus.FAILED
        self.health_ok = False

    def start(self):
        """Start or restart the pod."""
        self.status = PodStatus.RUNNING
        self.health_ok = True
        self.latency_ms = random.uniform(5.0, 50.0)

    def terminate(self):
        """Graceful termination."""
        self.status = PodStatus.TERMINATING
        self.health_ok = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "uid": self.uid,
            "image": self.image,
            "labels": self.labels,
            "node_name": self.node_name,
            "status": self.status.value,
            "restart_count": self.restart_count,
            "health_ok": self.health_ok,
            "latency_ms": round(self.latency_ms, 1),
            "cpu_usage": round(self.cpu_usage, 3),
            "memory_mb": round(self.memory_mb, 1),
            "deployment": self.deployment_name,
            "created_at": self.created_at,
        }


# ═══════════════════════════════════════════════════════════════════
#  KUBE NODE — A worker machine in the cluster
# ═══════════════════════════════════════════════════════════════════

class KubeNode:
    """Simulated Kubernetes Worker Node."""

    def __init__(
        self,
        name: str,
        cpu_cores: int = 4,
        memory_gb: float = 8.0,
        max_pods: int = 30,
    ):
        self.name = name
        self.uid = str(uuid.uuid4())[:8]
        self.status = NodeStatus.READY
        self.cpu_cores = cpu_cores
        self.memory_gb = memory_gb
        self.max_pods = max_pods
        self.pods: List[Pod] = []
        self.created_at = time.time()
        self.conditions: Dict[str, bool] = {
            "Ready": True,
            "MemoryPressure": False,
            "DiskPressure": False,
            "PIDPressure": False,
        }

    @property
    def pod_count(self) -> int:
        return len(self.pods)

    @property
    def cpu_used(self) -> float:
        return sum(p.cpu_usage for p in self.pods if p.status == PodStatus.RUNNING)

    @property
    def memory_used(self) -> float:
        return sum(p.memory_mb for p in self.pods if p.status == PodStatus.RUNNING) / 1024

    def can_schedule(self) -> bool:
        """Can this node accept more pods?"""
        return (
            self.status == NodeStatus.READY
            and self.pod_count < self.max_pods
            and self.cpu_used < self.cpu_cores * 0.9
        )

    def add_pod(self, pod: Pod):
        pod.node_name = self.name
        pod.status = PodStatus.RUNNING
        pod.health_ok = True
        self.pods.append(pod)

    def remove_pod(self, pod_name: str) -> Optional[Pod]:
        for i, p in enumerate(self.pods):
            if p.name == pod_name:
                removed = self.pods.pop(i)
                removed.node_name = None
                return removed
        return None

    def mark_not_ready(self):
        """Simulate node failure."""
        self.status = NodeStatus.NOT_READY
        self.conditions["Ready"] = False
        # All pods on this node become unhealthy
        for pod in self.pods:
            pod.health_ok = False
            pod.status = PodStatus.FAILED

    def mark_ready(self):
        """Recover the node."""
        self.status = NodeStatus.READY
        self.conditions["Ready"] = True

    def drain(self):
        """Drain a node — mark pods for eviction."""
        self.status = NodeStatus.DRAINING
        for pod in self.pods:
            pod.status = PodStatus.TERMINATING
            pod.health_ok = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "uid": self.uid,
            "status": self.status.value,
            "cpu_cores": self.cpu_cores,
            "cpu_used": round(self.cpu_used, 2),
            "memory_gb": round(self.memory_gb, 2),
            "memory_used_gb": round(self.memory_used, 2),
            "pod_count": self.pod_count,
            "max_pods": self.max_pods,
            "conditions": self.conditions,
            "pods": [p.name for p in self.pods],
        }


# ═══════════════════════════════════════════════════════════════════
#  DEPLOYMENT — Manages desired pod replicas
# ═══════════════════════════════════════════════════════════════════

class Deployment:
    """Simulated Kubernetes Deployment."""

    def __init__(
        self,
        name: str,
        image: str = "app:latest",
        replicas: int = 3,
        labels: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.uid = str(uuid.uuid4())[:8]
        self.image = image
        self.replicas_desired = replicas
        self.labels = labels or {"app": name}
        self.pods: List[Pod] = []
        self.created_at = time.time()

    @property
    def replicas_ready(self) -> int:
        return sum(1 for p in self.pods if p.status == PodStatus.RUNNING and p.health_ok)

    @property
    def replicas_available(self) -> int:
        return sum(1 for p in self.pods if p.status == PodStatus.RUNNING)

    def create_pod(self, index: int) -> Pod:
        """Create a new pod for this deployment."""
        pod = Pod(
            name=f"{self.name}-pod-{index}",
            image=self.image,
            labels=dict(self.labels),
        )
        pod.deployment_name = self.name
        self.pods.append(pod)
        return pod

    def get_failed_pods(self) -> List[Pod]:
        return [
            p for p in self.pods
            if p.status in (PodStatus.FAILED, PodStatus.CRASH_LOOP)
        ]

    def get_running_pods(self) -> List[Pod]:
        return [p for p in self.pods if p.status == PodStatus.RUNNING]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "uid": self.uid,
            "image": self.image,
            "replicas_desired": self.replicas_desired,
            "replicas_ready": self.replicas_ready,
            "replicas_available": self.replicas_available,
            "labels": self.labels,
            "pods": [p.name for p in self.pods],
        }


# ═══════════════════════════════════════════════════════════════════
#  SERVICE — Load balances across healthy pods
# ═══════════════════════════════════════════════════════════════════

class Service:
    """Simulated Kubernetes Service."""

    def __init__(
        self,
        name: str,
        selector: Optional[Dict[str, str]] = None,
        port: int = 80,
        service_type: ServiceType = ServiceType.CLUSTER_IP,
    ):
        self.name = name
        self.uid = str(uuid.uuid4())[:8]
        self.selector = selector or {}
        self.port = port
        self.service_type = service_type
        self._rr_index = 0  # round-robin counter

    def get_healthy_endpoints(self, all_pods: List[Pod]) -> List[Pod]:
        """Find all healthy pods matching this service's selector."""
        endpoints = []
        for pod in all_pods:
            if pod.status != PodStatus.RUNNING or not pod.health_ok:
                continue
            # Check label selector match
            match = all(pod.labels.get(k) == v for k, v in self.selector.items())
            if match:
                endpoints.append(pod)
        return endpoints

    def route_request(self, all_pods: List[Pod]) -> Optional[Pod]:
        """Route a request to a healthy pod (round-robin)."""
        endpoints = self.get_healthy_endpoints(all_pods)
        if not endpoints:
            return None
        target = endpoints[self._rr_index % len(endpoints)]
        self._rr_index += 1
        return target

    def to_dict(self, all_pods: List[Pod]) -> dict:
        healthy = self.get_healthy_endpoints(all_pods)
        return {
            "name": self.name,
            "uid": self.uid,
            "selector": self.selector,
            "port": self.port,
            "type": self.service_type.value,
            "endpoints": [p.name for p in healthy],
            "endpoint_count": len(healthy),
        }


# ═══════════════════════════════════════════════════════════════════
#  CLUSTER — The complete Kubernetes cluster
# ═══════════════════════════════════════════════════════════════════

class Cluster:
    """
    Simulated Kubernetes Cluster.

    Holds all nodes, pods, deployments, and services.
    Provides scheduling, event logging, and state serialization.
    """

    def __init__(self, name: str = "k8s-cluster"):
        self.name = name
        self.nodes: List[KubeNode] = []
        self.deployments: List[Deployment] = []
        self.services: List[Service] = []
        self.event_log: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.created_at = time.time()

    # ── Node Management ──────────────────────────────────────────

    def add_node(self, node: KubeNode):
        with self._lock:
            self.nodes.append(node)
            self._log_event("NodeAdded", f"Node '{node.name}' joined the cluster")

    def get_node(self, name: str) -> Optional[KubeNode]:
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def get_ready_nodes(self) -> List[KubeNode]:
        return [n for n in self.nodes if n.status == NodeStatus.READY]

    # ── Pod Scheduling ───────────────────────────────────────────

    def schedule_pod(self, pod: Pod) -> Optional[KubeNode]:
        """Schedule a pod onto the least-loaded ready node."""
        with self._lock:
            candidates = [n for n in self.nodes if n.can_schedule()]
            if not candidates:
                self._log_event("ScheduleFailed", f"No node available for pod '{pod.name}'")
                return None
            # Least-loaded scheduling
            target = min(candidates, key=lambda n: n.pod_count)
            target.add_pod(pod)
            self._log_event("PodScheduled", f"Pod '{pod.name}' → Node '{target.name}'")
            return target

    def all_pods(self) -> List[Pod]:
        """Get all pods across all nodes."""
        pods = []
        for node in self.nodes:
            pods.extend(node.pods)
        # Also include unscheduled pods from deployments
        scheduled_names = {p.name for p in pods}
        for dep in self.deployments:
            for p in dep.pods:
                if p.name not in scheduled_names:
                    pods.append(p)
        return pods

    # ── Deployment Management ────────────────────────────────────

    def create_deployment(self, deployment: Deployment) -> List[Pod]:
        """Create a deployment and schedule its pods."""
        with self._lock:
            self.deployments.append(deployment)
            scheduled = []
            for i in range(deployment.replicas_desired):
                pod = deployment.create_pod(i)
                self._log_event("PodCreated", f"Pod '{pod.name}' created by deployment '{deployment.name}'")
                scheduled.append(pod)
            self._log_event("DeploymentCreated", f"Deployment '{deployment.name}' with {deployment.replicas_desired} replicas")

        # Schedule pods (outside lock to avoid deadlock)
        for pod in scheduled:
            self.schedule_pod(pod)
        return scheduled

    def get_deployment(self, name: str) -> Optional[Deployment]:
        for d in self.deployments:
            if d.name == name:
                return d
        return None

    # ── Service Management ───────────────────────────────────────

    def create_service(self, service: Service):
        with self._lock:
            self.services.append(service)
            endpoints = service.get_healthy_endpoints(self.all_pods())
            self._log_event(
                "ServiceCreated",
                f"Service '{service.name}' created with {len(endpoints)} endpoints"
            )

    def get_service(self, name: str) -> Optional[Service]:
        for s in self.services:
            if s.name == name:
                return s
        return None

    # ── Event Log ────────────────────────────────────────────────

    def _log_event(self, kind: str, message: str, severity: str = "Normal"):
        event = {
            "timestamp": time.time(),
            "kind": kind,
            "message": message,
            "severity": severity,
        }
        self.event_log.append(event)
        # Keep last 500 events
        if len(self.event_log) > 500:
            self.event_log = self.event_log[-500:]

    def get_recent_events(self, count: int = 50) -> List[Dict]:
        return list(reversed(self.event_log[-count:]))

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict:
        all_p = self.all_pods()
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "deployments": [d.to_dict() for d in self.deployments],
            "services": [s.to_dict(all_p) for s in self.services],
            "total_pods": len(all_p),
            "healthy_pods": sum(1 for p in all_p if p.health_ok and p.status == PodStatus.RUNNING),
            "total_nodes": len(self.nodes),
            "ready_nodes": len(self.get_ready_nodes()),
        }

    def get_snapshot_data(self) -> dict:
        """Get a full serializable snapshot of the cluster state."""
        return {
            "cluster_name": self.name,
            "timestamp": time.time(),
            "nodes": [
                {"name": n.name, "cpu_cores": n.cpu_cores, "memory_gb": n.memory_gb, "max_pods": n.max_pods}
                for n in self.nodes
            ],
            "deployments": [
                {
                    "name": d.name, "image": d.image,
                    "replicas": d.replicas_desired, "labels": d.labels,
                }
                for d in self.deployments
            ],
            "services": [
                {
                    "name": s.name, "selector": s.selector,
                    "port": s.port, "type": s.service_type.value,
                }
                for s in self.services
            ],
        }
