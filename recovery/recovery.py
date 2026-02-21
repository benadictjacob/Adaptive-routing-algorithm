"""
═══════════════════════════════════════════════════════════════════════
  RECOVERY ENGINE — Auto-Recovery + Disaster Recovery Mode
═══════════════════════════════════════════════════════════════════════

Restarts crashed containers, scales services, and handles cascade failures.
Supports priority-based multi-failure disaster recovery.
"""

import time
import docker
from typing import List, Dict
from monitor.monitor import FailureEvent


# Service priority (lower = more critical)
SERVICE_PRIORITY = {
    "healstack_api-gateway": 1,
    "healstack_auth-service": 2,
    "healstack_data-service": 3,
}


class RecoveryAction:
    def __init__(self, action_type: str, target: str, message: str, success: bool = True):
        self.action_type = action_type
        self.target = target
        self.message = message
        self.success = success
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "message": self.message,
            "success": self.success,
            "timestamp": self.timestamp,
        }


class RecoveryEngine:
    """
    Automatic recovery engine using Docker SDK.
    Includes disaster recovery mode for cascade failures.
    """

    def __init__(self):
        self.client = docker.from_env()
        self.actions: List[RecoveryAction] = []
        self.disaster_mode = False
        self._pending_failures: List[FailureEvent] = []

    def handle_failure(self, event: FailureEvent):
        """Route failure to recovery strategy. Triggers disaster mode if multiple failures."""
        self._pending_failures.append(event)

        # Enter disaster mode if 3+ failures pending
        if len(self._pending_failures) >= 3:
            self._disaster_recovery()
            return

        if event.event_type in ("ContainerCrash", "CrashLoop"):
            self._restart_service(event)
        elif event.event_type == "Unhealthy":
            self._restart_container(event)
        elif event.event_type == "ServiceDown":
            self._force_update_service(event)

    def _restart_container(self, event: FailureEvent):
        try:
            container = self.client.containers.get(event.container_name)
            container.restart(timeout=10)
            self.actions.append(RecoveryAction(
                "ContainerRestart", event.container_name,
                f"Restarted container '{event.container_name}'"
            ))
        except Exception as e:
            self.actions.append(RecoveryAction(
                "ContainerRestart", event.container_name,
                f"Failed: {str(e)[:100]}", success=False
            ))

    def _restart_service(self, event: FailureEvent):
        svc_name = event.service_name
        try:
            service = self.client.services.get(svc_name)
            service.force_update()
            self.actions.append(RecoveryAction(
                "ServiceForceUpdate", svc_name,
                f"Force-updated service '{svc_name}'"
            ))
        except Exception as e:
            self.actions.append(RecoveryAction(
                "ServiceForceUpdate", svc_name,
                f"Failed: {str(e)[:100]}", success=False
            ))

    def _force_update_service(self, event: FailureEvent):
        self._restart_service(event)

    def _disaster_recovery(self):
        """Priority-based multi-failure recovery."""
        self.disaster_mode = True
        self.actions.append(RecoveryAction(
            "DisasterMode", "cluster",
            f"🚨 DISASTER MODE: {len(self._pending_failures)} failures detected — prioritizing recovery"
        ))

        # Sort by priority (critical services first)
        sorted_failures = sorted(
            self._pending_failures,
            key=lambda f: SERVICE_PRIORITY.get(f.service_name, 99)
        )

        for event in sorted_failures:
            self._restart_service(event)
            time.sleep(1)  # Stagger to avoid overload

        self._pending_failures.clear()
        self.disaster_mode = False
        self.actions.append(RecoveryAction(
            "DisasterRecovery", "cluster",
            "Disaster recovery complete — all services restarted in priority order"
        ))

    def scale_service(self, service_name: str, replicas: int):
        try:
            service = self.client.services.get(service_name)
            service.scale(replicas)
            self.actions.append(RecoveryAction(
                "ServiceScale", service_name,
                f"Scaled '{service_name}' to {replicas} replicas"
            ))
        except Exception as e:
            self.actions.append(RecoveryAction(
                "ServiceScale", service_name,
                f"Failed: {str(e)[:100]}", success=False
            ))

    def get_summary(self) -> Dict:
        by_type = {}
        for a in self.actions:
            by_type[a.action_type] = by_type.get(a.action_type, 0) + 1
        return {
            "total_actions": len(self.actions),
            "disaster_mode": self.disaster_mode,
            "by_type": by_type,
            "recent": [a.to_dict() for a in self.actions[-20:]],
        }
