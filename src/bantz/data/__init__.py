"""
bantz.data — Data persistence layer.

Provides:
- IngestStore: TTL-cached tool result store with fingerprint dedup
- DataClass: EPHEMERAL / SESSION / PERSISTENT lifecycle classification
- GraphStore: Backend-agnostic knowledge graph interface
- AutoLinker: Automatic entity/relationship extraction from tool results
- HybridRetriever: Keyword + graph traversal retrieval
"""

from bantz.data.ingest_store import IngestStore, DataClass, IngestRecord
from bantz.data.graph_store import GraphStore, GraphNode, GraphEdge, NODE_LABELS, EDGE_RELATIONS
from bantz.data.auto_linker import AutoLinker
from bantz.data.hybrid_retriever import HybridRetriever

__all__ = [
    "IngestStore", "DataClass", "IngestRecord",
    "GraphStore", "GraphNode", "GraphEdge", "NODE_LABELS", "EDGE_RELATIONS",
    "AutoLinker", "HybridRetriever",
]
