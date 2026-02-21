"""
═══════════════════════════════════════════════════════════════════════
  STATE SNAPSHOT ENGINE (Section 5)
  Periodic cluster state snapshots for disaster restoration.
═══════════════════════════════════════════════════════════════════════
"""

import os
import json
import time
import threading
from typing import List, Dict, Optional
from controller.cluster import Cluster


SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state_store", "snapshots")


class SnapshotEngine:
    """
    Periodically saves full cluster state to JSON files.
    Supports listing, retrieving, and restoring from snapshots.
    """

    def __init__(self, cluster: Cluster, interval: float = 30.0):
        self.cluster = cluster
        self.interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.snapshot_count = 0
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    def take_snapshot(self) -> str:
        """Take a snapshot of the current cluster state."""
        data = self.cluster.get_snapshot_data()
        self.snapshot_count += 1
        filename = f"snapshot_{self.snapshot_count:04d}_{int(time.time())}.json"
        filepath = os.path.join(SNAPSHOT_DIR, filename)

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        self.cluster._log_event(
            "SnapshotCreated",
            f"Snapshot #{self.snapshot_count} saved: {filename}"
        )
        return filename

    def list_snapshots(self) -> List[Dict]:
        """List all available snapshots."""
        files = sorted(os.listdir(SNAPSHOT_DIR), reverse=True)
        result = []
        for f in files:
            if f.endswith(".json"):
                filepath = os.path.join(SNAPSHOT_DIR, f)
                stat = os.stat(filepath)
                result.append({
                    "filename": f,
                    "size_bytes": stat.st_size,
                    "created_at": stat.st_mtime,
                })
        return result

    def get_latest_snapshot(self) -> Optional[Dict]:
        """Retrieve the most recent snapshot data."""
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
        latest = snapshots[0]
        return self.load_snapshot(latest["filename"])

    def load_snapshot(self, filename: str) -> Optional[Dict]:
        """Load a specific snapshot by filename."""
        filepath = os.path.join(SNAPSHOT_DIR, filename)
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r") as f:
            return json.load(f)

    # ── Background Runner ────────────────────────────────────────

    def start(self):
        """Start periodic snapshot scheduling."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            self.take_snapshot()
            time.sleep(self.interval)
