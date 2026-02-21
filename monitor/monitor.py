"""
═══════════════════════════════════════════════════════════════════════
  DOCKER HEALTH MONITOR — Real Container Monitoring via Docker SDK
═══════════════════════════════════════════════════════════════════════

Polls real Docker containers using the Docker socket.
Detects crashes, restarts, unhealthy state, and timeouts.
"""

import time
import threading
import docker
import urllib.request
import json
from typing import List, Dict, Optional, Callable


class ContainerState:
    """Snapshot of a container's state at a point in time."""

    def __init__(self, container):
        self.id = container.short_id
        self.name = container.name
        self.status = container.status  # running, exited, restarting, etc.
        self.image = container.image.tags[0] if container.image.tags else "unknown"
        attrs = container.attrs
        self.health = "unknown"
        health_state = attrs.get("State", {}).get("Health", {})
        if health_state:
            self.health = health_state.get("Status", "unknown")
        restart_count = attrs.get("RestartCount", 0)
        self.restart_count = restart_count
        self.started_at = attrs.get("State", {}).get("StartedAt", "")
        self.exit_code = attrs.get("State", {}).get("ExitCode", 0)
        self.service_name = container.labels.get("com.docker.swarm.service.name", "")
        self.node_id = container.labels.get("com.docker.swarm.node.id", "")
        self.task_id = container.labels.get("com.docker.swarm.task.id", "")
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "health": self.health,
            "image": self.image,
            "restart_count": self.restart_count,
            "exit_code": self.exit_code,
            "service_name": self.service_name,
            "started_at": self.started_at,
        }


class FailureEvent:
    """Structured failure event from the monitor."""

    def __init__(self, event_type: str, container_name: str, service_name: str,
                 message: str, severity: str = "Warning", details: Dict = None):
        self.event_type = event_type
        self.container_name = container_name
        self.service_name = service_name
        self.message = message
        self.severity = severity
        self.details = details or {}
        self.timestamp = time.time()
        self.logs = ""
        self.ai_analysis = None
        self.resolved = False

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "container_name": self.container_name,
            "service_name": self.service_name,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp,
            "logs": self.logs[:500] if self.logs else "",
            "ai_analysis": self.ai_analysis,
            "resolved": self.resolved,
        }


class HealthMonitor:
    """
    Continuously monitors Docker Swarm containers via the Docker SDK.
    Emits FailureEvent objects when issues are detected.
    """

    STACK_LABEL = "com.docker.stack.namespace"

    def __init__(self, stack_name: str = "healstack", check_interval: float = 3.0,
                 service_ports: Dict[str, int] = None):
        self.client = docker.from_env()
        self.stack_name = stack_name
        self.check_interval = check_interval
        self.service_ports = service_ports or {
            "healstack_api-gateway": 9001,
            "healstack_auth-service": 9002,
            "healstack_data-service": 9003,
        }
        self._callbacks: List[Callable[[FailureEvent], None]] = []
        self.container_states: Dict[str, ContainerState] = {}
        self.failure_history: List[FailureEvent] = []
        self._active_failures: Dict[str, FailureEvent] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def on_failure(self, callback: Callable[[FailureEvent], None]):
        self._callbacks.append(callback)

    def _emit(self, event: FailureEvent):
        key = f"{event.service_name}:{event.event_type}"
        if key in self._active_failures and not self._active_failures[key].resolved:
            return  # Already tracking
        self._active_failures[key] = event
        self.failure_history.append(event)
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def get_containers(self) -> List:
        """Get relevant containers belonging to our stack."""
        try:
            # We use all=True to see failed containers for diagnosis,
            # but we will filter the state cache to stay clean.
            return self.client.containers.list(
                all=True,
                filters={"label": f"{self.STACK_LABEL}={self.stack_name}"}
            )
        except Exception:
            return []

    def check_all(self) -> List[FailureEvent]:
        """Run all health checks and return new failures."""
        events = []
        containers = self.get_containers()
        
        # Reset current states to avoid "ghost" containers from previous runs
        new_states = {}

        for container in containers:
            try:
                container.reload()
                state = ContainerState(container)
                
                # Only keep running or very recently exited containers (non-zero exit)
                if state.status == "running" or state.exit_code != 0:
                    new_states[state.name] = state
            except Exception:
                continue
                
        self.container_states = new_states

        # Process failures for each tracked container
        for state in self.container_states.values():
            try:
                # Auto-resolve active failures if container is running healthy
                if state.status == "running" and state.health in ("healthy", "unknown"):
                    for ftype in ("ContainerCrash", "Unhealthy", "CrashLoop"):
                        key = f"{state.service_name}:{ftype}"
                        if key in self._active_failures and not self._active_failures[key].resolved:
                            self._active_failures[key].resolved = True

                # Check 1: Container crashed / exited
                if state.status == "exited" and state.exit_code != 0:
                    ev = FailureEvent(
                        "ContainerCrash", state.name, state.service_name,
                        f"Container '{state.name}' exited with code {state.exit_code}",
                        "Critical",
                        {"exit_code": state.exit_code, "restart_count": state.restart_count}
                    )
                    events.append(ev)
                    self._emit(ev)

                # Check 2: Unhealthy health check
                elif state.health == "unhealthy":
                    ev = FailureEvent(
                        "Unhealthy", state.name, state.service_name,
                        f"Container '{state.name}' health check failing",
                        "Warning",
                        {"health": state.health, "restart_count": state.restart_count}
                    )
                    events.append(ev)
                    self._emit(ev)

                # Check 3: High restart count
                elif state.restart_count > 3:
                    ev = FailureEvent(
                        "CrashLoop", state.name, state.service_name,
                        f"Container '{state.name}' restarting excessively ({state.restart_count} restarts)",
                        "Critical",
                        {"restart_count": state.restart_count}
                    )
                    events.append(ev)
                    self._emit(ev)
            except Exception:
                continue

        # Check 4: HTTP health check on service ports
        events.extend(self._check_http_health())

        return events

    def _check_http_health(self) -> List[FailureEvent]:
        """Check actual HTTP /health endpoints."""
        events = []
        for svc_name, port in self.service_ports.items():
            try:
                req = urllib.request.Request(
                    f"http://localhost:{port}/health",
                    headers={"User-Agent": "HealthMonitor/1.0"}
                )
                resp = urllib.request.urlopen(req, timeout=3)
                data = json.loads(resp.read())
                if data.get("status") != "healthy":
                    ev = FailureEvent(
                        "ServiceUnhealthy", svc_name, svc_name,
                        f"Service '{svc_name}' reporting unhealthy: {data.get('reason', 'unknown')}",
                        "Warning",
                        {"response": data}
                    )
                    events.append(ev)
                    self._emit(ev)
                else:
                    # Resolve any active failure for this service
                    key = f"{svc_name}:ServiceDown"
                    if key in self._active_failures:
                        self._active_failures[key].resolved = True
            except Exception as e:
                ev = FailureEvent(
                    "ServiceDown", svc_name, svc_name,
                    f"Service '{svc_name}' on port {port} unreachable: {str(e)[:100]}",
                    "Critical",
                    {"port": port, "error": str(e)[:200]}
                )
                events.append(ev)
                self._emit(ev)
        return events

    # Background runner
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            self.check_all()
            time.sleep(self.check_interval)

    def get_all_states(self) -> List[Dict]:
        return [s.to_dict() for s in self.container_states.values()]

    def get_active_failures(self) -> List[Dict]:
        return [e.to_dict() for e in self._active_failures.values() if not e.resolved]

    def get_failure_summary(self) -> Dict:
        total = len(self.failure_history)
        active = sum(1 for e in self._active_failures.values() if not e.resolved)
        return {"total": total, "active": active, "resolved": total - active}
