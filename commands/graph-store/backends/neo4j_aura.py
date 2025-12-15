"""Neo4j Aura Backend Implementation.

Uses Neo4j Aura (free tier available) for graph storage with native
Cypher queries for efficient traversal and pattern matching.

Neo4j Aura Free Tier Limits (as of 2025):
- Up to 200,000 nodes and 400,000 relationships (Classic)
- Or 50,000 nodes / 175,000 relationships (Early Access tier)
- Instance pauses after 3 days of no writes
- One free instance per account

Setup:
1. Create free account at https://neo4j.com/cloud/aura/
2. Create a new AuraDB Free instance
3. Save the connection URI and password
4. Store credentials in Secret Manager or environment variables

References:
- Neo4j Python Driver: https://neo4j.com/docs/python-manual/current/
- Neo4j Aura: https://neo4j.com/docs/aura/
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from zoneinfo import ZoneInfo

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from .base import GraphBackend


class Neo4jAuraBackend(GraphBackend):
    """Graph backend using Neo4j Aura.

    Provides native graph database capabilities with Cypher queries
    for efficient traversal, pattern matching, and graph algorithms.

    Environment variables:
        NEO4J_URI: Connection URI (neo4j+s://xxx.databases.neo4j.io)
        NEO4J_USERNAME: Database username (usually 'neo4j')
        NEO4J_PASSWORD: Database password

    Attributes:
        uri: Neo4j connection URI
        username: Database username
        password: Database password
        timezone: Timezone for timestamps
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timezone: str = "Pacific/Auckland"
    ):
        self.uri = uri or os.environ.get("NEO4J_URI")
        self.username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD")
        self.timezone = ZoneInfo(timezone)
        self._driver = None

        if not self.uri or not self.password:
            raise ValueError("NEO4J_URI and NEO4J_PASSWORD are required")

    @property
    def driver(self):
        """Lazy-load Neo4j driver."""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password)
            )
        return self._driver

    def _now(self) -> str:
        """Get current timestamp."""
        return datetime.now(self.timezone).isoformat()

    def _run_query(self, query: str, parameters: dict = None) -> List[Dict]:
        """Execute a Cypher query and return results."""
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def _run_write(self, query: str, parameters: dict = None) -> Any:
        """Execute a write query."""
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return result.single()

    # -------------------------------------------------------------------------
    # Node Operations
    # -------------------------------------------------------------------------

    def create_node(
        self,
        node_type: str,
        node_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a node in Neo4j."""
        now = self._now()

        # Flatten nested data for Neo4j properties
        props = {
            "id": node_id,
            "created_at": now,
            "updated_at": now,
            **{k: json.dumps(v) if isinstance(v, (list, dict)) else v
               for k, v in data.items()}
        }

        query = f"""
        CREATE (n:{node_type} $props)
        RETURN n
        """

        result = self._run_write(query, {"props": props})
        node_data = dict(result["n"])

        # Convert back to JSON-LD format
        return self._neo4j_to_jsonld(node_data, node_type)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID."""
        query = """
        MATCH (n {id: $id})
        RETURN n, labels(n) as labels
        """

        results = self._run_query(query, {"id": node_id})
        if not results:
            return None

        record = results[0]
        node_type = record["labels"][0] if record["labels"] else "Node"
        return self._neo4j_to_jsonld(dict(record["n"]), node_type)

    def update_node(
        self,
        node_id: str,
        data: Dict[str, Any],
        merge: bool = True
    ) -> Dict[str, Any]:
        """Update a node."""
        now = self._now()

        # Prepare properties
        props = {
            "updated_at": now,
            **{k: json.dumps(v) if isinstance(v, (list, dict)) else v
               for k, v in data.items()}
        }

        if merge:
            query = """
            MATCH (n {id: $id})
            SET n += $props
            RETURN n, labels(n) as labels
            """
        else:
            query = """
            MATCH (n {id: $id})
            SET n = $props
            SET n.id = $id
            RETURN n, labels(n) as labels
            """

        results = self._run_query(query, {"id": node_id, "props": props})
        if not results:
            raise KeyError(f"Node not found: {node_id}")

        record = results[0]
        node_type = record["labels"][0] if record["labels"] else "Node"
        return self._neo4j_to_jsonld(dict(record["n"]), node_type)

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its relationships."""
        query = """
        MATCH (n {id: $id})
        DETACH DELETE n
        RETURN count(n) as deleted
        """

        results = self._run_query(query, {"id": node_id})
        return results[0]["deleted"] > 0 if results else False

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists."""
        query = """
        MATCH (n {id: $id})
        RETURN count(n) > 0 as exists
        """

        results = self._run_query(query, {"id": node_id})
        return results[0]["exists"] if results else False

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
        now = self._now()
        edge_id = f"edge:{uuid.uuid4().hex[:12]}"

        props = {
            "id": edge_id,
            "created_at": now,
            **(data or {})
        }

        # Sanitize relation name for Cypher (uppercase, underscores)
        rel_type = relation.upper().replace(" ", "_")

        query = f"""
        MATCH (from {{id: $from_id}}), (to {{id: $to_id}})
        CREATE (from)-[r:{rel_type} $props]->(to)
        RETURN r
        """

        try:
            result = self._run_write(query, {
                "from_id": from_id,
                "to_id": to_id,
                "props": props
            })

            return {
                "@id": edge_id,
                "@type": "Edge",
                "from_id": from_id,
                "relation": relation,
                "to_id": to_id,
                "created_at": now,
                **(data or {})
            }
        except Neo4jError as e:
            raise KeyError(f"Failed to create edge: {e}")

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get edges connected to a node."""
        rel_filter = f":{relation.upper()}" if relation else ""

        if direction == "outgoing":
            query = f"""
            MATCH (n {{id: $id}})-[r{rel_filter}]->(m)
            RETURN r, n.id as from_id, m.id as to_id, type(r) as rel_type
            """
        elif direction == "incoming":
            query = f"""
            MATCH (n {{id: $id}})<-[r{rel_filter}]-(m)
            RETURN r, m.id as from_id, n.id as to_id, type(r) as rel_type
            """
        else:
            query = f"""
            MATCH (n {{id: $id}})-[r{rel_filter}]-(m)
            RETURN r,
                   CASE WHEN startNode(r).id = $id THEN startNode(r).id ELSE endNode(r).id END as from_id,
                   CASE WHEN startNode(r).id = $id THEN endNode(r).id ELSE startNode(r).id END as to_id,
                   type(r) as rel_type
            """

        results = self._run_query(query, {"id": node_id})
        edges = []

        for record in results:
            edge_data = dict(record["r"]) if record["r"] else {}
            edges.append({
                "@id": edge_data.get("id", f"edge:{uuid.uuid4().hex[:8]}"),
                "@type": "Edge",
                "from_id": record["from_id"],
                "relation": record["rel_type"].lower(),
                "to_id": record["to_id"],
                **{k: v for k, v in edge_data.items() if k != "id"}
            })

        return edges

    def delete_edge(self, edge_id: str) -> bool:
        """Delete an edge by ID."""
        query = """
        MATCH ()-[r {id: $id}]-()
        DELETE r
        RETURN count(r) as deleted
        """

        results = self._run_query(query, {"id": edge_id})
        return results[0]["deleted"] > 0 if results else False

    def delete_edges_for_node(self, node_id: str) -> int:
        """Delete all edges connected to a node."""
        query = """
        MATCH (n {id: $id})-[r]-()
        DELETE r
        RETURN count(r) as deleted
        """

        results = self._run_query(query, {"id": node_id})
        return results[0]["deleted"] if results else 0

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
        label_filter = f":{node_type}" if node_type else ""

        # Build WHERE clause
        where_clauses = []
        params = {"limit": limit, "offset": offset}

        if filters:
            for i, (key, value) in enumerate(filters.items()):
                param_name = f"filter_{i}"
                where_clauses.append(f"n.{key} = ${param_name}")
                params[param_name] = value

        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
        MATCH (n{label_filter})
        {where_str}
        RETURN n, labels(n) as labels
        ORDER BY n.created_at DESC
        SKIP $offset
        LIMIT $limit
        """

        results = self._run_query(query, params)
        nodes = []

        for record in results:
            node_type = record["labels"][0] if record["labels"] else "Node"
            nodes.append(self._neo4j_to_jsonld(dict(record["n"]), node_type))

        return nodes

    def count_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """Count nodes matching criteria."""
        label_filter = f":{node_type}" if node_type else ""

        where_clauses = []
        params = {}

        if filters:
            for i, (key, value) in enumerate(filters.items()):
                param_name = f"filter_{i}"
                where_clauses.append(f"n.{key} = ${param_name}")
                params[param_name] = value

        where_str = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
        MATCH (n{label_filter})
        {where_str}
        RETURN count(n) as count
        """

        results = self._run_query(query, params)
        return results[0]["count"] if results else 0

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
        """Traverse the graph using Neo4j's native path finding."""
        rel_filter = ""
        if relations:
            rel_types = "|".join(r.upper() for r in relations)
            rel_filter = f":{rel_types}"

        if direction == "outgoing":
            path_pattern = f"-[r{rel_filter}*1..{depth}]->"
        elif direction == "incoming":
            path_pattern = f"<-[r{rel_filter}*1..{depth}]-"
        else:
            path_pattern = f"-[r{rel_filter}*1..{depth}]-"

        query = f"""
        MATCH path = (start {{id: $start_id}}){path_pattern}(end)
        WITH nodes(path) as pathNodes, relationships(path) as pathRels
        UNWIND pathNodes as n
        WITH collect(DISTINCT n) as allNodes, collect(DISTINCT pathRels) as allRels
        UNWIND allRels as relList
        UNWIND relList as r
        WITH allNodes, collect(DISTINCT r) as allEdges
        RETURN allNodes, allEdges
        """

        results = self._run_query(query, {"start_id": start_id})

        nodes = []
        edges = []

        if results:
            record = results[0]

            for node in record.get("allNodes", []):
                node_dict = dict(node)
                # Get label from node
                labels = list(node.labels) if hasattr(node, 'labels') else ["Node"]
                nodes.append(self._neo4j_to_jsonld(node_dict, labels[0]))

            for rel in record.get("allEdges", []):
                rel_dict = dict(rel) if rel else {}
                edges.append({
                    "@id": rel_dict.get("id", f"edge:{uuid.uuid4().hex[:8]}"),
                    "@type": "Edge",
                    "from_id": rel.start_node["id"] if hasattr(rel, 'start_node') else "",
                    "relation": rel.type.lower() if hasattr(rel, 'type') else "",
                    "to_id": rel.end_node["id"] if hasattr(rel, 'end_node') else "",
                    **{k: v for k, v in rel_dict.items() if k != "id"}
                })

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
        """Extract a subgraph for LLM context using Neo4j traversal."""
        traversal = self.traverse(node_id, depth)

        nodes = traversal["nodes"]
        edges = traversal["edges"]

        # Filter by types if specified
        if include_types:
            nodes = [n for n in nodes if n.get("@type") in include_types]
            node_ids = {n["@id"] for n in nodes}
            edges = [e for e in edges
                     if e["from_id"] in node_ids and e["to_id"] in node_ids]

        return {
            "@context": self._get_context(),
            "@graph": nodes,
            "_edges": edges,
            "_meta": {
                "focal_node": node_id,
                "depth": depth,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "extracted_at": self._now(),
                "backend": "neo4j_aura"
            }
        }

    # -------------------------------------------------------------------------
    # PathRAG Support
    # -------------------------------------------------------------------------

    def find_paths(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 4,
        relations: Optional[List[str]] = None
    ) -> List[List[Dict[str, Any]]]:
        """Find paths between two nodes using Neo4j's shortestPath."""
        rel_filter = ""
        if relations:
            rel_types = "|".join(r.upper() for r in relations)
            rel_filter = f":{rel_types}"

        query = f"""
        MATCH path = allShortestPaths(
            (start {{id: $from_id}})-[{rel_filter}*..{max_depth}]-(end {{id: $to_id}})
        )
        RETURN path
        LIMIT 10
        """

        results = self._run_query(query, {"from_id": from_id, "to_id": to_id})
        paths = []

        for record in results:
            path = record.get("path")
            if path:
                path_items = []
                for item in path:
                    if hasattr(item, 'labels'):  # It's a node
                        node_dict = dict(item)
                        labels = list(item.labels)
                        path_items.append(self._neo4j_to_jsonld(node_dict, labels[0] if labels else "Node"))
                    else:  # It's a relationship
                        rel_dict = dict(item) if item else {}
                        path_items.append({
                            "@id": rel_dict.get("id", f"edge:{uuid.uuid4().hex[:8]}"),
                            "@type": "Edge",
                            "relation": item.type.lower() if hasattr(item, 'type') else "",
                            **{k: v for k, v in rel_dict.items() if k != "id"}
                        })
                paths.append(path_items)

        return paths

    def get_path_context(
        self,
        node_ids: List[str],
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """Extract paths between multiple nodes for LLM context."""
        all_nodes = {}
        all_edges = {}
        all_paths = []

        # Get pairwise paths
        for i, from_id in enumerate(node_ids):
            for to_id in node_ids[i + 1:]:
                paths = self.find_paths(from_id, to_id, max_depth)
                for path in paths:
                    path_info = {"from": from_id, "to": to_id, "steps": []}
                    for item in path:
                        if item.get("@type") != "Edge":
                            all_nodes[item["@id"]] = item
                            path_info["steps"].append({"node": item["@id"]})
                        else:
                            all_edges[item["@id"]] = item
                            path_info["steps"].append({
                                "edge": item["@id"],
                                "relation": item.get("relation", "")
                            })
                    all_paths.append(path_info)

        return {
            "@context": self._get_context(),
            "@graph": list(all_nodes.values()),
            "_edges": list(all_edges.values()),
            "_paths": all_paths,
            "_meta": {
                "query_nodes": node_ids,
                "path_count": len(all_paths),
                "node_count": len(all_nodes),
                "edge_count": len(all_edges),
                "extracted_at": self._now(),
                "backend": "neo4j_aura"
            }
        }

    # -------------------------------------------------------------------------
    # LightRAG Support
    # -------------------------------------------------------------------------

    def get_entity_context(
        self,
        entity_ids: List[str],
        include_relations: bool = True,
        depth: int = 1
    ) -> Dict[str, Any]:
        """Get context for entities (LightRAG low-level retrieval)."""
        all_nodes = {}
        all_edges = {}

        for entity_id in entity_ids:
            subgraph = self.traverse(entity_id, depth)
            for node in subgraph["nodes"]:
                all_nodes[node["@id"]] = node
            if include_relations:
                for edge in subgraph["edges"]:
                    all_edges[edge["@id"]] = edge

        return {
            "@context": self._get_context(),
            "@graph": list(all_nodes.values()),
            "_edges": list(all_edges.values()) if include_relations else [],
            "_meta": {
                "query_entities": entity_ids,
                "retrieval_type": "entity",
                "depth": depth,
                "node_count": len(all_nodes),
                "extracted_at": self._now(),
                "backend": "neo4j_aura"
            }
        }

    def get_relation_context(
        self,
        relation_types: List[str],
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get context for relation types (LightRAG high-level retrieval)."""
        rel_types = "|".join(r.upper() for r in relation_types)

        query = f"""
        MATCH (from)-[r:{rel_types}]->(to)
        RETURN from, r, to, labels(from) as from_labels, labels(to) as to_labels
        LIMIT $limit
        """

        results = self._run_query(query, {"limit": limit})

        nodes = {}
        edges = []

        for record in results:
            from_node = dict(record["from"])
            to_node = dict(record["to"])
            rel = dict(record["r"]) if record["r"] else {}

            from_type = record["from_labels"][0] if record["from_labels"] else "Node"
            to_type = record["to_labels"][0] if record["to_labels"] else "Node"

            nodes[from_node["id"]] = self._neo4j_to_jsonld(from_node, from_type)
            nodes[to_node["id"]] = self._neo4j_to_jsonld(to_node, to_type)

            edges.append({
                "@id": rel.get("id", f"edge:{uuid.uuid4().hex[:8]}"),
                "@type": "Edge",
                "from_id": from_node["id"],
                "relation": record["r"].type.lower() if hasattr(record["r"], 'type') else "",
                "to_id": to_node["id"],
                **{k: v for k, v in rel.items() if k != "id"}
            })

        return {
            "@context": self._get_context(),
            "@graph": list(nodes.values()),
            "_edges": edges,
            "_meta": {
                "query_relations": relation_types,
                "retrieval_type": "relation",
                "node_count": len(nodes),
                "edge_count": len(edges),
                "extracted_at": self._now(),
                "backend": "neo4j_aura"
            }
        }

    # -------------------------------------------------------------------------
    # Bulk Operations
    # -------------------------------------------------------------------------

    def bulk_create_nodes(
        self,
        nodes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple nodes using UNWIND for efficiency."""
        now = self._now()
        created = []

        # Group by type for efficient batch creation
        by_type: Dict[str, List[Dict]] = {}
        for node in nodes:
            node_type = node.get("type", "Node")
            if node_type not in by_type:
                by_type[node_type] = []

            props = {
                "id": node.get("id", f"{node_type.lower()}:{uuid.uuid4().hex[:12]}"),
                "created_at": now,
                "updated_at": now,
                **{k: json.dumps(v) if isinstance(v, (list, dict)) else v
                   for k, v in node.get("data", {}).items()}
            }
            by_type[node_type].append(props)

        for node_type, props_list in by_type.items():
            query = f"""
            UNWIND $props as p
            CREATE (n:{node_type})
            SET n = p
            RETURN n
            """

            results = self._run_query(query, {"props": props_list})
            for record in results:
                created.append(self._neo4j_to_jsonld(dict(record["n"]), node_type))

        return created

    def bulk_create_edges(
        self,
        edges: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Create multiple edges."""
        now = self._now()
        created = []

        for edge in edges:
            try:
                result = self.create_edge(
                    edge["from_id"],
                    edge["relation"],
                    edge["to_id"],
                    edge.get("data")
                )
                created.append(result)
            except KeyError:
                continue  # Skip if nodes don't exist

        return created

    # -------------------------------------------------------------------------
    # Schema & Metadata
    # -------------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Any]:
        """Get the graph schema from Neo4j."""
        # Get all labels
        labels_query = "CALL db.labels()"
        labels = [r["label"] for r in self._run_query(labels_query)]

        # Get all relationship types
        rels_query = "CALL db.relationshipTypes()"
        rel_types = [r["relationshipType"].lower() for r in self._run_query(rels_query)]

        return {
            "@context": self._get_context(),
            "version": "1.0",
            "node_types": labels,
            "relation_types": rel_types,
            "backend": "neo4j_aura"
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        # Node count by label
        nodes_query = """
        CALL db.labels() YIELD label
        CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) as count', {}) YIELD value
        RETURN label, value.count as count
        """

        # Fallback if APOC not available
        try:
            node_counts = {r["label"]: r["count"]
                          for r in self._run_query(nodes_query)}
        except Neo4jError:
            # Simple count without APOC
            node_counts = {}
            labels = [r["label"] for r in self._run_query("CALL db.labels()")]
            for label in labels:
                count_result = self._run_query(
                    f"MATCH (n:{label}) RETURN count(n) as count"
                )
                node_counts[label] = count_result[0]["count"] if count_result else 0

        # Total counts
        total_nodes = sum(node_counts.values())

        edge_count_result = self._run_query(
            "MATCH ()-[r]->() RETURN count(r) as count"
        )
        total_edges = edge_count_result[0]["count"] if edge_count_result else 0

        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "nodes_by_type": node_counts,
            "storage_backend": "neo4j_aura",
            "uri": self.uri[:30] + "..." if self.uri else None
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _neo4j_to_jsonld(self, node_dict: Dict, node_type: str) -> Dict[str, Any]:
        """Convert Neo4j node to JSON-LD format."""
        result = {
            "@type": node_type,
            "@id": node_dict.get("id", ""),
        }

        for key, value in node_dict.items():
            if key == "id":
                continue

            # Try to parse JSON strings back to objects
            if isinstance(value, str):
                try:
                    if value.startswith("[") or value.startswith("{"):
                        value = json.loads(value)
                except json.JSONDecodeError:
                    pass

            result[key] = value

        return result

    def _get_context(self) -> Dict[str, Any]:
        """Get JSON-LD context."""
        return {
            "@vocab": "https://schema.org/",
            "Task": "https://schema.org/Action",
            "Topic": "https://schema.org/Thing",
            "Goal": "https://schema.org/Thing",
            "Project": "https://schema.org/Project",
            "hasTopic": {"@type": "@id"},
            "parent": {"@type": "@id"},
            "derivedFrom": {"@type": "@id"},
            "supportsGoal": {"@type": "@id"},
            "hasTask": {"@type": "@id"},
            "dependsOn": {"@type": "@id"},
            "assignedTo": {"@type": "@id"}
        }

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def initialize(self) -> None:
        """Initialize Neo4j indexes for performance."""
        # Create indexes for common lookups
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (n:Task) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Topic) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Goal) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Project) ON (n.id)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Task) ON (n.status)",
            "CREATE INDEX IF NOT EXISTS FOR (n:Task) ON (n.priority)",
        ]

        for idx_query in indexes:
            try:
                self._run_write(idx_query)
            except Neo4jError:
                pass  # Index may already exist

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
