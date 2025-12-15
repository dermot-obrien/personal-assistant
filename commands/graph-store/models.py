"""Pydantic models for graph-store.

Defines the data models for nodes, edges, and API requests/responses.
Uses JSON-LD compatible structures for semantic richness.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class NodeType(str, Enum):
    """Standard node types in the knowledge graph."""
    TASK = "Task"
    TOPIC = "Topic"
    GOAL = "Goal"
    PROJECT = "Project"
    INITIATIVE = "Initiative"
    COMMITMENT = "Commitment"
    ASPIRATION = "Aspiration"
    OUTCOME = "Outcome"
    PERSON = "Person"
    TRANSCRIPT = "Transcript"


class RelationType(str, Enum):
    """Standard relationship types."""
    HAS_TOPIC = "hasTopic"
    PARENT = "parent"
    DERIVED_FROM = "derivedFrom"
    SUPPORTS_GOAL = "supportsGoal"
    HAS_TASK = "hasTask"
    DEPENDS_ON = "dependsOn"
    ASSIGNED_TO = "assignedTo"
    RELATED_TO = "relatedTo"
    BLOCKS = "blocks"
    PART_OF = "partOf"
    CONTRIBUTES_TO = "contributesTo"


class TaskStatus(str, Enum):
    """Task status values."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Priority(str, Enum):
    """Priority levels."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Direction(str, Enum):
    """Edge direction for queries."""
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class RetrievalMode(str, Enum):
    """LLM context retrieval modes."""
    SUBGRAPH = "subgraph"      # Standard graph traversal
    PATH = "path"              # PathRAG - relational paths
    ENTITY = "entity"          # LightRAG low-level
    RELATION = "relation"      # LightRAG high-level


# =============================================================================
# Base Models
# =============================================================================

class NodeBase(BaseModel):
    """Base model for all nodes."""
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class EdgeBase(BaseModel):
    """Base model for edges."""
    data: Optional[Dict[str, Any]] = Field(default_factory=dict)


# =============================================================================
# Node Models
# =============================================================================

class Node(BaseModel):
    """A node in the knowledge graph (JSON-LD compatible)."""
    type: str = Field(..., alias="@type", description="Node type")
    id: str = Field(..., alias="@id", description="Unique node identifier")
    name: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "allow"  # Allow additional properties


class TaskNode(NodeBase):
    """Task-specific node properties."""
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.MEDIUM
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    context: Optional[str] = None
    source_transcript_id: Optional[str] = None
    source_transcript_title: Optional[str] = None
    completed_at: Optional[str] = None


class TopicNode(NodeBase):
    """Topic-specific node properties."""
    path: str = Field(..., description="Hierarchical path like 'Work/Projects/Alpha'")
    parent_id: Optional[str] = None
    examples: Optional[List[str]] = Field(default_factory=list)


class GoalNode(NodeBase):
    """Goal-specific node properties."""
    timeframe: Optional[str] = None
    status: Optional[str] = "active"
    key_results: Optional[List[str]] = Field(default_factory=list)
    progress: Optional[float] = None


class ProjectNode(NodeBase):
    """Project-specific node properties."""
    status: Optional[str] = "active"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    outcomes: Optional[List[str]] = Field(default_factory=list)


# =============================================================================
# Edge Models
# =============================================================================

class Edge(BaseModel):
    """An edge/relationship in the knowledge graph."""
    id: str = Field(..., alias="@id")
    type: str = Field(default="Edge", alias="@type")
    from_id: str
    relation: str
    to_id: str
    created_at: Optional[str] = None
    data: Optional[Dict[str, Any]] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


# =============================================================================
# API Request Models
# =============================================================================

class CreateNodeRequest(BaseModel):
    """Request to create a new node."""
    type: str = Field(..., description="Node type (Task, Topic, Goal, etc.)")
    id: Optional[str] = Field(None, description="Optional custom ID. Auto-generated if not provided.")
    data: Dict[str, Any] = Field(default_factory=dict, description="Node properties")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        # Allow any type, but normalize common ones
        return v.title() if v.lower() in [t.value.lower() for t in NodeType] else v


class UpdateNodeRequest(BaseModel):
    """Request to update a node."""
    data: Dict[str, Any] = Field(..., description="Properties to update")
    merge: bool = Field(True, description="Merge with existing data (True) or replace (False)")


class CreateEdgeRequest(BaseModel):
    """Request to create an edge."""
    from_id: str = Field(..., description="Source node ID")
    relation: str = Field(..., description="Relationship type")
    to_id: str = Field(..., description="Target node ID")
    data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Edge properties")


class QueryNodesRequest(BaseModel):
    """Request to query nodes."""
    type: Optional[str] = Field(None, description="Filter by node type")
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Property filters")
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class TraverseRequest(BaseModel):
    """Request to traverse the graph."""
    start_id: str = Field(..., description="Starting node ID")
    depth: int = Field(2, ge=1, le=10, description="Maximum traversal depth")
    relations: Optional[List[str]] = Field(None, description="Filter by relation types")
    direction: Direction = Field(Direction.BOTH)


class SubgraphRequest(BaseModel):
    """Request to extract a subgraph for LLM context."""
    node_id: str = Field(..., description="Central node ID")
    depth: int = Field(2, ge=1, le=5)
    include_types: Optional[List[str]] = Field(None, description="Filter by node types")
    mode: RetrievalMode = Field(RetrievalMode.SUBGRAPH)


class PathContextRequest(BaseModel):
    """Request for PathRAG-style path extraction."""
    node_ids: List[str] = Field(..., min_length=2, description="Nodes to find paths between")
    max_depth: int = Field(3, ge=1, le=6)
    relations: Optional[List[str]] = Field(None)


class EntityContextRequest(BaseModel):
    """Request for LightRAG entity-level retrieval."""
    entity_ids: List[str] = Field(..., min_length=1)
    include_relations: bool = Field(True)
    depth: int = Field(1, ge=0, le=3)


class RelationContextRequest(BaseModel):
    """Request for LightRAG relation-level retrieval."""
    relation_types: List[str] = Field(..., min_length=1)
    limit: int = Field(50, ge=1, le=200)


class BulkCreateNodesRequest(BaseModel):
    """Request to create multiple nodes."""
    nodes: List[CreateNodeRequest]


class BulkCreateEdgesRequest(BaseModel):
    """Request to create multiple edges."""
    edges: List[CreateEdgeRequest]


class ImportRequest(BaseModel):
    """Request to import data from legacy format."""
    source: str = Field(..., description="Source type: 'consolidated_tasks', 'topic_taxonomy'")
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)


# =============================================================================
# API Response Models
# =============================================================================

class NodeResponse(BaseModel):
    """Response containing a single node."""
    node: Dict[str, Any]


class NodesResponse(BaseModel):
    """Response containing multiple nodes."""
    total: int
    count: int
    limit: int
    offset: int
    nodes: List[Dict[str, Any]]


class EdgeResponse(BaseModel):
    """Response containing a single edge."""
    edge: Dict[str, Any]


class EdgesResponse(BaseModel):
    """Response containing multiple edges."""
    count: int
    edges: List[Dict[str, Any]]


class SubgraphResponse(BaseModel):
    """Response containing a subgraph (JSON-LD format)."""
    context: Dict[str, Any] = Field(..., alias="@context")
    graph: List[Dict[str, Any]] = Field(..., alias="@graph")
    edges: List[Dict[str, Any]] = Field(..., alias="_edges")
    meta: Dict[str, Any] = Field(..., alias="_meta")

    class Config:
        populate_by_name = True


class PathContextResponse(BaseModel):
    """Response for PathRAG path retrieval."""
    context: Dict[str, Any] = Field(..., alias="@context")
    graph: List[Dict[str, Any]] = Field(..., alias="@graph")
    edges: List[Dict[str, Any]] = Field(..., alias="_edges")
    paths: List[Dict[str, Any]] = Field(..., alias="_paths")
    meta: Dict[str, Any] = Field(..., alias="_meta")

    class Config:
        populate_by_name = True


class StatsResponse(BaseModel):
    """Response containing graph statistics."""
    total_nodes: int
    total_edges: int
    nodes_by_type: Dict[str, int]
    storage_backend: str
    bucket: Optional[str] = None
    prefix: Optional[str] = None


class SchemaResponse(BaseModel):
    """Response containing the graph schema."""
    context: Dict[str, Any] = Field(..., alias="@context")
    version: str
    node_types: List[str]
    relation_types: List[str]

    class Config:
        populate_by_name = True


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    service: str = "graph-store"
    backend: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    details: Optional[Dict[str, Any]] = None
