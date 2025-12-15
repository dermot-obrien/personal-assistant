"""Core graph service.

Provides high-level graph operations on top of the storage backend.
"""

import uuid
from typing import Optional, List, Dict, Any

from ..backends.base import GraphBackend


class GraphService:
    """High-level service for graph operations.

    Wraps the GraphBackend with business logic and convenience methods.
    """

    def __init__(self, backend: GraphBackend):
        self.backend = backend

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    def create_node(
        self,
        node_type: str,
        data: Dict[str, Any],
        node_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new node.

        Args:
            node_type: Type of node (Task, Topic, Goal, etc.)
            data: Node properties
            node_id: Optional custom ID. Auto-generated if not provided.

        Returns:
            The created node
        """
        if not node_id:
            prefix = node_type.lower()
            node_id = f"{prefix}:{uuid.uuid4().hex[:12]}"

        return self.backend.create_node(node_type, node_id, data)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID."""
        return self.backend.get_node(node_id)

    def update_node(
        self,
        node_id: str,
        data: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """Update a node."""
        return self.backend.update_node(node_id, data, merge)

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges."""
        return self.backend.delete_node(node_id)

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists."""
        return self.backend.node_exists(node_id)

    # -------------------------------------------------------------------------
    # Edge Operations
    # -------------------------------------------------------------------------

    def create_edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a relationship between nodes."""
        return self.backend.create_edge(from_id, relation, to_id, data)

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get edges connected to a node."""
        return self.backend.get_edges(node_id, direction, relation)

    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge."""
        return self.backend.delete_edge(edge_id)

    def get_related_nodes(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "outgoing"
    ) -> List[Dict[str, Any]]:
        """Get nodes connected to a given node.

        Args:
            node_id: The source node ID
            relation: Optional filter by relation type
            direction: "outgoing", "incoming", or "both"

        Returns:
            List of related nodes
        """
        edges = self.get_edges(node_id, direction, relation)
        related_ids = set()

        for edge in edges:
            if direction == "outgoing" or direction == "both":
                if edge["from_id"] == node_id:
                    related_ids.add(edge["to_id"])
            if direction == "incoming" or direction == "both":
                if edge["to_id"] == node_id:
                    related_ids.add(edge["from_id"])

        # Fetch the nodes
        nodes = []
        for rid in related_ids:
            node = self.get_node(rid)
            if node:
                nodes.append(node)

        return nodes

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    def query_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query nodes with filters."""
        return self.backend.query_nodes(node_type, filters, limit, offset)

    def count_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """Count nodes matching criteria."""
        return self.backend.count_nodes(node_type, filters)

    def search_nodes(
        self,
        query: str,
        node_type: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Simple text search across nodes.

        Args:
            query: Search query
            node_type: Optional filter by type
            fields: Fields to search (default: name, description)
            limit: Maximum results

        Returns:
            Matching nodes sorted by relevance
        """
        if not fields:
            fields = ["name", "description"]

        query_lower = query.lower()
        all_nodes = self.query_nodes(node_type, limit=1000)
        results = []

        for node in all_nodes:
            score = 0
            for field in fields:
                value = node.get(field, "")
                if isinstance(value, str):
                    value_lower = value.lower()
                    if query_lower in value_lower:
                        # Exact match gets higher score
                        if query_lower == value_lower:
                            score += 10
                        # Starts with gets medium score
                        elif value_lower.startswith(query_lower):
                            score += 5
                        # Contains gets base score
                        else:
                            score += 1

            if score > 0:
                results.append((score, node))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in results[:limit]]

    # -------------------------------------------------------------------------
    # Traversal Operations
    # -------------------------------------------------------------------------

    def traverse(
        self,
        start_id: str,
        depth: int = 2,
        relations: Optional[List[str]] = None,
        direction: str = "both"
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting node."""
        return self.backend.traverse(start_id, depth, relations, direction)

    def get_subgraph(
        self,
        node_id: str,
        depth: int = 2,
        include_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract a subgraph for LLM context."""
        return self.backend.get_subgraph(node_id, depth, include_types)

    # -------------------------------------------------------------------------
    # Bulk Operations
    # -------------------------------------------------------------------------

    def bulk_create_nodes(
        self,
        nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple nodes."""
        # Ensure each node has an ID
        for node in nodes:
            if "id" not in node:
                prefix = node.get("type", "node").lower()
                node["id"] = f"{prefix}:{uuid.uuid4().hex[:12]}"

        return self.backend.bulk_create_nodes(nodes)

    def bulk_create_edges(
        self,
        edges: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple edges."""
        return self.backend.bulk_create_edges(edges)

    # -------------------------------------------------------------------------
    # Schema & Stats
    # -------------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Any]:
        """Get the graph schema."""
        return self.backend.get_schema()

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        return self.backend.get_stats()

    # -------------------------------------------------------------------------
    # Domain-Specific Helpers
    # -------------------------------------------------------------------------

    def get_topic_hierarchy(self, root_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get topics in hierarchical structure.

        Args:
            root_path: Optional path prefix to filter (e.g., "Work/Projects")

        Returns:
            List of topics with their children
        """
        topics = self.query_nodes("Topic", limit=1000)

        if root_path:
            topics = [t for t in topics if t.get("path", "").startswith(root_path)]

        # Build hierarchy
        by_path = {t.get("path"): t for t in topics}
        roots = []

        for topic in topics:
            path = topic.get("path", "")
            parts = path.rsplit("/", 1)

            if len(parts) == 1:
                # Top-level topic
                roots.append(topic)
            else:
                parent_path = parts[0]
                if parent_path in by_path:
                    parent = by_path[parent_path]
                    if "children" not in parent:
                        parent["children"] = []
                    parent["children"].append(topic)
                else:
                    # Parent not found, treat as root
                    roots.append(topic)

        return roots

    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get tasks filtered by status."""
        return self.query_nodes("Task", {"status": status}, limit=500)

    def get_tasks_by_topic(self, topic_id: str) -> List[Dict[str, Any]]:
        """Get all tasks under a topic (including nested topics)."""
        # Get the topic to find its path
        topic = self.get_node(topic_id)
        if not topic:
            return []

        topic_path = topic.get("path", "")

        # Get all tasks
        tasks = self.query_nodes("Task", limit=1000)

        # Filter by topic path prefix
        return [
            t for t in tasks
            if t.get("primary_topic", "").startswith(topic_path)
        ]

    def get_goal_alignment(self, goal_id: str) -> Dict[str, Any]:
        """Get all entities aligned to a goal.

        Returns projects, initiatives, and tasks that support the goal.
        """
        goal = self.get_node(goal_id)
        if not goal:
            return {"error": "Goal not found"}

        # Get directly related nodes
        projects = self.get_related_nodes(goal_id, "supportsGoal", "incoming")
        initiatives = self.get_related_nodes(goal_id, "hasInitiative", "outgoing")

        # Get tasks from projects
        tasks = []
        for project in projects:
            project_tasks = self.get_related_nodes(project["@id"], "hasTask", "outgoing")
            tasks.extend(project_tasks)

        return {
            "goal": goal,
            "projects": projects,
            "initiatives": initiatives,
            "tasks": tasks,
            "summary": {
                "project_count": len(projects),
                "initiative_count": len(initiatives),
                "task_count": len(tasks)
            }
        }
