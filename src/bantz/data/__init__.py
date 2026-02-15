"""
bantz.data — Data persistence layer.

Provides:
- IngestStore: TTL-cached tool result store with fingerprint dedup
- DataClass: EPHEMERAL / SESSION / PERSISTENT lifecycle classification
- RunTracker: Observability — runs, tool calls, artifacts tracking
- MetricsReporter: CLI/library metrics reporter
- GraphStore: Backend-agnostic knowledge graph interface
- AutoLinker: Automatic entity/relationship extraction from tool results
- HybridRetriever: Keyword + graph traversal retrieval
"""

from bantz.data.ingest_store import IngestStore, DataClass, IngestRecord
from bantz.data.run_tracker import (
    Artifact,
    Run,
    RunTracker,
    ToolCall,
    ToolCallHandle,
)
from bantz.data.metrics_reporter import MetricsReporter
from bantz.data.graph_store import GraphStore, GraphNode, GraphEdge, NODE_LABELS, EDGE_RELATIONS
from bantz.data.auto_linker import AutoLinker
from bantz.data.hybrid_retriever import HybridRetriever

__all__ = [
    "IngestStore",
    "DataClass",
    "IngestRecord",
    "RunTracker",
    "Run",
    "ToolCall",
    "ToolCallHandle",
    "Artifact",
    "MetricsReporter",
    "GraphStore",
    "GraphNode",
    "GraphEdge",
    "NODE_LABELS",
    "EDGE_RELATIONS",
    "AutoLinker",
    "HybridRetriever",
]
