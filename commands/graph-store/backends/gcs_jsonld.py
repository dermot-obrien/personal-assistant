"""GCS JSON-LD Backend Implementation.

Stores graph data in Google Cloud Storage using JSON-LD format.
Supports GraphRAG, PathRAG, and LightRAG retrieval patterns for LLM reasoning.

Storage Structure:
    gs://bucket/graph/
        schema.json          - JSON-LD @context definitions
        nodes/
            {type}.jsonl     - Nodes by type (one per line)
        edges/
            relationships.jsonl - All edges
        indexes/
            node_index.json  - ID -> file location mapping
            by_type.json     - Type -> node IDs
            by_property.json - Property indexes for common queries

References:
    - PathRAG: https://arxiv.org/html/2502.14902v1
    - LightRAG: https://arxiv.org/html/2410.05779v1
    - Microsoft GraphRAG: https://microsoft.github.io/graphrag/
"""

import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Set, Tuple
from zoneinfo import ZoneInfo

from google.cloud import storage

from .base import GraphBackend


class GCSJsonLDBackend(GraphBackend):
    """Graph backend using GCS with JSON-LD storage format.

    Implements efficient graph operations with support for:
    - GraphRAG: Community-based retrieval with hierarchical summaries
    - PathRAG: Path-based pruning with flow algorithms
    - LightRAG: Dual-level (entity + relationship) retrieval

    Attributes:
        bucket_name: GCS bucket name
        prefix: Path prefix within bucket (default: "graph/")
        timezone: Timezone for timestamps
    """

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "graph/",
        timezone: str = "Pacific/Auckland"
    ):
        self.bucket_name = bucket_name
        self.prefix = prefix.rstrip("/") + "/"
        self.timezone = ZoneInfo(timezone)
        self._client: Optional[storage.Client] = None

        # In-memory caches (loaded on demand)
        self._node_index: Optional[Dict[str, Dict]] = None
        self._edge_index: Optional[Dict[str, List[Dict]]] = None
        self._type_index: Optional[Dict[str, Set[str]]] = None
        self._schema: Optional[Dict] = None

    @property
    def client(self) -> storage.Client:
        """Lazy-load storage client."""
        if self._client is None:
            self._client = storage.Client()
        return self._client

    @property
    def bucket(self) -> storage.Bucket:
        """Get the GCS bucket."""
        return self.client.bucket(self.bucket_name)

    # -------------------------------------------------------------------------
    # Path Helpers
    # -------------------------------------------------------------------------

    def _nodes_path(self, node_type: str) -> str:
        """Get path to nodes file for a type."""
        return f"{self.prefix}nodes/{node_type.lower()}.jsonl"

    def _edges_path(self) -> str:
        """Get path to edges file."""
        return f"{self.prefix}edges/relationships.jsonl"

    def _index_path(self, name: str) -> str:
        """Get path to an index file."""
        return f"{self.prefix}indexes/{name}.json"

    def _schema_path(self) -> str:
        """Get path to schema file."""
        return f"{self.prefix}schema.json"

    # -------------------------------------------------------------------------
    # Index Management
    # -------------------------------------------------------------------------

    def _load_indexes(self) -> None:
        """Load all indexes into memory."""
        if self._node_index is not None:
            return

        self._node_index = {}
        self._edge_index = defaultdict(list)
        self._type_index = defaultdict(set)

        # Load node index
        blob = self.bucket.blob(self._index_path("node_index"))
        if blob.exists():
            data = json.loads(blob.download_as_text())
            self._node_index = data.get("nodes", {})

        # Load type index
        blob = self.bucket.blob(self._index_path("by_type"))
        if blob.exists():
            data = json.loads(blob.download_as_text())
            self._type_index = {k: set(v) for k, v in data.get("types", {}).items()}

        # Load edge index
        blob = self.bucket.blob(self._edges_path())
        if blob.exists():
            for line in blob.download_as_text().strip().split("\n"):
                if line:
                    edge = json.loads(line)
                    self._edge_index[edge["from_id"]].append(edge)
                    self._edge_index[edge["to_id"]].append(edge)

    def _save_indexes(self) -> None:
        """Persist indexes to GCS."""
        # Save node index
        blob = self.bucket.blob(self._index_path("node_index"))
        blob.upload_from_string(
            json.dumps({"nodes": self._node_index}, indent=2),
            content_type="application/json"
        )

        # Save type index
        blob = self.bucket.blob(self._index_path("by_type"))
        type_data = {k: list(v) for k, v in self._type_index.items()}
        blob.upload_from_string(
            json.dumps({"types": type_data}, indent=2),
            content_type="application/json"
        )

    def _save_edges(self) -> None:
        """Persist edges to GCS."""
        # Deduplicate edges and write
        seen_edges = {}
        for edges in self._edge_index.values():
            for edge in edges:
                seen_edges[edge["@id"]] = edge

        lines = [json.dumps(e) for e in seen_edges.values()]
        blob = self.bucket.blob(self._edges_path())
        blob.upload_from_string("\n".join(lines), content_type="application/jsonl")

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    def create_node(
        self,
        node_type: str,
        node_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a node in the graph."""
        self._load_indexes()

        if node_id in self._node_index:
            raise ValueError(f"Node already exists: {node_id}")

        now = datetime.now(self.timezone).isoformat()

        # Build JSON-LD node
        node = {
            "@type": node_type,
            "@id": node_id,
            "created_at": now,
            "updated_at": now,
            **data
        }

        # Store in type-specific JSONL file
        blob = self.bucket.blob(self._nodes_path(node_type))
        existing = ""
        if blob.exists():
            existing = blob.download_as_text()
            if existing and not existing.endswith("\n"):
                existing += "\n"

        blob.upload_from_string(
            existing + json.dumps(node) + "\n",
            content_type="application/jsonl"
        )

        # Update indexes
        self._node_index[node_id] = {
            "type": node_type,
            "file": self._nodes_path(node_type)
        }
        self._type_index[node_type].add(node_id)
        self._save_indexes()

        return node

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID."""
        self._load_indexes()

        if node_id not in self._node_index:
            return None

        info = self._node_index[node_id]
        blob = self.bucket.blob(info["file"])

        if not blob.exists():
            return None

        for line in blob.download_as_text().strip().split("\n"):
            if line:
                node = json.loads(line)
                if node.get("@id") == node_id:
                    return node

        return None

    def update_node(
        self,
        node_id: str,
        data: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """Update a node."""
        self._load_indexes()

        if node_id not in self._node_index:
            raise KeyError(f"Node not found: {node_id}")

        info = self._node_index[node_id]
        blob = self.bucket.blob(info["file"])
        lines = blob.download_as_text().strip().split("\n")

        updated_node = None
        new_lines = []

        for line in lines:
            if not line:
                continue
            node = json.loads(line)
            if node.get("@id") == node_id:
                if merge:
                    node.update(data)
                else:
                    node = {
                        "@type": info["type"],
                        "@id": node_id,
                        "created_at": node.get("created_at"),
                        **data
                    }
                node["updated_at"] = datetime.now(self.timezone).isoformat()
                updated_node = node
            new_lines.append(json.dumps(node))

        blob.upload_from_string("\n".join(new_lines) + "\n", content_type="application/jsonl")
        return updated_node

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its associated edges."""
        self._load_indexes()

        if node_id not in self._node_index:
            return False

        info = self._node_index[node_id]

        # Remove from JSONL file
        blob = self.bucket.blob(info["file"])
        if blob.exists():
            lines = blob.download_as_text().strip().split("\n")
            new_lines = [
                line for line in lines
                if line and json.loads(line).get("@id") != node_id
            ]
            blob.upload_from_string("\n".join(new_lines) + "\n", content_type="application/jsonl")

        # Delete associated edges
        self.delete_edges_for_node(node_id)

        # Update indexes
        del self._node_index[node_id]
        self._type_index[info["type"]].discard(node_id)
        self._save_indexes()

        return True

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists."""
        self._load_indexes()
        return node_id in self._node_index

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
        self._load_indexes()

        if from_id not in self._node_index:
            raise KeyError(f"Source node not found: {from_id}")
        if to_id not in self._node_index:
            raise KeyError(f"Target node not found: {to_id}")

        now = datetime.now(self.timezone).isoformat()
        edge_id = f"edge:{uuid.uuid4().hex[:12]}"

        edge = {
            "@id": edge_id,
            "@type": "Edge",
            "from_id": from_id,
            "relation": relation,
            "to_id": to_id,
            "created_at": now,
            **(data or {})
        }

        # Add to edge index
        self._edge_index[from_id].append(edge)
        self._edge_index[to_id].append(edge)
        self._save_edges()

        return edge

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get edges connected to a node."""
        self._load_indexes()

        edges = self._edge_index.get(node_id, [])
        results = []

        for edge in edges:
            # Direction filter
            if direction == "outgoing" and edge["from_id"] != node_id:
                continue
            if direction == "incoming" and edge["to_id"] != node_id:
                continue

            # Relation filter
            if relation and edge["relation"] != relation:
                continue

            results.append(edge)

        return results

    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge by ID."""
        self._load_indexes()

        found = False
        for node_id in list(self._edge_index.keys()):
            self._edge_index[node_id] = [
                e for e in self._edge_index[node_id]
                if e["@id"] != edge_id or not (found := True)
            ]

        if found:
            self._save_edges()
        return found

    def delete_edges_for_node(self, node_id: str) -> int:
        """Delete all edges connected to a node."""
        self._load_indexes()

        # Collect edge IDs to delete
        edge_ids_to_delete = {
            edge["@id"] for edge in self._edge_index.get(node_id, [])
        }

        if not edge_ids_to_delete:
            return 0

        # Remove from all nodes' edge lists
        for nid in list(self._edge_index.keys()):
            self._edge_index[nid] = [
                e for e in self._edge_index[nid]
                if e["@id"] not in edge_ids_to_delete
            ]

        self._save_edges()
        return len(edge_ids_to_delete)

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
        self._load_indexes()

        # Determine which types to search
        if node_type:
            types_to_search = [node_type] if node_type in self._type_index else []
        else:
            types_to_search = list(self._type_index.keys())

        results = []

        for t in types_to_search:
            blob = self.bucket.blob(self._nodes_path(t))
            if not blob.exists():
                continue

            for line in blob.download_as_text().strip().split("\n"):
                if not line:
                    continue
                node = json.loads(line)

                # Apply filters
                if filters:
                    match = all(
                        node.get(k) == v for k, v in filters.items()
                    )
                    if not match:
                        continue

                results.append(node)

        # Sort by created_at descending
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Apply pagination
        return results[offset:offset + limit]

    def count_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """Count nodes matching criteria."""
        # For simple counts without filters, use index
        if not filters:
            self._load_indexes()
            if node_type:
                return len(self._type_index.get(node_type, set()))
            return len(self._node_index)

        # Otherwise, do full query
        return len(self.query_nodes(node_type, filters, limit=10000))

    # -------------------------------------------------------------------------
    # Traversal Operations (GraphRAG / PathRAG support)
    # -------------------------------------------------------------------------

    def traverse(
        self,
        start_id: str,
        depth: int = 2,
        relations: Optional[List[str]] = None,
        direction: str = "both"
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting node.

        Implements breadth-first traversal suitable for GraphRAG
        community detection and PathRAG path extraction.
        """
        self._load_indexes()

        visited_nodes: Set[str] = set()
        visited_edges: Set[str] = set()
        nodes: List[Dict] = []
        edges: List[Dict] = []

        # BFS traversal
        current_level = {start_id}

        for _ in range(depth + 1):
            next_level: Set[str] = set()

            for node_id in current_level:
                if node_id in visited_nodes:
                    continue
                visited_nodes.add(node_id)

                # Get node
                node = self.get_node(node_id)
                if node:
                    nodes.append(node)

                # Get edges
                node_edges = self.get_edges(node_id, direction, None)
                for edge in node_edges:
                    # Filter by relation type
                    if relations and edge["relation"] not in relations:
                        continue

                    if edge["@id"] not in visited_edges:
                        visited_edges.add(edge["@id"])
                        edges.append(edge)

                        # Add connected node to next level
                        other_id = edge["to_id"] if edge["from_id"] == node_id else edge["from_id"]
                        if other_id not in visited_nodes:
                            next_level.add(other_id)

            current_level = next_level

        return {
            "start_node": start_id,
            "depth": depth,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges
        }

    def get_subgraph(
        self,
        node_id: str,
        depth: int = 2,
        include_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract a subgraph for LLM context (JSON-LD format).

        Optimized for GraphRAG and PathRAG retrieval patterns.
        Returns clean JSON-LD that LLMs can reason over directly.
        """
        traversal = self.traverse(node_id, depth)

        # Filter by types if specified
        nodes = traversal["nodes"]
        if include_types:
            nodes = [n for n in nodes if n.get("@type") in include_types]
            node_ids = {n["@id"] for n in nodes}
            edges = [
                e for e in traversal["edges"]
                if e["from_id"] in node_ids and e["to_id"] in node_ids
            ]
        else:
            edges = traversal["edges"]

        # Build JSON-LD graph
        schema = self.get_schema()

        return {
            "@context": schema.get("@context", {}),
            "@graph": nodes,
            "_edges": edges,
            "_meta": {
                "focal_node": node_id,
                "depth": depth,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "extracted_at": datetime.now(self.timezone).isoformat()
            }
        }

    # -------------------------------------------------------------------------
    # PathRAG: Path-based retrieval
    # -------------------------------------------------------------------------

    def find_paths(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 4,
        relations: Optional[List[str]] = None
    ) -> List[List[Dict[str, Any]]]:
        """Find paths between two nodes (PathRAG pattern).

        Uses depth-limited search to find relational paths.

        Args:
            from_id: Starting node ID
            to_id: Target node ID
            max_depth: Maximum path length
            relations: Optional filter for relation types

        Returns:
            List of paths, each path is a list of alternating nodes and edges
        """
        self._load_indexes()

        paths = []
        visited = set()

        def dfs(current_id: str, target_id: str, path: List, depth: int):
            if depth > max_depth:
                return
            if current_id == target_id:
                paths.append(path.copy())
                return
            if current_id in visited:
                return

            visited.add(current_id)

            for edge in self.get_edges(current_id, "outgoing"):
                if relations and edge["relation"] not in relations:
                    continue

                next_id = edge["to_id"]
                path.append(edge)

                next_node = self.get_node(next_id)
                if next_node:
                    path.append(next_node)
                    dfs(next_id, target_id, path, depth + 1)
                    path.pop()

                path.pop()

            visited.remove(current_id)

        start_node = self.get_node(from_id)
        if start_node:
            dfs(from_id, to_id, [start_node], 0)

        return paths

    def get_path_context(
        self,
        node_ids: List[str],
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """Extract paths between multiple nodes for LLM context.

        This implements the PathRAG approach of finding key relational
        paths between retrieved nodes.

        Args:
            node_ids: List of node IDs to connect
            max_depth: Maximum path length between nodes

        Returns:
            JSON-LD subgraph with paths highlighted
        """
        all_nodes = {}
        all_edges = {}
        all_paths = []

        # Get all pairwise paths
        for i, from_id in enumerate(node_ids):
            for to_id in node_ids[i + 1:]:
                paths = self.find_paths(from_id, to_id, max_depth)
                for path in paths:
                    path_info = {
                        "from": from_id,
                        "to": to_id,
                        "steps": []
                    }
                    for item in path:
                        if "@type" in item and item["@type"] != "Edge":
                            all_nodes[item["@id"]] = item
                            path_info["steps"].append({"node": item["@id"]})
                        elif item.get("@type") == "Edge":
                            all_edges[item["@id"]] = item
                            path_info["steps"].append({
                                "edge": item["@id"],
                                "relation": item["relation"]
                            })
                    all_paths.append(path_info)

        schema = self.get_schema()

        return {
            "@context": schema.get("@context", {}),
            "@graph": list(all_nodes.values()),
            "_edges": list(all_edges.values()),
            "_paths": all_paths,
            "_meta": {
                "query_nodes": node_ids,
                "path_count": len(all_paths),
                "node_count": len(all_nodes),
                "edge_count": len(all_edges),
                "extracted_at": datetime.now(self.timezone).isoformat()
            }
        }

    # -------------------------------------------------------------------------
    # LightRAG: Dual-level retrieval
    # -------------------------------------------------------------------------

    def get_entity_context(
        self,
        entity_ids: List[str],
        include_relations: bool = True,
        depth: int = 1
    ) -> Dict[str, Any]:
        """Get context for entities (LightRAG low-level retrieval).

        Args:
            entity_ids: List of entity node IDs
            include_relations: Whether to include relationship info
            depth: How many hops of neighbors to include

        Returns:
            JSON-LD context optimized for entity-level queries
        """
        nodes = {}
        edges = {}

        for entity_id in entity_ids:
            subgraph = self.traverse(entity_id, depth)
            for node in subgraph["nodes"]:
                nodes[node["@id"]] = node
            if include_relations:
                for edge in subgraph["edges"]:
                    edges[edge["@id"]] = edge

        schema = self.get_schema()

        return {
            "@context": schema.get("@context", {}),
            "@graph": list(nodes.values()),
            "_edges": list(edges.values()) if include_relations else [],
            "_meta": {
                "query_entities": entity_ids,
                "retrieval_type": "entity",
                "depth": depth,
                "node_count": len(nodes),
                "extracted_at": datetime.now(self.timezone).isoformat()
            }
        }

    def get_relation_context(
        self,
        relation_types: List[str],
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get context for relation types (LightRAG high-level retrieval).

        Args:
            relation_types: List of relation types to retrieve
            limit: Maximum edges per relation type

        Returns:
            JSON-LD context optimized for relationship-level queries
        """
        self._load_indexes()

        edges = []
        node_ids = set()

        # Collect edges matching relation types
        seen_edges = set()
        for edge_list in self._edge_index.values():
            for edge in edge_list:
                if edge["relation"] in relation_types:
                    if edge["@id"] not in seen_edges:
                        seen_edges.add(edge["@id"])
                        edges.append(edge)
                        node_ids.add(edge["from_id"])
                        node_ids.add(edge["to_id"])

                        if len(edges) >= limit * len(relation_types):
                            break

        # Get associated nodes
        nodes = [self.get_node(nid) for nid in node_ids]
        nodes = [n for n in nodes if n]

        schema = self.get_schema()

        return {
            "@context": schema.get("@context", {}),
            "@graph": nodes,
            "_edges": edges,
            "_meta": {
                "query_relations": relation_types,
                "retrieval_type": "relation",
                "node_count": len(nodes),
                "edge_count": len(edges),
                "extracted_at": datetime.now(self.timezone).isoformat()
            }
        }

    # -------------------------------------------------------------------------
    # Bulk Operations
    # -------------------------------------------------------------------------

    def bulk_create_nodes(
        self,
        nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple nodes in a batch."""
        self._load_indexes()

        created = []
        by_type: Dict[str, List[Dict]] = defaultdict(list)
        now = datetime.now(self.timezone).isoformat()

        for node_spec in nodes:
            node_type = node_spec["type"]
            node_id = node_spec["id"]
            data = node_spec.get("data", {})

            if node_id in self._node_index:
                continue  # Skip duplicates

            node = {
                "@type": node_type,
                "@id": node_id,
                "created_at": now,
                "updated_at": now,
                **data
            }

            by_type[node_type].append(node)
            self._node_index[node_id] = {
                "type": node_type,
                "file": self._nodes_path(node_type)
            }
            self._type_index[node_type].add(node_id)
            created.append(node)

        # Write to type files
        for node_type, type_nodes in by_type.items():
            blob = self.bucket.blob(self._nodes_path(node_type))
            existing = ""
            if blob.exists():
                existing = blob.download_as_text()
                if existing and not existing.endswith("\n"):
                    existing += "\n"

            new_lines = "\n".join(json.dumps(n) for n in type_nodes)
            blob.upload_from_string(
                existing + new_lines + "\n",
                content_type="application/jsonl"
            )

        self._save_indexes()
        return created

    def bulk_create_edges(
        self,
        edges: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple edges in a batch."""
        self._load_indexes()

        created = []
        now = datetime.now(self.timezone).isoformat()

        for edge_spec in edges:
            from_id = edge_spec["from_id"]
            relation = edge_spec["relation"]
            to_id = edge_spec["to_id"]
            data = edge_spec.get("data", {})

            if from_id not in self._node_index or to_id not in self._node_index:
                continue  # Skip if nodes don't exist

            edge_id = f"edge:{uuid.uuid4().hex[:12]}"
            edge = {
                "@id": edge_id,
                "@type": "Edge",
                "from_id": from_id,
                "relation": relation,
                "to_id": to_id,
                "created_at": now,
                **data
            }

            self._edge_index[from_id].append(edge)
            self._edge_index[to_id].append(edge)
            created.append(edge)

        self._save_edges()
        return created

    # -------------------------------------------------------------------------
    # Schema & Metadata
    # -------------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Any]:
        """Get the graph schema definition."""
        if self._schema:
            return self._schema

        blob = self.bucket.blob(self._schema_path())

        if blob.exists():
            self._schema = json.loads(blob.download_as_text())
            return self._schema

        # Default schema
        self._schema = {
            "@context": {
                "@vocab": "https://schema.org/",
                "Task": "https://schema.org/Action",
                "Topic": "https://schema.org/Thing",
                "Goal": "https://schema.org/Thing",
                "Project": "https://schema.org/Project",
                "Person": "https://schema.org/Person",
                "hasTopic": {"@type": "@id"},
                "parent": {"@type": "@id"},
                "derivedFrom": {"@type": "@id"},
                "supportsGoal": {"@type": "@id"},
                "hasTask": {"@type": "@id"},
                "dependsOn": {"@type": "@id"},
                "assignedTo": {"@type": "@id"},
                "relatedTo": {"@type": "@id"}
            },
            "version": "1.0",
            "node_types": ["Task", "Topic", "Goal", "Project", "Person", "Transcript"],
            "relation_types": [
                "hasTopic", "parent", "derivedFrom", "supportsGoal",
                "hasTask", "dependsOn", "assignedTo", "relatedTo"
            ]
        }

        # Save default schema
        blob.upload_from_string(
            json.dumps(self._schema, indent=2),
            content_type="application/json"
        )

        return self._schema

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        self._load_indexes()

        edge_count = len({
            e["@id"]
            for edges in self._edge_index.values()
            for e in edges
        })

        return {
            "total_nodes": len(self._node_index),
            "total_edges": edge_count,
            "nodes_by_type": {k: len(v) for k, v in self._type_index.items()},
            "storage_backend": "gcs_jsonld",
            "bucket": self.bucket_name,
            "prefix": self.prefix
        }

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize the backend (create schema, indexes)."""
        # Ensure schema exists
        self.get_schema()

        # Initialize empty indexes if needed
        self._load_indexes()
        self._save_indexes()

    def close(self) -> None:
        """Close connections and cleanup."""
        self._client = None
        self._node_index = None
        self._edge_index = None
        self._type_index = None
        self._schema = None
