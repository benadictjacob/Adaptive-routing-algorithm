"""
Geometric math utilities for the Adaptive Vector Routing System.

Provides cosine similarity and Euclidean distance calculations
used by the routing decision function.
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
    """Compute the magnitude (L2 norm) of a vector."""
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(v1: Vector, v2: Vector) -> float:
    """
    Compute cosine similarity between two vectors.

    Returns a value in [-1, 1]:
        1  → vectors point in the same direction
        0  → vectors are orthogonal
       -1  → vectors point in opposite directions

    If either vector has zero magnitude, returns 0.0.
    """
    mag1 = magnitude(v1)
    mag2 = magnitude(v2)
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot_product(v1, v2) / (mag1 * mag2)


def euclidean_distance(v1: Vector, v2: Vector) -> float:
    """
    Compute the Euclidean distance between two vectors.

    distance = sqrt( sum( (a_i - b_i)^2 ) )
    """
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def vector_subtract(v1: Vector, v2: Vector) -> Vector:
    """Compute v1 - v2 element-wise."""
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")
    return [a - b for a, b in zip(v1, v2)]
