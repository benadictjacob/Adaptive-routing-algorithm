"""
SECTION 2 — SERVICE GROUPING

Nodes must be grouped into semantic service sections:
- auth
- database
- compute
- vision
- storage
- proxy

Routing must first match section before selecting node.
Nodes outside required section must never be chosen.
"""

from typing import List, Dict, Optional
from avrs.node import Node
from avrs.network import Network


# Valid service roles from specification
VALID_SERVICE_ROLES = {
    "auth",
    "database",
    "compute",
    "vision",
    "storage",
    "proxy"
}


class ServiceGrouping:
    """
    Manages semantic service grouping and role-based routing.
    
    SECTION 2: Ensures routing only selects nodes from the correct service section.
    """
    
    def __init__(self, network: Network):
        """
        Initialize service grouping for a network.
        
        Args:
            network: Network instance containing nodes
        """
        self.network = network
        self._role_to_nodes: Dict[str, List[Node]] = {}
        self._update_grouping()
    
    def _update_grouping(self):
        """Update internal mapping of role to nodes."""
        self._role_to_nodes = {}
        for node in self.network.nodes:
            role = node.role
            if role not in self._role_to_nodes:
                self._role_to_nodes[role] = []
            self._role_to_nodes[role].append(node)
    
    def get_nodes_by_role(self, role: str) -> List[Node]:
        """
        Get all nodes with a specific role.
        
        Args:
            role: Service role name
            
        Returns:
            List of nodes with that role
        """
        return self._role_to_nodes.get(role, [])
    
    def get_alive_nodes_by_role(self, role: str) -> List[Node]:
        """
        Get all alive nodes with a specific role.
        
        Args:
            role: Service role name
            
        Returns:
            List of alive nodes with that role
        """
        return [node for node in self.get_nodes_by_role(role) if node.alive]
    
    def has_alive_nodes(self, role: str) -> bool:
        """
        Check if any nodes with the given role are alive.
        
        Args:
            role: Service role name
            
        Returns:
            True if at least one node with that role is alive
        """
        return len(self.get_alive_nodes_by_role(role)) > 0
    
    def determine_target_role(self, request_text: str) -> Optional[str]:
        """
        Determine target service role from request text.
        
        Uses keyword matching to identify the target service section.
        In production, this could use NLP or ML classification.
        
        Args:
            request_text: Request text description
            
        Returns:
            Target service role, or None if cannot be determined
        """
        text_lower = request_text.lower()
        
        # Keyword-based role detection
        role_keywords = {
            "auth": ["auth", "login", "authenticate", "token", "credential", "password"],
            "database": ["database", "db", "query", "sql", "data", "store", "persist"],
            "compute": ["compute", "calculate", "process", "execute", "run", "task"],
            "vision": ["vision", "image", "visual", "detect", "recognize", "camera"],
            "storage": ["storage", "file", "upload", "download", "blob", "object"],
            "proxy": ["proxy", "forward", "route", "gateway", "redirect"]
        }
        
        # Count keyword matches for each role
        role_scores = {}
        for role, keywords in role_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            if score > 0:
                role_scores[role] = score
        
        if not role_scores:
            return None
        
        # Return role with highest score
        return max(role_scores.items(), key=lambda x: x[1])[0]
    
    def validate_role(self, role: str) -> bool:
        """
        Check if a role is a valid service role.
        
        Args:
            role: Role name to validate
            
        Returns:
            True if role is valid
        """
        return role in VALID_SERVICE_ROLES
    
    def refresh(self):
        """Refresh the grouping after network changes."""
        self._update_grouping()
