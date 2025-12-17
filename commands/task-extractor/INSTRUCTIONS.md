# Task Extractor: Implementation Instructions

This document provides step-by-step instructions for enhancing the task-extractor with:

1. **Constrained Output** - Guarantee taxonomy compliance via Gemini's structured output
2. **GLiNER** - Zero-shot entity extraction for people, deadlines, projects
3. **SetFit** - Few-shot taxonomy classification with minimal training data

## Table of Contents

- [Overview](#overview)
- [Phase 1: Constrained Output with Gemini](#phase-1-constrained-output-with-gemini)
- [Phase 2: GLiNER Entity Extraction](#phase-2-gliner-entity-extraction)
- [Phase 3: SetFit Taxonomy Classification](#phase-3-setfit-taxonomy-classification)
- [Combined Architecture](#combined-architecture)
- [Deployment Considerations](#deployment-considerations)

---

## Overview

### Current Architecture

```
Transcript -> Gemini (free-form JSON) -> Tasks JSON -> GCS
```

**Limitations:**
- Gemini may return categories outside the taxonomy
- No structured entity extraction
- Classification accuracy depends on prompt quality

### Enhanced Architecture

```
Transcript
    │
    ├─> GLiNER ─────────────> Entities (people, deadlines, projects)
    │                              │
    ├─> Gemini (constrained) ─> Tasks (guaranteed schema)
    │                              │
    └─> SetFit ─────────────> Taxonomy categories
                                   │
                                   ▼
                           Merged Output -> GCS
```

**Benefits:**
- Taxonomy compliance guaranteed (constrained output)
- Rich entity extraction (GLiNER)
- High-accuracy classification with minimal data (SetFit)

---

## Phase 1: Constrained Output with Gemini

### Goal

Ensure Gemini only outputs valid taxonomy categories using JSON schema constraints.

### Implementation

#### 1.1 Define Pydantic Models

Create `models.py`:

```python
"""Pydantic models for structured task extraction."""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class ExtractedEntity(BaseModel):
    """An entity extracted from the transcript."""
    text: str = Field(description="The entity text as it appears")
    type: str = Field(description="Entity type: person, deadline, project, organization")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Task(BaseModel):
    """A single extracted task."""
    description: str = Field(description="Clear, actionable task description")
    assignee: Optional[str] = Field(default=None, description="Person responsible")
    deadline: Optional[str] = Field(default=None, description="Due date or timeframe")
    priority: Priority = Field(default=Priority.medium, description="Task priority")
    primary_topic: str = Field(description="Primary category from taxonomy")
    secondary_topics: List[str] = Field(default_factory=list, description="Related categories")
    context: Optional[str] = Field(default=None, description="Brief context from transcript")
    entities: List[ExtractedEntity] = Field(default_factory=list, description="Related entities")


class ExtractionResult(BaseModel):
    """Complete extraction result."""
    tasks: List[Task] = Field(default_factory=list)
    summary: str = Field(default="", description="Brief summary of action items")
    entities: List[ExtractedEntity] = Field(default_factory=list, description="All extracted entities")


def create_dynamic_task_model(taxonomy_paths: List[str]):
    """Create a Task model with taxonomy-constrained primary_topic.

    Args:
        taxonomy_paths: List of valid taxonomy paths (e.g., ["Work/Projects", "Personal/Health"])

    Returns:
        A Pydantic model class with constrained primary_topic field
    """
    # Create a Literal type from taxonomy paths
    if not taxonomy_paths:
        taxonomy_paths = ["General"]

    TopicLiteral = Literal[tuple(taxonomy_paths)]

    class ConstrainedTask(BaseModel):
        description: str = Field(description="Clear, actionable task description")
        assignee: Optional[str] = Field(default=None, description="Person responsible")
        deadline: Optional[str] = Field(default=None, description="Due date or timeframe")
        priority: Priority = Field(default=Priority.medium, description="Task priority")
        primary_topic: TopicLiteral = Field(description="Primary category from taxonomy")
        secondary_topics: List[str] = Field(default_factory=list, description="Related categories")
        context: Optional[str] = Field(default=None, description="Brief context from transcript")

    class ConstrainedExtractionResult(BaseModel):
        tasks: List[ConstrainedTask] = Field(default_factory=list)
        summary: str = Field(default="", description="Brief summary of action items")

    return ConstrainedExtractionResult
```

#### 1.2 Update Gemini Extraction with Schema

Modify `extract_tasks_with_gemini()` in `main.py`:

```python
from vertexai.generative_models import GenerativeModel, GenerationConfig
import json

def extract_tasks_with_gemini(
    transcript: dict,
    project_id: str,
    taxonomy: dict,
    location: str = "us-central1"
) -> dict:
    """Use Gemini to extract tasks with constrained taxonomy output."""

    vertexai.init(project=project_id, location=location)
    model = GenerativeModel("gemini-2.0-flash")

    # Get taxonomy paths for schema constraint
    taxonomy_paths = [t["path"] for t in taxonomy.get("topics", [])]
    if not taxonomy_paths:
        taxonomy_paths = ["General"]

    # Build JSON schema for constrained output
    response_schema = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "assignee": {"type": ["string", "null"]},
                        "deadline": {"type": ["string", "null"]},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                        "primary_topic": {"type": "string", "enum": taxonomy_paths},
                        "secondary_topics": {
                            "type": "array",
                            "items": {"type": "string", "enum": taxonomy_paths}
                        },
                        "context": {"type": ["string", "null"]}
                    },
                    "required": ["description", "primary_topic", "priority"]
                }
            },
            "summary": {"type": "string"}
        },
        "required": ["tasks", "summary"]
    }

    # Prepare transcript text
    transcript_text = transcript.get("full_text", "")
    if not transcript_text:
        segments = transcript.get("segments", [])
        if isinstance(segments, list):
            transcript_text = "\n".join(
                f"{s.get('speaker', 'Unknown')}: {s.get('text', '')}"
                for s in segments
            )

    if not transcript_text.strip():
        return {"tasks": [], "summary": "No transcript content available"}

    taxonomy_text = format_taxonomy_for_prompt(taxonomy)

    prompt = f"""Analyze this transcript and extract action items.

## Topic Taxonomy (use ONLY these categories)
{taxonomy_text}

## Instructions
1. Extract all tasks, action items, and commitments
2. Identify assignees and deadlines when mentioned
3. Classify each task using ONLY the taxonomy categories above
4. Assign priority based on urgency/importance cues

TRANSCRIPT:
{transcript_text[:15000]}"""

    generation_config = GenerationConfig(
        temperature=0.1,  # Lower temperature for more consistent output
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=response_schema  # Enforce schema
    )

    try:
        response = model.generate_content(prompt, generation_config=generation_config)
        result = json.loads(response.text)

        # Validate all primary_topics are in taxonomy (belt and suspenders)
        for task in result.get("tasks", []):
            if task.get("primary_topic") not in taxonomy_paths:
                task["primary_topic"] = "General"
            task["secondary_topics"] = [
                t for t in task.get("secondary_topics", [])
                if t in taxonomy_paths
            ]

        return result

    except Exception as e:
        log_structured("ERROR", f"Gemini extraction failed: {e}",
                      event="gemini_error", error=str(e))
        return {"tasks": [], "summary": "", "error": str(e)}
```

#### 1.3 Key Changes

| Before | After |
|--------|-------|
| Free-form JSON output | Schema-constrained JSON |
| Category validation in post-processing | Categories enforced at generation |
| `response_mime_type="application/json"` | + `response_schema=schema` |

---

## Phase 2: GLiNER Entity Extraction

### Goal

Extract structured entities (people, deadlines, projects) to augment LLM extraction.

### Implementation

#### 2.1 Install GLiNER

Add to `requirements.txt`:

```
gliner>=0.2.0
torch>=2.0.0
```

For Cloud Functions, create a separate `requirements-local.txt` for local testing with GLiNER (see Deployment Considerations).

#### 2.2 Create Entity Extractor Module

Create `entity_extractor.py`:

```python
"""GLiNER-based entity extraction for task-relevant entities."""

from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Extracted entity."""
    text: str
    label: str
    score: float
    start: int
    end: int


class EntityExtractor:
    """Extract task-relevant entities using GLiNER."""

    # Default entity types for task extraction
    DEFAULT_LABELS = [
        "person",
        "organization",
        "deadline",
        "date",
        "project",
        "document",
        "meeting",
        "monetary_amount"
    ]

    def __init__(self, model_name: str = "urchade/gliner_medium-v2.1"):
        """Initialize the entity extractor.

        Args:
            model_name: GLiNER model to use. Options:
                - "urchade/gliner_small-v2.1" (faster, less accurate)
                - "urchade/gliner_medium-v2.1" (balanced)
                - "urchade/gliner_large-v2.1" (most accurate)
        """
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        """Lazy-load the model."""
        if self._model is None:
            try:
                from gliner import GLiNER
                logger.info(f"Loading GLiNER model: {self.model_name}")
                self._model = GLiNER.from_pretrained(self.model_name)
                logger.info("GLiNER model loaded successfully")
            except ImportError:
                logger.warning("GLiNER not installed, entity extraction disabled")
                return None
            except Exception as e:
                logger.error(f"Failed to load GLiNER model: {e}")
                return None
        return self._model

    def extract(
        self,
        text: str,
        labels: Optional[List[str]] = None,
        threshold: float = 0.5
    ) -> List[Entity]:
        """Extract entities from text.

        Args:
            text: Input text to extract entities from
            labels: Entity types to extract (uses defaults if not specified)
            threshold: Minimum confidence score (0-1)

        Returns:
            List of extracted entities
        """
        if self.model is None:
            return []

        if labels is None:
            labels = self.DEFAULT_LABELS

        try:
            # GLiNER prediction
            raw_entities = self.model.predict_entities(text, labels, threshold=threshold)

            entities = [
                Entity(
                    text=e["text"],
                    label=e["label"],
                    score=e["score"],
                    start=e.get("start", 0),
                    end=e.get("end", len(e["text"]))
                )
                for e in raw_entities
            ]

            return entities

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    def extract_grouped(
        self,
        text: str,
        labels: Optional[List[str]] = None,
        threshold: float = 0.5
    ) -> Dict[str, List[Dict]]:
        """Extract entities grouped by type.

        Returns:
            Dict mapping entity type to list of entities
        """
        entities = self.extract(text, labels, threshold)

        grouped = {}
        for entity in entities:
            if entity.label not in grouped:
                grouped[entity.label] = []
            grouped[entity.label].append({
                "text": entity.text,
                "score": entity.score
            })

        return grouped

    def extract_for_tasks(self, text: str) -> Dict[str, List[str]]:
        """Extract entities specifically useful for task extraction.

        Returns simplified dict with deduplicated entity texts.
        """
        entities = self.extract(text, threshold=0.6)

        result = {
            "people": [],
            "deadlines": [],
            "projects": [],
            "organizations": []
        }

        seen = set()
        for entity in entities:
            text_lower = entity.text.lower()
            if text_lower in seen:
                continue
            seen.add(text_lower)

            if entity.label == "person":
                result["people"].append(entity.text)
            elif entity.label in ("deadline", "date"):
                result["deadlines"].append(entity.text)
            elif entity.label == "project":
                result["projects"].append(entity.text)
            elif entity.label == "organization":
                result["organizations"].append(entity.text)

        return result


# Singleton instance for reuse
_extractor: Optional[EntityExtractor] = None


def get_entity_extractor() -> EntityExtractor:
    """Get or create the singleton entity extractor."""
    global _extractor
    if _extractor is None:
        _extractor = EntityExtractor()
    return _extractor


def extract_entities(text: str) -> Dict[str, List[str]]:
    """Convenience function to extract task-relevant entities."""
    return get_entity_extractor().extract_for_tasks(text)
```

#### 2.3 Integrate with Main Extraction

Add to `main.py`:

```python
from entity_extractor import extract_entities

def extract_tasks_with_gemini(
    transcript: dict,
    project_id: str,
    taxonomy: dict,
    location: str = "us-central1"
) -> dict:
    """Extract tasks with entity augmentation."""

    # Get transcript text
    transcript_text = get_transcript_text(transcript)
    if not transcript_text:
        return {"tasks": [], "summary": "No content", "entities": {}}

    # Step 1: Extract entities with GLiNER
    entities = extract_entities(transcript_text)

    # Step 2: Include entities in Gemini prompt for context
    entity_context = ""
    if entities.get("people"):
        entity_context += f"\nPeople mentioned: {', '.join(entities['people'])}"
    if entities.get("deadlines"):
        entity_context += f"\nDeadlines mentioned: {', '.join(entities['deadlines'])}"
    if entities.get("projects"):
        entity_context += f"\nProjects mentioned: {', '.join(entities['projects'])}"

    prompt = f"""Analyze this transcript and extract action items.
{entity_context}

## Topic Taxonomy
{format_taxonomy_for_prompt(taxonomy)}

TRANSCRIPT:
{transcript_text[:15000]}"""

    # Step 3: Extract tasks with Gemini (constrained output)
    result = call_gemini_with_schema(prompt, taxonomy)

    # Step 4: Add entities to result
    result["entities"] = entities

    # Step 5: Enrich tasks with entity matches
    for task in result.get("tasks", []):
        task_text = task.get("description", "").lower()
        task["matched_entities"] = {
            "people": [p for p in entities.get("people", []) if p.lower() in task_text],
            "deadlines": [d for d in entities.get("deadlines", []) if d.lower() in task_text]
        }

    return result
```

#### 2.4 Updated Output Format

```json
{
  "tasks": [
    {
      "description": "Review Q4 budget proposal",
      "assignee": "John",
      "deadline": "Friday",
      "primary_topic": "Work/Finance",
      "secondary_topics": ["Work/Projects"],
      "priority": "high",
      "context": "Discussed during budget review",
      "matched_entities": {
        "people": ["John"],
        "deadlines": ["Friday"]
      }
    }
  ],
  "summary": "Meeting covered budget review and project updates",
  "entities": {
    "people": ["John", "Sarah", "Mike"],
    "deadlines": ["Friday", "next week", "Q4"],
    "projects": ["Alpha", "Budget Review"],
    "organizations": ["Acme Corp"]
  }
}
```

---

## Phase 3: SetFit Taxonomy Classification

### Goal

Train a lightweight classifier on your taxonomy using 8-16 examples per category for high-accuracy classification.

### Implementation

#### 3.1 Install SetFit

Add to `requirements-local.txt` (for training only):

```
setfit>=1.0.0
sentence-transformers>=2.2.0
datasets>=2.14.0
torch>=2.0.0
```

#### 3.2 Create Training Script

Create `train_classifier.py`:

```python
"""Train a SetFit classifier for taxonomy classification."""

import json
import argparse
from pathlib import Path
from datasets import Dataset
from setfit import SetFitModel, Trainer, TrainingArguments


def load_taxonomy(taxonomy_path: str) -> list[str]:
    """Load taxonomy paths from JSON file."""
    with open(taxonomy_path) as f:
        taxonomy = json.load(f)
    return [t["path"] for t in taxonomy.get("topics", [])]


def create_training_data(taxonomy_paths: list[str], examples_per_class: int = 8):
    """Create or load training examples.

    This function should be customized with your actual training examples.
    """
    # Example training data - REPLACE WITH YOUR ACTUAL EXAMPLES
    examples = {
        "Work/Projects": [
            "Complete the API integration",
            "Fix the login bug in production",
            "Deploy new feature to staging",
            "Review pull request from team",
            "Update documentation for v2.0",
            "Refactor authentication module",
            "Write unit tests for payment flow",
            "Implement dark mode feature"
        ],
        "Work/Meetings": [
            "Schedule standup for Monday",
            "Send meeting notes to team",
            "Book conference room for review",
            "Prepare slides for presentation",
            "Follow up on action items from sync",
            "Set up recurring 1:1 meetings",
            "Create agenda for quarterly review",
            "Send calendar invite for workshop"
        ],
        "Work/Finance": [
            "Review Q4 budget proposal",
            "Submit expense report",
            "Approve vendor invoice",
            "Update revenue projections",
            "Review contractor payments",
            "Prepare financial summary",
            "Track project spending",
            "Reconcile monthly expenses"
        ],
        "Work/Admin": [
            "Update team wiki",
            "Order office supplies",
            "Submit PTO request",
            "Complete compliance training",
            "Update emergency contacts",
            "Review company policies",
            "Set up new hire accounts",
            "Archive old documents"
        ],
        "Personal/Health": [
            "Book dentist appointment",
            "Schedule annual checkup",
            "Renew gym membership",
            "Pick up prescription",
            "Schedule eye exam",
            "Book massage appointment",
            "Start meal prep for week",
            "Set up therapy session"
        ],
        "Personal/Finance": [
            "Pay credit card bill",
            "Review investment portfolio",
            "Update monthly budget",
            "File tax documents",
            "Transfer to savings account",
            "Review insurance policies",
            "Cancel unused subscriptions",
            "Check retirement contributions"
        ],
        "Personal/Learning": [
            "Complete online course module",
            "Read chapter of technical book",
            "Practice new programming language",
            "Watch tutorial on machine learning",
            "Attend webinar on leadership",
            "Review flashcards for certification",
            "Write blog post about learnings",
            "Join study group session"
        ],
        "General": [
            "Call mom this weekend",
            "Buy birthday gift",
            "Plan weekend trip",
            "Return library books",
            "Water the plants",
            "Clean apartment",
            "Grocery shopping",
            "Pick up dry cleaning"
        ]
    }

    # Filter to only include taxonomy paths that have examples
    texts = []
    labels = []
    label_to_idx = {path: idx for idx, path in enumerate(taxonomy_paths)}

    for path in taxonomy_paths:
        if path in examples:
            for text in examples[path][:examples_per_class]:
                texts.append(text)
                labels.append(label_to_idx[path])

    return Dataset.from_dict({"text": texts, "label": labels}), taxonomy_paths


def train_classifier(
    taxonomy_path: str,
    output_dir: str = "./taxonomy_classifier",
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    examples_per_class: int = 8
):
    """Train a SetFit classifier on the taxonomy.

    Args:
        taxonomy_path: Path to topic_taxonomy.json
        output_dir: Where to save the trained model
        model_name: Base sentence transformer model
        examples_per_class: Number of examples per taxonomy category
    """
    # Load taxonomy
    taxonomy_paths = load_taxonomy(taxonomy_path)
    print(f"Loaded {len(taxonomy_paths)} taxonomy categories")

    # Create training data
    train_dataset, labels = create_training_data(taxonomy_paths, examples_per_class)
    print(f"Created training dataset with {len(train_dataset)} examples")

    # Initialize model
    model = SetFitModel.from_pretrained(
        model_name,
        labels=labels
    )

    # Training arguments
    args = TrainingArguments(
        batch_size=16,
        num_epochs=1,
        evaluation_strategy="no",
        save_strategy="no",
        report_to="none"
    )

    # Train
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset
    )

    print("Training classifier...")
    trainer.train()

    # Save model
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)

    # Save label mapping
    with open(output_path / "labels.json", "w") as f:
        json.dump(labels, f, indent=2)

    print(f"Model saved to {output_dir}")

    # Test predictions
    test_texts = [
        "Complete the API documentation",
        "Book flight for vacation",
        "Review quarterly earnings",
        "Schedule dentist appointment"
    ]

    predictions = model.predict(test_texts)
    print("\nTest predictions:")
    for text, pred in zip(test_texts, predictions):
        print(f"  '{text}' -> {labels[pred]}")

    return model


def main():
    parser = argparse.ArgumentParser(description="Train taxonomy classifier")
    parser.add_argument("--taxonomy", default="topic_taxonomy.json", help="Path to taxonomy JSON")
    parser.add_argument("--output", default="./taxonomy_classifier", help="Output directory")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="Base model")
    parser.add_argument("--examples", type=int, default=8, help="Examples per class")

    args = parser.parse_args()
    train_classifier(args.taxonomy, args.output, args.model, args.examples)


if __name__ == "__main__":
    main()
```

#### 3.3 Create Classifier Module

Create `taxonomy_classifier.py`:

```python
"""SetFit-based taxonomy classifier."""

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class TaxonomyClassifier:
    """Classify text into taxonomy categories using SetFit."""

    def __init__(self, model_path: str = "./taxonomy_classifier"):
        """Initialize the classifier.

        Args:
            model_path: Path to trained SetFit model directory
        """
        self.model_path = Path(model_path)
        self._model = None
        self._labels = None

    @property
    def is_available(self) -> bool:
        """Check if a trained model is available."""
        return (self.model_path / "model.safetensors").exists() or \
               (self.model_path / "pytorch_model.bin").exists()

    def _load_model(self):
        """Load the trained model and labels."""
        if self._model is not None:
            return

        try:
            from setfit import SetFitModel

            logger.info(f"Loading taxonomy classifier from {self.model_path}")
            self._model = SetFitModel.from_pretrained(str(self.model_path))

            # Load labels
            labels_path = self.model_path / "labels.json"
            if labels_path.exists():
                with open(labels_path) as f:
                    self._labels = json.load(f)
            else:
                logger.warning("Labels file not found, using indices")
                self._labels = None

            logger.info("Taxonomy classifier loaded successfully")

        except ImportError:
            logger.warning("SetFit not installed, classifier disabled")
            raise
        except Exception as e:
            logger.error(f"Failed to load classifier: {e}")
            raise

    def classify(self, text: str) -> Tuple[str, float]:
        """Classify a single text.

        Returns:
            Tuple of (category, confidence)
        """
        results = self.classify_batch([text])
        return results[0]

    def classify_batch(self, texts: List[str]) -> List[Tuple[str, float]]:
        """Classify multiple texts.

        Returns:
            List of (category, confidence) tuples
        """
        if not self.is_available:
            return [("General", 0.0) for _ in texts]

        self._load_model()

        # Get predictions
        predictions = self._model.predict(texts)

        # Get probabilities if available
        try:
            probas = self._model.predict_proba(texts)
            confidences = [float(max(p)) for p in probas]
        except:
            confidences = [1.0 for _ in texts]

        # Map to labels
        results = []
        for pred, conf in zip(predictions, confidences):
            if self._labels and isinstance(pred, int):
                label = self._labels[pred]
            else:
                label = str(pred)
            results.append((label, conf))

        return results

    def classify_with_fallback(
        self,
        text: str,
        fallback_category: str = "General"
    ) -> Tuple[str, float]:
        """Classify with fallback for errors.

        Returns:
            Tuple of (category, confidence)
        """
        try:
            return self.classify(text)
        except Exception as e:
            logger.warning(f"Classification failed, using fallback: {e}")
            return (fallback_category, 0.0)


# Singleton instance
_classifier: Optional[TaxonomyClassifier] = None


def get_classifier(model_path: str = "./taxonomy_classifier") -> TaxonomyClassifier:
    """Get or create the singleton classifier."""
    global _classifier
    if _classifier is None:
        _classifier = TaxonomyClassifier(model_path)
    return _classifier


def classify_task(text: str, fallback: str = "General") -> str:
    """Convenience function to classify a task description."""
    category, _ = get_classifier().classify_with_fallback(text, fallback)
    return category
```

#### 3.4 Integrate SetFit with Main Extraction

Update `main.py` to use SetFit for classification:

```python
from taxonomy_classifier import get_classifier, classify_task

def extract_tasks_with_gemini(
    transcript: dict,
    project_id: str,
    taxonomy: dict,
    location: str = "us-central1"
) -> dict:
    """Extract tasks with SetFit classification override."""

    # ... existing extraction code ...

    result = call_gemini_with_schema(prompt, taxonomy)

    # Override classification with SetFit if available
    classifier = get_classifier()
    if classifier.is_available:
        taxonomy_paths = [t["path"] for t in taxonomy.get("topics", [])]

        for task in result.get("tasks", []):
            description = task.get("description", "")
            setfit_category, confidence = classifier.classify_with_fallback(
                description,
                fallback_category=task.get("primary_topic", "General")
            )

            # Use SetFit if confidence is high, otherwise keep Gemini's choice
            if confidence > 0.7 and setfit_category in taxonomy_paths:
                task["primary_topic"] = setfit_category
                task["classification_source"] = "setfit"
                task["classification_confidence"] = confidence
            else:
                task["classification_source"] = "gemini"

    return result
```

#### 3.5 Training Workflow

```bash
# 1. Create/update training examples in train_classifier.py

# 2. Train the classifier
python train_classifier.py \
    --taxonomy topic_taxonomy.json \
    --output ./taxonomy_classifier \
    --examples 8

# 3. Test locally
python -c "
from taxonomy_classifier import classify_task
print(classify_task('Complete the API documentation'))
print(classify_task('Book dentist appointment'))
"

# 4. Upload model to GCS for Cloud Function use
gsutil -m cp -r ./taxonomy_classifier gs://your-bucket/models/taxonomy_classifier/
```

---

## Combined Architecture

### Full Pipeline Code

Create `enhanced_extractor.py`:

```python
"""Enhanced task extraction with GLiNER, SetFit, and constrained output."""

import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

from entity_extractor import get_entity_extractor
from taxonomy_classifier import get_classifier

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTask:
    """A fully extracted and classified task."""
    description: str
    assignee: Optional[str]
    deadline: Optional[str]
    priority: str
    primary_topic: str
    secondary_topics: List[str]
    context: Optional[str]
    entities: Dict[str, List[str]]
    classification_source: str
    classification_confidence: float


@dataclass
class ExtractionResult:
    """Complete extraction result."""
    tasks: List[ExtractedTask]
    summary: str
    all_entities: Dict[str, List[str]]
    stats: Dict[str, any]


class EnhancedTaskExtractor:
    """Enhanced task extractor using GLiNER + Gemini + SetFit."""

    def __init__(
        self,
        project_id: str,
        taxonomy: dict,
        location: str = "us-central1",
        classifier_path: Optional[str] = None
    ):
        self.project_id = project_id
        self.taxonomy = taxonomy
        self.location = location
        self.taxonomy_paths = [t["path"] for t in taxonomy.get("topics", [])]

        # Initialize components
        self.entity_extractor = get_entity_extractor()
        self.classifier = get_classifier(classifier_path) if classifier_path else None

        # Initialize Vertex AI
        vertexai.init(project=project_id, location=location)
        self.model = GenerativeModel("gemini-2.0-flash")

    def extract(self, transcript_text: str) -> ExtractionResult:
        """Run the full extraction pipeline.

        Args:
            transcript_text: Full transcript text

        Returns:
            ExtractionResult with tasks, entities, and metadata
        """
        stats = {"entity_extraction_ms": 0, "llm_extraction_ms": 0, "classification_ms": 0}

        # Step 1: Extract entities with GLiNER
        import time
        start = time.time()
        entities = self.entity_extractor.extract_for_tasks(transcript_text)
        stats["entity_extraction_ms"] = int((time.time() - start) * 1000)
        stats["entity_count"] = sum(len(v) for v in entities.values())

        # Step 2: Extract tasks with Gemini (constrained output)
        start = time.time()
        gemini_result = self._extract_with_gemini(transcript_text, entities)
        stats["llm_extraction_ms"] = int((time.time() - start) * 1000)
        stats["raw_task_count"] = len(gemini_result.get("tasks", []))

        # Step 3: Classify/verify with SetFit
        start = time.time()
        tasks = self._classify_tasks(gemini_result.get("tasks", []))
        stats["classification_ms"] = int((time.time() - start) * 1000)

        return ExtractionResult(
            tasks=tasks,
            summary=gemini_result.get("summary", ""),
            all_entities=entities,
            stats=stats
        )

    def _extract_with_gemini(
        self,
        transcript_text: str,
        entities: Dict[str, List[str]]
    ) -> dict:
        """Extract tasks using Gemini with constrained output."""

        # Build entity context
        entity_lines = []
        if entities.get("people"):
            entity_lines.append(f"People: {', '.join(entities['people'][:10])}")
        if entities.get("deadlines"):
            entity_lines.append(f"Deadlines: {', '.join(entities['deadlines'][:10])}")
        if entities.get("projects"):
            entity_lines.append(f"Projects: {', '.join(entities['projects'][:10])}")

        entity_context = "\n".join(entity_lines) if entity_lines else ""

        # Build taxonomy text
        taxonomy_text = "\n".join(
            f"- {t['path']}: {t.get('description', '')}"
            for t in self.taxonomy.get("topics", [])
        )

        # Build JSON schema
        response_schema = {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "assignee": {"type": ["string", "null"]},
                            "deadline": {"type": ["string", "null"]},
                            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "primary_topic": {"type": "string", "enum": self.taxonomy_paths},
                            "secondary_topics": {
                                "type": "array",
                                "items": {"type": "string", "enum": self.taxonomy_paths}
                            },
                            "context": {"type": ["string", "null"]}
                        },
                        "required": ["description", "primary_topic", "priority"]
                    }
                },
                "summary": {"type": "string"}
            },
            "required": ["tasks", "summary"]
        }

        prompt = f"""Extract action items from this transcript.

## Detected Entities
{entity_context}

## Taxonomy (use ONLY these categories)
{taxonomy_text}

## Transcript
{transcript_text[:15000]}"""

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            return {"tasks": [], "summary": "", "error": str(e)}

    def _classify_tasks(self, raw_tasks: List[dict]) -> List[ExtractedTask]:
        """Classify tasks using SetFit (if available) or keep Gemini classification."""

        tasks = []
        use_setfit = self.classifier and self.classifier.is_available

        for raw in raw_tasks:
            description = raw.get("description", "")

            # Determine classification
            if use_setfit:
                category, confidence = self.classifier.classify_with_fallback(
                    description,
                    fallback_category=raw.get("primary_topic", "General")
                )
                # Use SetFit if confident, otherwise keep Gemini
                if confidence > 0.7 and category in self.taxonomy_paths:
                    primary_topic = category
                    source = "setfit"
                else:
                    primary_topic = raw.get("primary_topic", "General")
                    source = "gemini"
                    confidence = 0.8  # Assumed confidence for Gemini
            else:
                primary_topic = raw.get("primary_topic", "General")
                source = "gemini"
                confidence = 0.8

            # Validate primary_topic
            if primary_topic not in self.taxonomy_paths:
                primary_topic = "General"

            task = ExtractedTask(
                description=description,
                assignee=raw.get("assignee"),
                deadline=raw.get("deadline"),
                priority=raw.get("priority", "medium"),
                primary_topic=primary_topic,
                secondary_topics=[
                    t for t in raw.get("secondary_topics", [])
                    if t in self.taxonomy_paths
                ],
                context=raw.get("context"),
                entities={},  # Will be populated below
                classification_source=source,
                classification_confidence=confidence
            )

            tasks.append(task)

        return tasks

    def to_dict(self, result: ExtractionResult) -> dict:
        """Convert result to JSON-serializable dict."""
        return {
            "tasks": [asdict(t) for t in result.tasks],
            "summary": result.summary,
            "entities": result.all_entities,
            "stats": result.stats
        }
```

---

## Deployment Considerations

### Cloud Functions Limitations

GLiNER and SetFit have dependencies (PyTorch, transformers) that may exceed Cloud Functions' deployment limits or cold start times.

**Options:**

#### Option A: Cloud Functions with Model Loading from GCS

```python
# Download model from GCS on cold start
def load_model_from_gcs(bucket_name: str, model_prefix: str, local_path: str):
    """Download model files from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    blobs = bucket.list_blobs(prefix=model_prefix)
    for blob in blobs:
        local_file = Path(local_path) / blob.name.replace(model_prefix, "")
        local_file.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_file))
```

#### Option B: Cloud Run (Recommended for ML models)

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Download models at build time (optional)
RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_small-v2.1')"

CMD ["functions-framework", "--target=process_transcript_event", "--port=8080"]
```

#### Option C: Separate Services

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Cloud Function │────▶│   Cloud Run     │────▶│   Cloud Run     │
│  (Orchestrator) │     │   (GLiNER)      │     │   (SetFit)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Requirements Files

**requirements.txt** (Cloud Functions - minimal):

```
functions-framework==3.*
google-cloud-storage==2.*
google-cloud-pubsub==2.*
google-cloud-aiplatform>=1.38.0
vertexai>=1.38.0
tzdata>=2024.1
cloudevents>=1.9.0
pydantic>=2.0.0
```

**requirements-ml.txt** (Cloud Run / Local with ML):

```
functions-framework==3.*
google-cloud-storage==2.*
google-cloud-pubsub==2.*
google-cloud-aiplatform>=1.38.0
vertexai>=1.38.0
tzdata>=2024.1
cloudevents>=1.9.0
pydantic>=2.0.0
gliner>=0.2.0
setfit>=1.0.0
sentence-transformers>=2.2.0
torch>=2.0.0
```

### Environment Variables

Add to deployment:

```bash
# GLiNER model (optional, uses default if not set)
GLINER_MODEL=urchade/gliner_small-v2.1

# SetFit classifier path in GCS
CLASSIFIER_GCS_PATH=gs://your-bucket/models/taxonomy_classifier

# Enable/disable ML features
ENABLE_GLINER=true
ENABLE_SETFIT=true
```

---

## Summary

| Feature | Implementation | Benefit |
|---------|---------------|---------|
| **Constrained Output** | Gemini `response_schema` | Guaranteed taxonomy compliance |
| **GLiNER** | Zero-shot entity extraction | Rich entity metadata |
| **SetFit** | Few-shot classification | High accuracy with minimal data |

### Recommended Rollout

1. **Phase 1**: Add constrained output to existing Gemini extraction (low effort, immediate benefit)
2. **Phase 2**: Add GLiNER for entity extraction (moderate effort, enriches output)
3. **Phase 3**: Train and deploy SetFit classifier (higher effort, best accuracy)

### Files to Create

```
task-extractor/
├── main.py                    # Update with constrained output
├── models.py                  # Pydantic models
├── entity_extractor.py        # GLiNER wrapper
├── taxonomy_classifier.py     # SetFit wrapper
├── enhanced_extractor.py      # Combined pipeline
├── train_classifier.py        # SetFit training script
├── requirements.txt           # Cloud Functions deps
├── requirements-ml.txt        # Full ML deps
├── Dockerfile                 # For Cloud Run deployment
└── taxonomy_classifier/       # Trained model (generated)
    ├── model.safetensors
    └── labels.json
```
