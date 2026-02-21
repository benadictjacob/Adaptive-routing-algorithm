"""
═══════════════════════════════════════════════════════════════════════
  DISASTER RESTORATION ENGINE (Section 6)
  Full cluster rebuild from a saved snapshot.
═══════════════════════════════════════════════════════════════════════

Retrieves the latest snapshot, rebuilds nodes, deployments,
services, and restores routing — fully automated.
"""

import time
from typing import Dict, Optional
from controller.cluster import (
    Cluster, KubeNode, Pod, Deployment, Service,
    ServiceType,
)
from state_store.snapshot_engine import SnapshotEngine


class DisasterRestore:
    """
    Full cluster restoration from a snapshot.

    Rebuilds:
      • All nodes
      • All deployments (and their pods)
      • All services
    """

    def __init__(self, snapshot_engine: SnapshotEngine):
        self.snapshot_engine = snapshot_engine
        self.restore_history = []

    def restore_from_latest(self) -> Dict:
        """Restore the cluster from the most recent snapshot."""
        snapshot = self.snapshot_engine.get_latest_snapshot()
        if not snapshot:
            return {"success": False, "message": "No snapshot available"}
        return self.restore_from_data(snapshot)

    def restore_from_file(self, filename: str) -> Dict:
        """Restore the cluster from a specific snapshot file."""
        snapshot = self.snapshot_engine.load_snapshot(filename)
        if not snapshot:
            return {"success": False, "message": f"Snapshot '{filename}' not found"}
        return self.restore_from_data(snapshot)

    def restore_from_data(self, snapshot: Dict) -> Dict:
        """
        Rebuild the entire cluster from snapshot data.
        This is a DESTRUCTIVE operation — the current cluster state is wiped.
        """
        cluster = self.snapshot_engine.cluster
        t0 = time.time()

        # ── Step 1: Wipe current state ───────────────────────────
        cluster.nodes.clear()
        cluster.deployments.clear()
        cluster.services.clear()
        cluster._log_event("DisasterRestore", "Wiping current cluster state", "Critical")

        # ── Step 2: Rebuild nodes ────────────────────────────────
        for node_data in snapshot.get("nodes", []):
            node = KubeNode(
                name=node_data["name"],
                cpu_cores=node_data.get("cpu_cores", 4),
                memory_gb=node_data.get("memory_gb", 8.0),
                max_pods=node_data.get("max_pods", 30),
            )
            cluster.add_node(node)

        # ── Step 3: Rebuild deployments and schedule pods ────────
        for dep_data in snapshot.get("deployments", []):
            dep = Deployment(
                name=dep_data["name"],
                image=dep_data.get("image", "app:latest"),
                replicas=dep_data.get("replicas", 3),
                labels=dep_data.get("labels", {}),
            )
            cluster.create_deployment(dep)

        # ── Step 4: Rebuild services ─────────────────────────────
        for svc_data in snapshot.get("services", []):
            svc_type = ServiceType.CLUSTER_IP
            if svc_data.get("type") == "LoadBalancer":
                svc_type = ServiceType.LOAD_BALANCER
            elif svc_data.get("type") == "NodePort":
                svc_type = ServiceType.NODE_PORT

            svc = Service(
                name=svc_data["name"],
                selector=svc_data.get("selector", {}),
                port=svc_data.get("port", 80),
                service_type=svc_type,
            )
            cluster.create_service(svc)

        elapsed = time.time() - t0

        result = {
            "success": True,
            "message": "Cluster fully restored from snapshot",
            "nodes_restored": len(cluster.nodes),
            "deployments_restored": len(cluster.deployments),
            "services_restored": len(cluster.services),
            "pods_scheduled": len(cluster.all_pods()),
            "restore_time_ms": round(elapsed * 1000, 1),
            "snapshot_timestamp": snapshot.get("timestamp", 0),
        }

        self.restore_history.append(result)
        cluster._log_event("DisasterRestore", f"Full restore complete in {result['restore_time_ms']}ms", "Critical")
        return result

    def get_restore_history(self):
        return self.restore_history
