#!/bin/bash
# Graph Store Deployment Script
# Deploys the graph-store microservice using Neo4j Aura backend

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
FUNCTION_NAME="graph-store"

# Neo4j Aura configuration
NEO4J_URI="${NEO4J_URI:-}"
NEO4J_USERNAME="${NEO4J_USERNAME:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"

# Validate required configuration
if [ -z "$PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT environment variable is required"
    echo "Set it with: export GCP_PROJECT=your-project-id"
    exit 1
fi

if [ -z "$NEO4J_URI" ] || [ -z "$NEO4J_PASSWORD" ]; then
    echo "Error: NEO4J_URI and NEO4J_PASSWORD environment variables are required"
    echo "Set them with:"
    echo "  export NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io"
    echo "  export NEO4J_PASSWORD=your-password"
    echo ""
    echo "Get a free Neo4j Aura instance at: https://neo4j.com/cloud/aura-free/"
    exit 1
fi

SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Graph Store Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Neo4j URI: $NEO4J_URI"
echo ""

# Set the project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Graph Store Cloud Function"
fi

# Build environment variables
ENV_VARS="NEO4J_URI=$NEO4J_URI,NEO4J_USERNAME=$NEO4J_USERNAME,NEO4J_PASSWORD=$NEO4J_PASSWORD,LOCAL_TIMEZONE=Pacific/Auckland"

# Deploy the HTTP API function
echo "Deploying Graph Store API..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=graph_api \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="$ENV_VARS" \
    --memory=512MB \
    --timeout=120s \
    --max-instances=10

# Get the function URL
API_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "Graph Store API URL: $API_URL"
echo "Backend: Neo4j Aura"
echo "Free Tier Limits: 200k nodes, 400k relationships"
echo ""
echo "=== API Endpoints ==="
echo ""
echo "Node Operations:"
echo "  POST   $API_URL/nodes              # Create node"
echo "  GET    $API_URL/nodes              # Query nodes"
echo "  GET    $API_URL/nodes/{id}         # Get node"
echo "  PUT    $API_URL/nodes/{id}         # Update node"
echo "  DELETE $API_URL/nodes/{id}         # Delete node"
echo ""
echo "Edge Operations:"
echo "  POST   $API_URL/edges              # Create edge"
echo "  DELETE $API_URL/edges/{id}         # Delete edge"
echo ""
echo "LLM Context Retrieval (GraphRAG/PathRAG/LightRAG):"
echo "  GET    $API_URL/subgraph/{id}      # Extract subgraph"
echo "  POST   $API_URL/context/path       # PathRAG paths"
echo "  POST   $API_URL/context/entity     # Entity context"
echo "  POST   $API_URL/context/relation   # Relation context"
echo "  POST   $API_URL/context/query      # Query-aware retrieval"
echo ""
echo "=== Examples ==="
echo ""
echo "# Create a topic node"
echo "curl -X POST \"$API_URL/nodes\" \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"type\": \"Topic\", \"data\": {\"name\": \"Work\", \"path\": \"Work\"}}'"
echo ""
echo "# Create a task node"
echo "curl -X POST \"$API_URL/nodes\" \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"type\": \"Task\", \"data\": {\"description\": \"Review PR\", \"priority\": \"high\"}}'"
echo ""
echo "# Create a relationship"
echo "curl -X POST \"$API_URL/edges\" \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"from_id\": \"task:abc123\", \"relation\": \"hasTopic\", \"to_id\": \"topic:work\"}'"
echo ""
echo "# Get subgraph for LLM context"
echo "curl \"$API_URL/subgraph/task:abc123?depth=2\""
echo ""
echo "# PathRAG: Find paths between nodes"
echo "curl -X POST \"$API_URL/context/path\" \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"node_ids\": [\"task:abc\", \"goal:xyz\"], \"max_depth\": 3}'"
echo ""
echo "# Query-aware retrieval for LLM"
echo "curl -X POST \"$API_URL/context/query\" \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"query\": \"tasks related to project alpha\", \"format\": \"markdown\"}'"
echo ""
echo "# View logs"
echo "gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
