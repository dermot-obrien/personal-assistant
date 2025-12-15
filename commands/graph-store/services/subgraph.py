"""Subgraph extraction service for LLM context.

Implements GraphRAG, PathRAG, and LightRAG retrieval patterns
for extracting relevant context to feed to LLMs.

References:
    - PathRAG: https://arxiv.org/html/2502.14902v1
    - LightRAG: https://arxiv.org/html/2410.05779v1
    - Microsoft GraphRAG: https://microsoft.github.io/graphrag/
"""

from typing import Optional, List, Dict, Any

from ..backends.base import GraphBackend


class SubgraphService:
    """Service for extracting subgraphs optimized for LLM reasoning.

    Supports multiple retrieval modes:
    - subgraph: Standard graph traversal (GraphRAG style)
    - path: Path-based retrieval (PathRAG style)
    - entity: Entity-level retrieval (LightRAG low-level)
    - relation: Relation-level retrieval (LightRAG high-level)
    """

    def __init__(self, backend: GraphBackend):
        self.backend = backend

    # -------------------------------------------------------------------------
    # GraphRAG: Standard Subgraph Extraction
    # -------------------------------------------------------------------------

    def extract_subgraph(
        self,
        node_id: str,
        depth: int = 2,
        include_types: Optional[List[str]] = None,
        max_nodes: int = 100
    ) -> Dict[str, Any]:
        """Extract a subgraph around a focal node (GraphRAG pattern).

        This provides general-purpose context for LLM reasoning by
        traversing outward from a focal node.

        Args:
            node_id: Central node to expand from
            depth: Maximum traversal depth
            include_types: Optional filter for node types
            max_nodes: Maximum nodes to include

        Returns:
            JSON-LD formatted subgraph ready for LLM consumption
        """
        subgraph = self.backend.get_subgraph(node_id, depth, include_types)

        # Trim if exceeds max_nodes
        if len(subgraph.get("@graph", [])) > max_nodes:
            # Prioritize nodes closer to focal node
            subgraph["@graph"] = subgraph["@graph"][:max_nodes]
            node_ids = {n["@id"] for n in subgraph["@graph"]}
            subgraph["_edges"] = [
                e for e in subgraph.get("_edges", [])
                if e["from_id"] in node_ids and e["to_id"] in node_ids
            ]

        return subgraph

    def extract_multi_focal(
        self,
        node_ids: List[str],
        depth: int = 1,
        include_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract subgraph around multiple focal nodes.

        Useful when the query relates to multiple entities.

        Args:
            node_ids: List of central nodes
            depth: Depth per focal node
            include_types: Optional type filter

        Returns:
            Combined JSON-LD subgraph
        """
        all_nodes = {}
        all_edges = {}

        for node_id in node_ids:
            subgraph = self.backend.get_subgraph(node_id, depth, include_types)
            for node in subgraph.get("@graph", []):
                all_nodes[node["@id"]] = node
            for edge in subgraph.get("_edges", []):
                all_edges[edge["@id"]] = edge

        schema = self.backend.get_schema()

        return {
            "@context": schema.get("@context", {}),
            "@graph": list(all_nodes.values()),
            "_edges": list(all_edges.values()),
            "_meta": {
                "focal_nodes": node_ids,
                "depth": depth,
                "node_count": len(all_nodes),
                "edge_count": len(all_edges),
                "retrieval_mode": "multi_focal"
            }
        }

    # -------------------------------------------------------------------------
    # PathRAG: Path-Based Retrieval
    # -------------------------------------------------------------------------

    def extract_paths(
        self,
        node_ids: List[str],
        max_depth: int = 3,
        relations: Optional[List[str]] = None,
        max_paths: int = 10
    ) -> Dict[str, Any]:
        """Extract relational paths between nodes (PathRAG pattern).

        PathRAG finds key relational paths between retrieved nodes,
        providing structured reasoning chains for the LLM.

        Args:
            node_ids: Nodes to find paths between
            max_depth: Maximum path length
            relations: Optional filter for relation types
            max_paths: Maximum paths to return

        Returns:
            JSON-LD with paths highlighted for LLM reasoning
        """
        # Use backend's path context extraction
        context = self.backend.get_path_context(node_ids, max_depth)

        # Limit paths if needed
        if len(context.get("_paths", [])) > max_paths:
            # Score paths by length (shorter = better)
            paths = context["_paths"]
            paths.sort(key=lambda p: len(p.get("steps", [])))
            context["_paths"] = paths[:max_paths]

        context["_meta"]["retrieval_mode"] = "path"
        return context

    def find_connecting_paths(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 4
    ) -> List[Dict[str, Any]]:
        """Find all paths connecting two specific nodes.

        Args:
            from_id: Source node
            to_id: Target node
            max_depth: Maximum path length

        Returns:
            List of paths, each with nodes and edges
        """
        paths = self.backend.find_paths(from_id, to_id, max_depth)

        # Format paths for LLM consumption
        formatted_paths = []
        for path in paths:
            formatted = {
                "from": from_id,
                "to": to_id,
                "length": (len(path) + 1) // 2,  # Number of nodes
                "nodes": [item for item in path if item.get("@type") != "Edge"],
                "edges": [item for item in path if item.get("@type") == "Edge"],
                "narrative": self._path_to_narrative(path)
            }
            formatted_paths.append(formatted)

        return formatted_paths

    def _path_to_narrative(self, path: List[Dict]) -> str:
        """Convert a path to a natural language narrative.

        This makes paths more interpretable for LLMs.
        """
        parts = []
        for i, item in enumerate(path):
            if item.get("@type") == "Edge":
                relation = item.get("relation", "relates to")
                parts.append(f" --[{relation}]--> ")
            else:
                name = item.get("name") or item.get("description", "")[:30] or item.get("@id")
                node_type = item.get("@type", "node")
                parts.append(f"({node_type}: {name})")

        return "".join(parts)

    # -------------------------------------------------------------------------
    # LightRAG: Dual-Level Retrieval
    # -------------------------------------------------------------------------

    def extract_entity_context(
        self,
        entity_ids: List[str],
        include_relations: bool = True,
        depth: int = 1
    ) -> Dict[str, Any]:
        """Extract entity-level context (LightRAG low-level).

        Focuses on specific entities and their immediate neighborhood.

        Args:
            entity_ids: Entity node IDs to retrieve
            include_relations: Whether to include edges
            depth: How many hops of neighbors

        Returns:
            JSON-LD context for entity-focused queries
        """
        context = self.backend.get_entity_context(entity_ids, include_relations, depth)
        context["_meta"]["retrieval_mode"] = "entity"
        return context

    def extract_relation_context(
        self,
        relation_types: List[str],
        limit: int = 50
    ) -> Dict[str, Any]:
        """Extract relation-level context (LightRAG high-level).

        Retrieves based on relationship types rather than specific entities.
        Useful for queries about patterns or categories.

        Args:
            relation_types: Types of relations to retrieve
            limit: Maximum edges per type

        Returns:
            JSON-LD context for relation-focused queries
        """
        context = self.backend.get_relation_context(relation_types, limit)
        context["_meta"]["retrieval_mode"] = "relation"
        return context

    # -------------------------------------------------------------------------
    # Hybrid Retrieval
    # -------------------------------------------------------------------------

    def extract_hybrid_context(
        self,
        focal_node_id: Optional[str] = None,
        entity_ids: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
        depth: int = 2
    ) -> Dict[str, Any]:
        """Extract context using multiple strategies (HybridRAG).

        Combines subgraph traversal, entity retrieval, and relation
        retrieval for comprehensive context.

        Args:
            focal_node_id: Optional central node for subgraph
            entity_ids: Optional specific entities to include
            relation_types: Optional relation types to include
            depth: Traversal depth

        Returns:
            Combined JSON-LD context
        """
        all_nodes = {}
        all_edges = {}
        meta = {
            "retrieval_mode": "hybrid",
            "strategies_used": []
        }

        # Subgraph extraction
        if focal_node_id:
            subgraph = self.extract_subgraph(focal_node_id, depth)
            for node in subgraph.get("@graph", []):
                all_nodes[node["@id"]] = node
            for edge in subgraph.get("_edges", []):
                all_edges[edge["@id"]] = edge
            meta["strategies_used"].append("subgraph")
            meta["focal_node"] = focal_node_id

        # Entity retrieval
        if entity_ids:
            entity_ctx = self.extract_entity_context(entity_ids, depth=1)
            for node in entity_ctx.get("@graph", []):
                all_nodes[node["@id"]] = node
            for edge in entity_ctx.get("_edges", []):
                all_edges[edge["@id"]] = edge
            meta["strategies_used"].append("entity")
            meta["entity_ids"] = entity_ids

        # Relation retrieval
        if relation_types:
            relation_ctx = self.extract_relation_context(relation_types)
            for node in relation_ctx.get("@graph", []):
                all_nodes[node["@id"]] = node
            for edge in relation_ctx.get("_edges", []):
                all_edges[edge["@id"]] = edge
            meta["strategies_used"].append("relation")
            meta["relation_types"] = relation_types

        schema = self.backend.get_schema()
        meta["node_count"] = len(all_nodes)
        meta["edge_count"] = len(all_edges)

        return {
            "@context": schema.get("@context", {}),
            "@graph": list(all_nodes.values()),
            "_edges": list(all_edges.values()),
            "_meta": meta
        }

    # -------------------------------------------------------------------------
    # Context Formatting for LLMs
    # -------------------------------------------------------------------------

    def format_for_llm(
        self,
        context: Dict[str, Any],
        format_type: str = "json",
        max_tokens: int = 4000
    ) -> str:
        """Format extracted context for LLM consumption.

        Args:
            context: JSON-LD context from extraction methods
            format_type: "json", "markdown", or "narrative"
            max_tokens: Approximate token limit

        Returns:
            Formatted string ready for LLM prompt
        """
        if format_type == "json":
            return self._format_json(context, max_tokens)
        elif format_type == "markdown":
            return self._format_markdown(context, max_tokens)
        elif format_type == "narrative":
            return self._format_narrative(context, max_tokens)
        else:
            return self._format_json(context, max_tokens)

    def _format_json(self, context: Dict[str, Any], max_tokens: int) -> str:
        """Format as clean JSON."""
        import json

        # Remove internal metadata
        output = {
            "@context": context.get("@context", {}),
            "@graph": context.get("@graph", []),
            "relationships": [
                {
                    "from": e["from_id"],
                    "relation": e["relation"],
                    "to": e["to_id"]
                }
                for e in context.get("_edges", [])
            ]
        }

        result = json.dumps(output, indent=2, ensure_ascii=False)

        # Simple truncation if too long (rough estimate: 4 chars per token)
        if len(result) > max_tokens * 4:
            result = result[:max_tokens * 4] + "\n... (truncated)"

        return result

    def _format_markdown(self, context: Dict[str, Any], max_tokens: int) -> str:
        """Format as markdown."""
        lines = ["# Knowledge Graph Context\n"]

        # Group nodes by type
        nodes_by_type: Dict[str, List] = {}
        for node in context.get("@graph", []):
            node_type = node.get("@type", "Unknown")
            if node_type not in nodes_by_type:
                nodes_by_type[node_type] = []
            nodes_by_type[node_type].append(node)

        for node_type, nodes in nodes_by_type.items():
            lines.append(f"\n## {node_type}s\n")
            for node in nodes:
                name = node.get("name") or node.get("description", "")[:50] or node.get("@id")
                lines.append(f"- **{name}**")
                if node.get("description") and node.get("name"):
                    lines.append(f"  - {node['description'][:100]}")
                if node.get("status"):
                    lines.append(f"  - Status: {node['status']}")

        # Relationships
        edges = context.get("_edges", [])
        if edges:
            lines.append("\n## Relationships\n")
            for edge in edges[:20]:  # Limit
                lines.append(f"- {edge['from_id']} --[{edge['relation']}]--> {edge['to_id']}")

        result = "\n".join(lines)

        if len(result) > max_tokens * 4:
            result = result[:max_tokens * 4] + "\n... (truncated)"

        return result

    def _format_narrative(self, context: Dict[str, Any], max_tokens: int) -> str:
        """Format as natural language narrative."""
        lines = []

        nodes = context.get("@graph", [])
        edges = context.get("_edges", [])

        if not nodes:
            return "No relevant context found."

        lines.append("Here is relevant context from the knowledge graph:\n")

        # Describe key entities
        for node in nodes[:10]:  # Limit
            node_type = node.get("@type", "item")
            name = node.get("name") or node.get("@id")
            desc = node.get("description", "")

            if desc:
                lines.append(f"- {name} is a {node_type}. {desc}")
            else:
                lines.append(f"- {name} is a {node_type}.")

        # Describe key relationships
        if edges:
            lines.append("\nKey relationships:")
            for edge in edges[:10]:
                # Try to get readable names
                from_node = next((n for n in nodes if n.get("@id") == edge["from_id"]), None)
                to_node = next((n for n in nodes if n.get("@id") == edge["to_id"]), None)

                from_name = from_node.get("name") if from_node else edge["from_id"]
                to_name = to_node.get("name") if to_node else edge["to_id"]
                relation = edge["relation"].replace("_", " ")

                lines.append(f"- {from_name} {relation} {to_name}")

        # Include paths if available
        paths = context.get("_paths", [])
        if paths:
            lines.append("\nReasoning paths:")
            for path in paths[:3]:
                for step in path.get("steps", []):
                    if "node" in step:
                        lines.append(f"  → {step['node']}")
                    elif "relation" in step:
                        lines.append(f"    [{step['relation']}]")

        result = "\n".join(lines)

        if len(result) > max_tokens * 4:
            result = result[:max_tokens * 4] + "\n... (truncated)"

        return result

    # -------------------------------------------------------------------------
    # Query-Aware Retrieval
    # -------------------------------------------------------------------------

    def retrieve_for_query(
        self,
        query: str,
        mode: str = "auto",
        max_nodes: int = 50
    ) -> Dict[str, Any]:
        """Retrieve context relevant to a natural language query.

        This is a simple keyword-based approach. For production,
        consider using embeddings for semantic matching.

        Args:
            query: Natural language query
            mode: "auto", "subgraph", "path", "entity", "relation"
            max_nodes: Maximum nodes to retrieve

        Returns:
            JSON-LD context for the query
        """
        query_lower = query.lower()

        # Simple keyword detection for mode selection
        if mode == "auto":
            if any(w in query_lower for w in ["path", "connect", "between", "relationship"]):
                mode = "path"
            elif any(w in query_lower for w in ["all", "every", "type of", "category"]):
                mode = "relation"
            else:
                mode = "entity"

        # Find relevant nodes by keyword matching
        all_nodes = self.backend.query_nodes(limit=500)
        relevant_ids = []

        query_words = set(query_lower.split())
        for node in all_nodes:
            score = 0
            text = f"{node.get('name', '')} {node.get('description', '')}".lower()
            for word in query_words:
                if len(word) > 2 and word in text:
                    score += 1
            if score > 0:
                relevant_ids.append((score, node["@id"]))

        relevant_ids.sort(reverse=True)
        top_ids = [nid for _, nid in relevant_ids[:10]]

        if not top_ids:
            # Fallback: return some recent nodes
            top_ids = [n["@id"] for n in all_nodes[:5]]

        # Retrieve based on mode
        if mode == "path" and len(top_ids) >= 2:
            return self.extract_paths(top_ids[:5], max_depth=3)
        elif mode == "relation":
            # Extract common relation types
            relation_types = ["hasTopic", "supportsGoal", "dependsOn"]
            return self.extract_relation_context(relation_types, limit=max_nodes)
        else:
            # Entity/subgraph mode
            if top_ids:
                return self.extract_multi_focal(top_ids[:3], depth=2)
            else:
                return {"@context": {}, "@graph": [], "_edges": [], "_meta": {"error": "No relevant nodes found"}}
