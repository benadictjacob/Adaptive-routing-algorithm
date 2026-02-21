"""
SECTION 4 — VECTOR MAPPING

Both nodes and requests must be embedded into the same vector space.
Node vector = embedding(service_description)
Request vector = embedding(request_text)

Router must compute similarity between request vector and node vector.
Similarity metric must be cosine similarity.
"""

import hashlib
import math
from typing import List, Dict
from avrs.math_utils import Vector, cosine_similarity


class VectorEmbedder:
    """
    Generates semantic embeddings for nodes and requests.
    
    In production, this would use a proper embedding model (e.g., sentence-transformers).
    For simulation, we use a deterministic hash-based approach that creates
    consistent vectors from text descriptions.
    """
    
    def __init__(self, dimensions: int = 128):
        """
        Initialize the embedder.
        
        Args:
            dimensions: Dimensionality of the embedding space (default 128)
        """
        self.dimensions = dimensions
        # Service role to vector mapping cache
        self._role_cache: Dict[str, Vector] = {}
    
    def embed_text(self, text: str) -> Vector:
        """
        Generate a vector embedding from text.
        
        Uses a deterministic hash-based approach to create consistent vectors.
        In production, replace with actual embedding model.
        
        Args:
            text: Input text to embed
            
        Returns:
            Vector of specified dimensions
        """
        # Normalize text
        text = text.lower().strip()
        
        # Generate deterministic vector from text hash
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # Convert hash bytes to float vector
        vector = []
        for i in range(self.dimensions):
            # Use multiple bytes to create smooth distribution
            byte_idx = i % len(hash_bytes)
            byte_val = hash_bytes[byte_idx]
            # Normalize to [-1, 1] range
            normalized = (byte_val / 255.0) * 2.0 - 1.0
            vector.append(normalized)
        
        # Normalize vector to unit length for cosine similarity
        magnitude = math.sqrt(sum(x * x for x in vector))
        if magnitude > 0:
            vector = [x / magnitude for x in vector]
        
        return vector
    
    def embed_service_description(self, role: str, description: str = "") -> Vector:
        """
        Generate embedding for a service node.
        
        Args:
            role: Service role (e.g., 'auth', 'database', 'compute')
            description: Optional additional description
            
        Returns:
            Vector embedding
        """
        # Cache role-based embeddings
        if role in self._role_cache:
            base_vector = self._role_cache[role]
        else:
            base_vector = self.embed_text(f"service role: {role}")
            self._role_cache[role] = base_vector
        
        # If description provided, blend with role vector
        if description:
            desc_vector = self.embed_text(description)
            # Weighted combination: 70% role, 30% description
            blended = [
                0.7 * base_vector[i] + 0.3 * desc_vector[i]
                for i in range(self.dimensions)
            ]
            # Renormalize
            magnitude = math.sqrt(sum(x * x for x in blended))
            if magnitude > 0:
                blended = [x / magnitude for x in blended]
            return blended
        
        return base_vector
    
    def embed_request(self, request_text: str) -> Vector:
        """
        Generate embedding for a request.
        
        Args:
            request_text: The request text to embed
            
        Returns:
            Vector embedding
        """
        return self.embed_text(f"request: {request_text}")
    
    def compute_similarity(self, node_vector: Vector, request_vector: Vector) -> float:
        """
        Compute semantic similarity between node and request vectors.
        
        Uses cosine similarity as specified in Section 4.
        
        Args:
            node_vector: Node's capability vector
            request_vector: Request's target vector
            
        Returns:
            Cosine similarity value in [-1, 1]
        """
        return cosine_similarity(node_vector, request_vector)


# Global embedder instance (defaults to 4D to match network)
_default_embedder = VectorEmbedder(dimensions=4)

def get_embedder(dimensions: int = 4) -> VectorEmbedder:
    """
    Get the default embedder instance.
    
    Args:
        dimensions: Vector dimensions (default 4 to match network)
        
    Returns:
        VectorEmbedder instance
    """
    if _default_embedder.dimensions != dimensions:
        # Create new embedder with specified dimensions
        return VectorEmbedder(dimensions=dimensions)
    return _default_embedder
