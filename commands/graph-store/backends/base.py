"""Abstract base class for graph storage backends.

This module defines the GraphBackend interface that all storage implementations
must follow. This abstraction allows swapping between different backends
(GCS JSON-LD, Firestore, Spanner Graph, Neo4j) without changing domain services.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class GraphBackend(ABC):
    """Abstract interface for graph storage backends.

    All methods are synchronous by default. Implementations may use
    async internally but should provide sync wrappers for Cloud Functions
    compatibility.
    """

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_node(
        self,
        node_type: str,
        node_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a node in the graph.

        Args:
            node_type: The type of node (e.g., "Task", "Topic", "Goal")
            node_id: Unique identifier for the node (e.g., "task:abc123")
            data: Node properties/attributes

        Returns:
            The created node with metadata (id, type, created_at, etc.)

        Raises:
            ValueError: If node_id already exists
        """
        pass

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID.

        Args:
            node_id: The node identifier

        Returns:
            The node data if found, None otherwise
        """
        pass

    @abstractmethod
    def update_node(
        self,
        node_id: str,
        data: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """Update a node.

        Args:
            node_id: The node identifier
            data: Properties to update
            merge: If True, merge with existing data. If False, replace entirely.

        Returns:
            The updated node

        Raises:
            KeyError: If node doesn't exist
        """
        pass

    @abstractmethod
    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its associated edges.

        Args:
            node_id: The node identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists.

        Args:
            node_id: The node identifier

        Returns:
            True if exists, False otherwise
        """
        pass

    # -------------------------------------------------------------------------
    # Edge Operations
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a relationship between nodes.

        Args:
            from_id: Source node ID
            relation: Relationship type (e.g., "hasTopic", "dependsOn")
            to_id: Target node ID
            data: Optional edge properties

        Returns:
            The created edge with metadata

        Raises:
            KeyError: If either node doesn't exist
        """
        pass

    @abstractmethod
    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get edges connected to a node.

        Args:
            node_id: The node identifier
            direction: "outgoing", "incoming", or "both"
            relation: Optional filter by relationship type

        Returns:
            List of edges
        """
        pass

    @abstractmethod
    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge by ID.

        Args:
            edge_id: The edge identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def delete_edges_for_node(self, node_id: str) -> int:
        """Delete all edges connected to a node.

        Args:
            node_id: The node identifier

        Returns:
            Number of edges deleted
        """
        pass

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    @abstractmethod
    def query_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query nodes with filters.

        Args:
            node_type: Optional filter by node type
            filters: Key-value filters (exact match)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of matching nodes
        """
        pass

    @abstractmethod
    def count_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """Count nodes matching criteria.

        Args:
            node_type: Optional filter by node type
            filters: Key-value filters

        Returns:
            Count of matching nodes
        """
        pass

    # -------------------------------------------------------------------------
    # Traversal Operations
    # -------------------------------------------------------------------------

    @abstractmethod
    def traverse(
        self,
        start_id: str,
        depth: int = 2,
        relations: Optional[List[str]] = None,
        direction: str = "both"
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting node.

        Args:
            start_id: Starting node ID
            depth: Maximum traversal depth (hops)
            relations: Optional list of relation types to follow
            direction: "outgoing", "incoming", or "both"

        Returns:
            Subgraph containing traversed nodes and edges
        """
        pass

    @abstractmethod
    def get_subgraph(
        self,
        node_id: str,
        depth: int = 2,
        include_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract a subgraph around a node for LLM context.

        This is optimized for producing JSON-LD that LLMs can reason over.

        Args:
            node_id: Central node ID
            depth: How many hops to include
            include_types: Optional list of node types to include

        Returns:
            JSON-LD formatted subgraph
        """
        pass

    # -------------------------------------------------------------------------
    # Bulk Operations
    # -------------------------------------------------------------------------

    @abstractmethod
    def bulk_create_nodes(
        self,
        nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple nodes in a batch.

        Args:
            nodes: List of node dicts, each with "type", "id", and "data"

        Returns:
            List of created nodes
        """
        pass

    @abstractmethod
    def bulk_create_edges(
        self,
        edges: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple edges in a batch.

        Args:
            edges: List of edge dicts, each with "from_id", "relation", "to_id"

        Returns:
            List of created edges
        """
        pass

    # -------------------------------------------------------------------------
    # Schema & Metadata
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get the graph schema definition.

        Returns:
            JSON-LD context and schema information
        """
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics.

        Returns:
            Dict with node counts by type, edge counts, etc.
        """
        pass

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize the backend (create tables, indexes, etc.).

        Default implementation does nothing. Override as needed.
        """
        pass

    def close(self) -> None:
        """Close connections and cleanup.

        Default implementation does nothing. Override as needed.
        """
        pass
