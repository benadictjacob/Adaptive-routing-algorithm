"""
═══════════════════════════════════════════════════════════════════════
  VECTOR MATH MODULE
  Geometric math utilities for the Adaptive Decentralized Routing System.
═══════════════════════════════════════════════════════════════════════

Provides cosine similarity, Euclidean distance, and vector operations.
All routing scoring depends on these primitives.
"""

import math
from typing import List

Vector = List[float]


def dot_product(v1: Vector, v2: Vector) -> float:
    """Compute the dot product of two vectors."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return sum(a * b for a, b in zip(v1, v2))


def magnitude(v: Vector) -> float:
    """Compute the L2 norm (magnitude) of a vector."""
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(v1: Vector, v2: Vector) -> float:
    """
    Cosine similarity in [-1, 1].
    Returns 0.0 if either vector has zero magnitude.
    """
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot_product(v1, v2) / (mag1 * mag2)


def euclidean_distance(v1: Vector, v2: Vector) -> float:
    """Euclidean distance between two vectors."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def vector_subtract(v1: Vector, v2: Vector) -> Vector:
    """Element-wise subtraction: v1 - v2."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return [a - b for a, b in zip(v1, v2)]


def vector_add(v1: Vector, v2: Vector) -> Vector:
    """Element-wise addition: v1 + v2."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return [a + b for a, b in zip(v1, v2)]


def normalize(v: Vector) -> Vector:
    """Return unit vector in the same direction. Returns zero vector if magnitude is 0."""
    mag = magnitude(v)
    if mag == 0.0:
        return [0.0] * len(v)
    return [x / mag for x in v]


def angle_between(v1: Vector, v2: Vector) -> float:
    """Angle in radians between two vectors. Returns 0 for zero vectors."""
    cos = cosine_similarity(v1, v2)
    # Clamp to [-1, 1] for numerical safety
    cos = max(-1.0, min(1.0, cos))
    return math.acos(cos)
