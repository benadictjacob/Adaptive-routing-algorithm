"""
═══════════════════════════════════════════════════════════════════════
  BLUE-GREEN DEPLOYMENT ENGINE — Safe Rolling Updates with Rollback
═══════════════════════════════════════════════════════════════════════

Deploys new versions alongside existing ones, validates health,
then switches traffic. Keeps old version as fallback.
"""

import time
import docker
import urllib.request
import json
from typing import Dict, List, Optional


class DeploymentState:
    """Tracks the state of a deployment."""
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.status = "idle"  # idle, deploying, validating, live, rolled_back
        self.blue_image = ""
        self.green_image = ""
        self.started_at = None
        self.completed_at = None
        self.health_checks_passed = 0
        self.health_checks_total = 3
        self.message = ""

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "status": self.status,
            "blue_image": self.blue_image,
            "green_image": self.green_image,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "health_checks": f"{self.health_checks_passed}/{self.health_checks_total}",
            "message": self.message,
        }


class BlueGreenDeployer:
    """
    Blue-Green Deployment Engine.

    Blue  = currently running version
    Green = new version being deployed

    Process:
      1. Deploy green alongside blue (start-first)
      2. Wait 5 seconds for startup
      3. Run health checks on green
      4. If healthy → route traffic to green
      5. Keep blue as fallback
      6. If green fails → revert to blue
    """

    def __init__(self, event_callback=None):
        self.client = docker.from_env()
        self.deployments: Dict[str, DeploymentState] = {}
        self.history: List[Dict] = []
        self._event_callback = event_callback

    def _push_event(self, event_type: str, data: dict):
        if self._event_callback:
            self._event_callback(event_type, data)

    def deploy(self, service_name: str, new_image: str, health_port: int) -> DeploymentState:
        """
        Execute a blue-green deployment.
        Returns the final deployment state.
        """
        state = DeploymentState(service_name)
        self.deployments[service_name] = state

        try:
            service = self.client.services.get(service_name)
        except Exception as e:
            state.status = "failed"
            state.message = f"Service '{service_name}' not found: {str(e)[:100]}"
            self.history.append(state.to_dict())
            return state

        # Get current (blue) image
        current_spec = service.attrs.get("Spec", {}).get("TaskTemplate", {}).get("ContainerSpec", {})
        state.blue_image = current_spec.get("Image", "unknown")
        state.green_image = new_image
        state.started_at = time.time()

        # Step 1: Deploy green (update with start-first order)
        state.status = "deploying"
        state.message = "Deploying green version alongside blue..."
        self._push_event("deployment", state.to_dict())

        try:
            service.update(
                image=new_image,
                update_config={
                    "Parallelism": 1,
                    "Delay": 5000000000,  # 5 seconds in nanoseconds
                    "Order": "start-first",
                    "FailureAction": "rollback",
                },
                rollback_config={
                    "Parallelism": 1,
                    "Order": "stop-first",
                },
            )
        except Exception as e:
            state.status = "failed"
            state.message = f"Deploy failed: {str(e)[:100]}"
            self.history.append(state.to_dict())
            self._push_event("deployment", state.to_dict())
            return state

        # Step 2: Wait for green to start
        state.status = "validating"
        state.message = "Waiting for green to start (5s)..."
        self._push_event("deployment", state.to_dict())
        time.sleep(5)

        # Step 3: Health checks
        state.message = "Running health checks on green..."
        self._push_event("deployment", state.to_dict())

        for i in range(state.health_checks_total):
            try:
                req = urllib.request.Request(
                    f"http://localhost:{health_port}/health",
                    headers={"User-Agent": "BlueGreenDeployer/1.0"}
                )
                resp = urllib.request.urlopen(req, timeout=5)
                data = json.loads(resp.read())
                if data.get("status") == "healthy":
                    state.health_checks_passed += 1
            except Exception:
                pass
            time.sleep(2)

        # Step 4: Decision
        if state.health_checks_passed >= 2:
            state.status = "live"
            state.message = f"Green deployed successfully. {state.health_checks_passed}/{state.health_checks_total} checks passed."
            state.completed_at = time.time()
        else:
            # Step 6: Rollback
            state.status = "rolling_back"
            state.message = f"Green failed. Rolling back to blue... ({state.health_checks_passed}/{state.health_checks_total} checks passed)"
            self._push_event("deployment", state.to_dict())

            try:
                service.update(image=state.blue_image)
                state.status = "rolled_back"
                state.message = f"Rolled back to blue ({state.blue_image})"
            except Exception as e:
                state.status = "failed"
                state.message = f"Rollback failed: {str(e)[:100]}"
            state.completed_at = time.time()

        self.history.append(state.to_dict())
        self._push_event("deployment", state.to_dict())
        return state

    def get_status(self, service_name: str) -> Optional[Dict]:
        s = self.deployments.get(service_name)
        return s.to_dict() if s else None

    def get_all(self) -> Dict:
        return {
            "active": {k: v.to_dict() for k, v in self.deployments.items()},
            "history": self.history[-20:],
        }
