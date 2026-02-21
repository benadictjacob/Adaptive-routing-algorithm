"""
═══════════════════════════════════════════════════════════════════════
  LOG COLLECTOR — Fetches real container logs via Docker SDK
═══════════════════════════════════════════════════════════════════════

When a failure is detected, captures stdout/stderr from the container.
Stores logs and forwards them to the AI analyzer.
"""

import docker
from typing import Optional, Dict


class LogCollector:
    """Fetches and stores container logs from real Docker containers."""

    def __init__(self):
        self.client = docker.from_env()
        self.log_store: Dict[str, str] = {}

    def fetch_logs(self, container_name: str, tail: int = 50) -> str:
        """Fetch the last N lines of logs from a container."""
        try:
            container = self.client.containers.get(container_name)
            logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
            self.log_store[container_name] = logs
            return logs
        except docker.errors.NotFound:
            return f"[ERROR] Container '{container_name}' not found"
        except docker.errors.APIError as e:
            return f"[ERROR] Docker API error: {str(e)[:200]}"
        except Exception as e:
            return f"[ERROR] Could not fetch logs: {str(e)[:200]}"

    def fetch_service_logs(self, service_name: str, tail: int = 50) -> str:
        """Fetch logs from a Docker Swarm service."""
        try:
            service = self.client.services.get(service_name)
            logs = service.logs(tail=tail, timestamps=True, stdout=True, stderr=True)
            if isinstance(logs, bytes):
                log_text = logs.decode("utf-8", errors="replace")
            else:
                log_text = "".join(chunk.decode("utf-8", errors="replace") for chunk in logs)
            self.log_store[service_name] = log_text
            return log_text
        except Exception as e:
            return f"[ERROR] Could not fetch service logs: {str(e)[:200]}"

    def get_stored_logs(self, name: str) -> Optional[str]:
        return self.log_store.get(name)

    def get_all_stored(self) -> Dict[str, str]:
        return {k: v[:500] for k, v in self.log_store.items()}
