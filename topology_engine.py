"""
═══════════════════════════════════════════════════════════════════════
  TOPOLOGY ENGINE MODULE
  Greedy guarantee checks and face routing for planar graphs.
═══════════════════════════════════════════════════════════════════════

Section 6 — Greedy Guarantee Check
Section 8 — Face Routing Mode
"""

import math
from typing import List, Optional, Tuple

from avrs.math_utils import Vector, euclidean_distance, cosine_similarity
from avrs.node import Node


# ═══════════════════════════════════════════════════════════════════
#  GREEDY GUARANTEE CHECK (Section 6)
# ═══════════════════════════════════════════════════════════════════

def greedy_guarantee_check(nodes: List[Node], target: Vector) -> dict:
    """
    When Delaunay mode is enabled:
    If any node exists closer to target than the current node,
    at least one neighbor must also be closer.

    Returns:
        dict with 'passed' (bool), 'violations' (list of node IDs), 'total_checked' (int)
    """
    violations = []
    total_checked = 0

    for node in nodes:
        if not node.alive:
            continue
        total_checked += 1
        dist_current = euclidean_distance(list(node.vector), target)

        # Check if any node in the network is closer
        any_closer_exists = False
        for other in nodes:
            if other.id == node.id or not other.alive:
                continue
            if euclidean_distance(list(other.vector), target) < dist_current - 1e-10:
                any_closer_exists = True
                break

        if not any_closer_exists:
            # This is the closest node — no violation possible
            continue

        # There IS a closer node somewhere. Check if at least one neighbor is closer.
        neighbor_closer = False
        for nb in node.get_alive_neighbors():
            if euclidean_distance(list(nb.vector), target) < dist_current - 1e-10:
                neighbor_closer = True
                break

        if not neighbor_closer:
            violations.append(node.id)

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "total_checked": total_checked,
    }


# ═══════════════════════════════════════════════════════════════════
#  FACE ROUTING MODE (Section 8)
# ═══════════════════════════════════════════════════════════════════

def _angle_to_target(current: Node, neighbor: Node, target: Vector) -> float:
    """
    Compute the angle from the line (current→target) to the line (current→neighbor),
    measured counter-clockwise in a 2D projection (first two coordinates).
    Used for face routing traversal.
    """
    cx, cy = list(current.vector)[0], list(current.vector)[1] if len(current.vector) > 1 else 0.0
    tx, ty = target[0], target[1] if len(target) > 1 else 0.0
    nx, ny = list(neighbor.vector)[0], list(neighbor.vector)[1] if len(neighbor.vector) > 1 else 0.0

    # Angle from current to target
    angle_target = math.atan2(ty - cy, tx - cx)
    # Angle from current to neighbor
    angle_neighbor = math.atan2(ny - cy, nx - cx)

    # Relative angle (counter-clockwise from target direction)
    relative = (angle_neighbor - angle_target) % (2 * math.pi)
    return relative


def face_route_step(
    current: Node,
    target: Vector,
    prev_node: Optional[Node] = None,
    visited_in_face: Optional[set] = None,
) -> Optional[Node]:
    """
    Perform one step of face routing (right-hand rule on 2D projection).

    When greedy routing fails (no neighbor closer to target):
    - Traverse polygon edges of the planar graph
    - Follow face boundaries
    - Continue until a node closer to target is found

    Args:
        current:         Current node (greedy routing got stuck here)
        target:          Target vector
        prev_node:       Previous node in face traversal (for right-hand rule)
        visited_in_face: Set of node IDs already visited during this face traversal

    Returns:
        Next node in face traversal, or None if stuck.
    """
    alive_neighbors = current.get_alive_neighbors()
    if not alive_neighbors:
        return None

    if visited_in_face is None:
        visited_in_face = set()

    if prev_node is None:
        # Start face routing: pick the neighbor with smallest CCW angle from target direction
        best = None
        best_angle = float('inf')
        for nb in alive_neighbors:
            if nb.id in visited_in_face:
                continue
            angle = _angle_to_target(current, nb, target)
            if angle < best_angle:
                best_angle = angle
                best = nb
        return best
    else:
        # Right-hand rule: pick next edge CCW from the edge we arrived on
        # Compute angle of arrival edge (from prev to current)
        cx, cy = list(current.vector)[0], list(current.vector)[1] if len(current.vector) > 1 else 0.0
        px, py = list(prev_node.vector)[0], list(prev_node.vector)[1] if len(prev_node.vector) > 1 else 0.0

        arrival_angle = math.atan2(py - cy, px - cx)

        # Sort neighbors by CCW angle from arrival direction
        candidates = []
        for nb in alive_neighbors:
            if nb.id in visited_in_face and nb.id != prev_node.id:
                continue
            nx, ny = list(nb.vector)[0], list(nb.vector)[1] if len(nb.vector) > 1 else 0.0
            nb_angle = math.atan2(ny - cy, nx - cx)
            relative = (nb_angle - arrival_angle) % (2 * math.pi)
            candidates.append((relative, nb))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        # Pick the first neighbor (smallest CCW angle = right-hand rule)
        return candidates[0][1]


def face_route_full(
    start: Node,
    target: Vector,
    max_face_steps: int = 50,
) -> Tuple[Optional[Node], List[str]]:
    """
    Execute full face routing from a stuck node until finding a node
    closer to target or exhausting step budget.

    Returns:
        (found_node, path_taken) — found_node is None if face routing fails.
    """
    dist_start = euclidean_distance(list(start.vector), target)
    current = start
    prev = None
    visited_in_face = {start.id}
    path = [start.id]

    for step in range(max_face_steps):
        next_node = face_route_step(current, target, prev, visited_in_face)

        if next_node is None:
            return None, path  # Stuck

        path.append(next_node.id)
        visited_in_face.add(next_node.id)

        # Check if this node is closer to target than where we started
        dist_next = euclidean_distance(list(next_node.vector), target)
        if dist_next < dist_start - 1e-10:
            return next_node, path  # Found a closer node — resume greedy

        # Check if we looped back to start
        if next_node.id == start.id:
            return None, path  # Full loop, no closer node found

        prev = current
        current = next_node

    return None, path  # Exhausted budget
