"""Graph Store HTTP API.

Provides REST endpoints for the knowledge graph with support for
GraphRAG, PathRAG, and LightRAG retrieval patterns.

Entry points:
- graph_api: Main HTTP API handler
- health_check: Health check endpoint
"""

import json
import os
from typing import Optional

import functions_framework
from flask import Request

from backends import GraphBackend, Neo4jAuraBackend
from services import GraphService, SubgraphService


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "graph-store",
        **kwargs
    }
    print(json.dumps(log_entry))


def get_backend() -> GraphBackend:
    """Create and return the Neo4j Aura storage backend.

    Environment variables:
        NEO4J_URI: Connection URI (e.g., neo4j+s://xxxxx.databases.neo4j.io)
        NEO4J_USERNAME: Username (default: "neo4j")
        NEO4J_PASSWORD: Password
        LOCAL_TIMEZONE: Timezone for timestamps (default: "Pacific/Auckland")
    """
    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    timezone = os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland")

    if not uri or not password:
        raise ValueError("NEO4J_URI and NEO4J_PASSWORD environment variables required")

    log_structured("INFO", "Initializing Neo4j Aura backend", backend="neo4j")
    return Neo4jAuraBackend(uri=uri, username=username, password=password, timezone=timezone)


def parse_json(request: Request) -> dict:
    """Parse JSON from request body."""
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


def json_response(data: dict, status: int = 200):
    """Create a JSON response tuple."""
    return data, status, {"Content-Type": "application/json"}


@functions_framework.http
def graph_api(request: Request):
    """Main HTTP API entry point.

    Routes:
    Node Operations:
        POST   /nodes              - Create node
        GET    /nodes              - Query nodes
        GET    /nodes/{id}         - Get node
        PUT    /nodes/{id}         - Update node
        DELETE /nodes/{id}         - Delete node
        GET    /nodes/{id}/edges   - Get node's edges

    Edge Operations:
        POST   /edges              - Create edge
        DELETE /edges/{id}         - Delete edge

    Query & Traversal:
        GET    /query              - Query nodes with filters
        GET    /traverse/{id}      - Traverse from node
        GET    /search             - Text search

    LLM Context (GraphRAG/PathRAG/LightRAG):
        GET    /subgraph/{id}      - Extract subgraph
        POST   /context/path       - PathRAG path extraction
        POST   /context/entity     - LightRAG entity context
        POST   /context/relation   - LightRAG relation context
        POST   /context/hybrid     - Hybrid retrieval
        POST   /context/query      - Query-aware retrieval

    Bulk Operations:
        POST   /bulk/nodes         - Bulk create nodes
        POST   /bulk/edges         - Bulk create edges
        POST   /import             - Import from legacy format

    Meta:
        GET    /schema             - Get graph schema
        GET    /stats              - Get statistics
    """
    try:
        backend = get_backend()
        graph = GraphService(backend)
        subgraph_service = SubgraphService(backend)

        path = request.path.strip("/")
        path_parts = path.split("/") if path else []
        method = request.method

        # ---------------------------------------------------------------------
        # Node Operations
        # ---------------------------------------------------------------------

        # POST /nodes - Create node
        if method == "POST" and path_parts == ["nodes"]:
            body = parse_json(request)
            node_type = body.get("type")
            if not node_type:
                return json_response({"error": "type is required"}, 400)

            node = graph.create_node(
                node_type=node_type,
                data=body.get("data", {}),
                node_id=body.get("id")
            )
            log_structured("INFO", f"Created node: {node['@id']}", event="node_created")
            return json_response({"node": node}, 201)

        # GET /nodes - Query nodes
        if method == "GET" and path_parts == ["nodes"]:
            node_type = request.args.get("type")
            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))

            # Build filters from query params
            filters = {}
            for key in ["status", "priority", "assignee"]:
                if key in request.args:
                    filters[key] = request.args.get(key)

            nodes = graph.query_nodes(node_type, filters if filters else None, limit, offset)
            total = graph.count_nodes(node_type, filters if filters else None)

            return json_response({
                "total": total,
                "count": len(nodes),
                "limit": limit,
                "offset": offset,
                "nodes": nodes
            })

        # GET /nodes/{id} - Get node
        if method == "GET" and len(path_parts) == 2 and path_parts[0] == "nodes":
            node_id = path_parts[1]
            node = graph.get_node(node_id)
            if not node:
                return json_response({"error": "Node not found"}, 404)
            return json_response({"node": node})

        # PUT /nodes/{id} - Update node
        if method == "PUT" and len(path_parts) == 2 and path_parts[0] == "nodes":
            node_id = path_parts[1]
            body = parse_json(request)
            try:
                node = graph.update_node(
                    node_id,
                    body.get("data", {}),
                    body.get("merge", True)
                )
                log_structured("INFO", f"Updated node: {node_id}", event="node_updated")
                return json_response({"node": node})
            except KeyError:
                return json_response({"error": "Node not found"}, 404)

        # DELETE /nodes/{id} - Delete node
        if method == "DELETE" and len(path_parts) == 2 and path_parts[0] == "nodes":
            node_id = path_parts[1]
            deleted = graph.delete_node(node_id)
            if not deleted:
                return json_response({"error": "Node not found"}, 404)
            log_structured("INFO", f"Deleted node: {node_id}", event="node_deleted")
            return json_response({"success": True, "node_id": node_id})

        # GET /nodes/{id}/edges - Get node's edges
        if method == "GET" and len(path_parts) == 3 and path_parts[0] == "nodes" and path_parts[2] == "edges":
            node_id = path_parts[1]
            direction = request.args.get("direction", "both")
            relation = request.args.get("relation")
            edges = graph.get_edges(node_id, direction, relation)
            return json_response({"count": len(edges), "edges": edges})

        # ---------------------------------------------------------------------
        # Edge Operations
        # ---------------------------------------------------------------------

        # POST /edges - Create edge
        if method == "POST" and path_parts == ["edges"]:
            body = parse_json(request)
            required = ["from_id", "relation", "to_id"]
            if not all(k in body for k in required):
                return json_response({"error": f"Required fields: {required}"}, 400)

            try:
                edge = graph.create_edge(
                    body["from_id"],
                    body["relation"],
                    body["to_id"],
                    body.get("data")
                )
                log_structured("INFO", f"Created edge: {edge['@id']}", event="edge_created")
                return json_response({"edge": edge}, 201)
            except KeyError as e:
                return json_response({"error": str(e)}, 404)

        # DELETE /edges/{id} - Delete edge
        if method == "DELETE" and len(path_parts) == 2 and path_parts[0] == "edges":
            edge_id = path_parts[1]
            deleted = graph.delete_edge(edge_id)
            if not deleted:
                return json_response({"error": "Edge not found"}, 404)
            log_structured("INFO", f"Deleted edge: {edge_id}", event="edge_deleted")
            return json_response({"success": True, "edge_id": edge_id})

        # ---------------------------------------------------------------------
        # Query & Traversal
        # ---------------------------------------------------------------------

        # GET /search - Text search
        if method == "GET" and path_parts == ["search"]:
            query = request.args.get("q", "")
            node_type = request.args.get("type")
            limit = int(request.args.get("limit", 50))

            if not query:
                return json_response({"error": "q parameter required"}, 400)

            nodes = graph.search_nodes(query, node_type, limit=limit)
            return json_response({"count": len(nodes), "nodes": nodes})

        # GET /traverse/{id} - Traverse from node
        if method == "GET" and len(path_parts) == 2 and path_parts[0] == "traverse":
            node_id = path_parts[1]
            depth = int(request.args.get("depth", 2))
            direction = request.args.get("direction", "both")
            relations = request.args.get("relations")
            relations_list = relations.split(",") if relations else None

            result = graph.traverse(node_id, depth, relations_list, direction)
            return json_response(result)

        # ---------------------------------------------------------------------
        # LLM Context Retrieval (GraphRAG/PathRAG/LightRAG)
        # ---------------------------------------------------------------------

        # GET /subgraph/{id} - Extract subgraph (GraphRAG)
        if method == "GET" and len(path_parts) == 2 and path_parts[0] == "subgraph":
            node_id = path_parts[1]
            depth = int(request.args.get("depth", 2))
            include_types = request.args.get("types")
            types_list = include_types.split(",") if include_types else None
            max_nodes = int(request.args.get("max_nodes", 100))
            format_type = request.args.get("format", "json")

            context = subgraph_service.extract_subgraph(node_id, depth, types_list, max_nodes)

            if format_type in ["markdown", "narrative"]:
                formatted = subgraph_service.format_for_llm(context, format_type)
                return formatted, 200, {"Content-Type": "text/plain"}

            return json_response(context)

        # POST /context/path - PathRAG path extraction
        if method == "POST" and path_parts == ["context", "path"]:
            body = parse_json(request)
            node_ids = body.get("node_ids", [])
            if len(node_ids) < 2:
                return json_response({"error": "At least 2 node_ids required"}, 400)

            max_depth = body.get("max_depth", 3)
            max_paths = body.get("max_paths", 10)

            context = subgraph_service.extract_paths(node_ids, max_depth, max_paths=max_paths)
            return json_response(context)

        # POST /context/entity - LightRAG entity context
        if method == "POST" and path_parts == ["context", "entity"]:
            body = parse_json(request)
            entity_ids = body.get("entity_ids", [])
            if not entity_ids:
                return json_response({"error": "entity_ids required"}, 400)

            include_relations = body.get("include_relations", True)
            depth = body.get("depth", 1)

            context = subgraph_service.extract_entity_context(entity_ids, include_relations, depth)
            return json_response(context)

        # POST /context/relation - LightRAG relation context
        if method == "POST" and path_parts == ["context", "relation"]:
            body = parse_json(request)
            relation_types = body.get("relation_types", [])
            if not relation_types:
                return json_response({"error": "relation_types required"}, 400)

            limit = body.get("limit", 50)

            context = subgraph_service.extract_relation_context(relation_types, limit)
            return json_response(context)

        # POST /context/hybrid - Hybrid retrieval
        if method == "POST" and path_parts == ["context", "hybrid"]:
            body = parse_json(request)
            context = subgraph_service.extract_hybrid_context(
                focal_node_id=body.get("focal_node_id"),
                entity_ids=body.get("entity_ids"),
                relation_types=body.get("relation_types"),
                depth=body.get("depth", 2)
            )
            return json_response(context)

        # POST /context/query - Query-aware retrieval
        if method == "POST" and path_parts == ["context", "query"]:
            body = parse_json(request)
            query = body.get("query", "")
            if not query:
                return json_response({"error": "query required"}, 400)

            mode = body.get("mode", "auto")
            max_nodes = body.get("max_nodes", 50)
            format_type = body.get("format", "json")

            context = subgraph_service.retrieve_for_query(query, mode, max_nodes)

            if format_type in ["markdown", "narrative"]:
                formatted = subgraph_service.format_for_llm(context, format_type)
                return formatted, 200, {"Content-Type": "text/plain"}

            return json_response(context)

        # ---------------------------------------------------------------------
        # Bulk Operations
        # ---------------------------------------------------------------------

        # POST /bulk/nodes - Bulk create nodes
        if method == "POST" and path_parts == ["bulk", "nodes"]:
            body = parse_json(request)
            nodes_data = body.get("nodes", [])
            if not nodes_data:
                return json_response({"error": "nodes array required"}, 400)

            # Convert to backend format
            nodes_to_create = [
                {"type": n.get("type"), "id": n.get("id"), "data": n.get("data", {})}
                for n in nodes_data
            ]

            created = graph.bulk_create_nodes(nodes_to_create)
            log_structured("INFO", f"Bulk created {len(created)} nodes", event="bulk_nodes_created")
            return json_response({"created_count": len(created), "nodes": created}, 201)

        # POST /bulk/edges - Bulk create edges
        if method == "POST" and path_parts == ["bulk", "edges"]:
            body = parse_json(request)
            edges_data = body.get("edges", [])
            if not edges_data:
                return json_response({"error": "edges array required"}, 400)

            created = graph.bulk_create_edges(edges_data)
            log_structured("INFO", f"Bulk created {len(created)} edges", event="bulk_edges_created")
            return json_response({"created_count": len(created), "edges": created}, 201)

        # POST /import - Import from legacy format
        if method == "POST" and path_parts == ["import"]:
            body = parse_json(request)
            source = body.get("source")
            if source not in ["consolidated_tasks", "topic_taxonomy"]:
                return json_response({"error": "source must be 'consolidated_tasks' or 'topic_taxonomy'"}, 400)

            result = import_legacy_data(backend, source, body.get("options", {}))
            return json_response(result)

        # ---------------------------------------------------------------------
        # Meta
        # ---------------------------------------------------------------------

        # GET /schema - Get graph schema
        if method == "GET" and path_parts == ["schema"]:
            schema = graph.get_schema()
            return json_response(schema)

        # GET /stats - Get statistics
        if method == "GET" and path_parts == ["stats"]:
            stats = graph.get_stats()
            return json_response(stats)

        # GET /topics/tree - Get topic hierarchy
        if method == "GET" and path_parts == ["topics", "tree"]:
            root_path = request.args.get("root")
            tree = graph.get_topic_hierarchy(root_path)
            return json_response({"topics": tree})

        # Not found
        return json_response({
            "error": "Not found",
            "path": request.path,
            "method": method
        }, 404)

    except Exception as e:
        log_structured("ERROR", f"API error: {e}", error=str(e), path=request.path)
        return json_response({"error": str(e)}, 500)


def import_legacy_data(backend: GraphBackend, source: str, options: dict) -> dict:
    """Import data from legacy formats.

    Args:
        backend: The storage backend
        source: "consolidated_tasks" or "topic_taxonomy"
        options: Import options

    Returns:
        Import results
    """
    from google.cloud import storage as gcs

    bucket_name = os.environ.get("GCS_BUCKET")
    storage_client = gcs.Client()
    bucket = storage_client.bucket(bucket_name)
    graph = GraphService(backend)

    if source == "topic_taxonomy":
        blob = bucket.blob("topic_taxonomy.json")
        if not blob.exists():
            return {"error": "topic_taxonomy.json not found"}

        taxonomy = json.loads(blob.download_as_text())
        created_nodes = []

        for topic in taxonomy.get("topics", []):
            path = topic.get("path", "")
            topic_id = f"topic:{path.lower().replace('/', '_')}"

            # Find parent
            parent_id = None
            if "/" in path:
                parent_path = path.rsplit("/", 1)[0]
                parent_id = f"topic:{parent_path.lower().replace('/', '_')}"

            node = graph.create_node(
                node_type="Topic",
                node_id=topic_id,
                data={
                    "name": path.split("/")[-1],
                    "path": path,
                    "description": topic.get("description", ""),
                    "examples": topic.get("examples", [])
                }
            )
            created_nodes.append(node)

            # Create parent edge if applicable
            if parent_id and graph.node_exists(parent_id):
                graph.create_edge(topic_id, "parent", parent_id)

        return {
            "source": source,
            "imported_count": len(created_nodes),
            "nodes": [n["@id"] for n in created_nodes]
        }

    elif source == "consolidated_tasks":
        blob = bucket.blob("tasks/consolidated_tasks.json")
        if not blob.exists():
            return {"error": "consolidated_tasks.json not found"}

        consolidated = json.loads(blob.download_as_text())
        created_nodes = []
        created_edges = []

        for task in consolidated.get("tasks", []):
            task_id = f"task:{task.get('source_transcript_id', '')[:8]}_{len(created_nodes)}"

            node = graph.create_node(
                node_type="Task",
                node_id=task_id,
                data={
                    "description": task.get("description", ""),
                    "status": "pending",
                    "priority": task.get("priority", "medium"),
                    "assignee": task.get("assignee"),
                    "deadline": task.get("deadline"),
                    "context": task.get("context"),
                    "source_transcript_id": task.get("source_transcript_id"),
                    "source_transcript_title": task.get("source_transcript_title"),
                    "primary_topic": task.get("primary_topic", "General"),
                    "secondary_topics": task.get("secondary_topics", [])
                }
            )
            created_nodes.append(node)

            # Create topic edge if topic exists
            topic_path = task.get("primary_topic", "")
            if topic_path:
                topic_id = f"topic:{topic_path.lower().replace('/', '_')}"
                if graph.node_exists(topic_id):
                    edge = graph.create_edge(task_id, "hasTopic", topic_id)
                    created_edges.append(edge)

        return {
            "source": source,
            "imported_nodes": len(created_nodes),
            "imported_edges": len(created_edges)
        }

    return {"error": f"Unknown source: {source}"}


@functions_framework.http
def health_check(request: Request):
    """Health check endpoint."""
    try:
        backend = get_backend()
        stats = backend.get_stats()
        return json_response({
            "status": "healthy",
            "service": "graph-store",
            "backend": stats.get("storage_backend"),
            "node_count": stats.get("total_nodes", 0)
        })
    except Exception as e:
        return json_response({
            "status": "unhealthy",
            "service": "graph-store",
            "error": str(e)
        }, 500)
