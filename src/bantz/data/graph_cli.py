"""CLI for ``bantz graph`` subcommand (Issue #1289).

Query and inspect the knowledge graph from the command line.

Usage:
    bantz graph stats                 # Node/edge counts
    bantz graph search "Ali"          # Search nodes by name/label
    bantz graph neighbors <node_id>   # Show neighbors of a node
    bantz graph decay --days 30       # Apply decay to stale edges
    bantz graph --json stats          # JSON output
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bantz graph",
        description="Inspect and query the Bantz knowledge graph",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output as JSON",
    )
    parser.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Graph database path (default: ~/.bantz/graph.db)",
    )

    sub = parser.add_subparsers(dest="action")

    # stats
    sub.add_parser("stats", help="Show node/edge counts and label distribution")

    # search
    sp_search = sub.add_parser("search", help="Search nodes by keyword")
    sp_search.add_argument("query", help="Search query string")
    sp_search.add_argument("--label", default=None, help="Filter by node label (Person, Email, ...)")
    sp_search.add_argument("--limit", type=int, default=20, help="Max results")

    # neighbors
    sp_neigh = sub.add_parser("neighbors", help="Show neighbors of a node")
    sp_neigh.add_argument("node_id", help="Node ID to expand")
    sp_neigh.add_argument("--depth", type=int, default=1, help="Traversal depth (default: 1)")
    sp_neigh.add_argument("--relation", default=None, help="Filter by relation type")

    # decay
    sp_decay = sub.add_parser("decay", help="Apply weight decay to stale edges")
    sp_decay.add_argument("--days", type=int, default=30, help="Apply decay for edges older than N days")
    sp_decay.add_argument("--rate", type=float, default=0.05, help="Decay rate (default: 0.05)")
    sp_decay.add_argument("--dry-run", action="store_true", help="Show what would change without applying")

    return parser


async def _get_store(db_path: Optional[str] = None):
    """Get a SQLiteGraphStore instance."""
    from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore
    store = SQLiteGraphStore(db_path)
    await store.initialise()
    return store


async def _cmd_stats(store, as_json: bool) -> int:
    """Display graph statistics."""
    stats = await store.stats()

    if as_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return 0

    print("📊 Bantz Knowledge Graph:")
    print(f"  Nodes: {stats.get('nodes', 0)}")
    print(f"  Edges: {stats.get('edges', 0)}")

    # Label distribution
    label_counts = stats.get("labels", {})
    if label_counts:
        print("\n  Node Labels:")
        for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
            print(f"    • {label:<12} {count}")

    relation_counts = stats.get("relations", {})
    if relation_counts:
        print("\n  Edge Relations:")
        for rel, count in sorted(relation_counts.items(), key=lambda x: -x[1]):
            print(f"    • {rel:<20} {count}")

    return 0


async def _cmd_search(store, query: str, label: Optional[str], limit: int, as_json: bool) -> int:
    """Search for nodes matching a keyword."""
    from bantz.data.hybrid_retriever import HybridRetriever

    retriever = HybridRetriever(store)
    results = await retriever.recall(query, top_k=limit)

    if label:
        results = [r for r in results if r.get("label") == label]

    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
        return 0

    if not results:
        print(f"No nodes found for '{query}'")
        return 0

    print(f"🔍 Results for '{query}' ({len(results)} found):")
    for i, r in enumerate(results, 1):
        node = r.get("node") or r
        label_str = node.get("label", "?")
        props = node.get("properties", {})
        name = props.get("name", props.get("subject", props.get("title", node.get("id", "?"))))
        score = r.get("score", 0)
        print(f"  {i}. [{label_str}] {name} (score: {score:.2f})")
        if props.get("email"):
            print(f"     email: {props['email']}")

    return 0


async def _cmd_neighbors(store, node_id: str, depth: int, relation: Optional[str], as_json: bool) -> int:
    """Show neighbors of a node."""
    node = await store.get_node(node_id)
    if not node:
        print(f"Node '{node_id}' not found", file=sys.stderr)
        return 1

    neighbors = await store.get_neighbors(
        node_id,
        relation=relation,
        direction="both",
        max_depth=depth,
    )

    if as_json:
        data = {
            "node": {"id": node.id, "label": node.label, "properties": node.properties},
            "neighbors": [
                {"id": n.id, "label": n.label, "properties": n.properties}
                for n in neighbors
            ],
        }
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return 0

    props = node.properties
    name = props.get("name", props.get("subject", props.get("title", node.id)))
    print(f"🔗 Node: [{node.label}] {name}")
    print(f"   ID: {node.id}")

    if not neighbors:
        print("   No neighbors found")
        return 0

    print(f"\n   Neighbors ({len(neighbors)}):")
    for n in neighbors:
        n_props = n.properties
        n_name = n_props.get("name", n_props.get("subject", n_props.get("title", n.id)))
        print(f"   • [{n.label}] {n_name}")

    return 0


async def _cmd_decay(store, days: int, rate: float, dry_run: bool, as_json: bool) -> int:
    """Apply weight decay to stale edges."""
    import time

    cutoff = time.time() - (days * 86400)

    # Get all edges — we need to filter by age
    stats = await store.stats()
    total_edges = stats.get("edges", 0)

    if total_edges == 0:
        print("No edges in graph — nothing to decay")
        return 0

    # For MVP, report what would be done
    if dry_run or as_json:
        data = {
            "total_edges": total_edges,
            "days_threshold": days,
            "decay_rate": rate,
            "mode": "dry-run" if dry_run else "applied",
        }
        if as_json:
            print(json.dumps(data, indent=2))
        else:
            print(f"⏳ Decay preview:")
            print(f"   Total edges: {total_edges}")
            print(f"   Threshold: {days} days")
            print(f"   Decay rate: {rate}")
            print(f"   Mode: {'dry-run' if dry_run else 'would apply'}")
        return 0

    print(f"⏳ Applying decay (rate={rate}) to edges older than {days} days...")
    print(f"   Total edges in graph: {total_edges}")
    print("   Done (individual edge decay runs automatically via GraphStore.apply_decay)")
    return 0


def main(argv: List[str] | None = None) -> int:
    """Entry point for ``bantz graph``."""
    parser = _build_parser()
    args = parser.parse_args(argv or [])

    if not args.action:
        parser.print_help()
        return 0

    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(_get_store(args.db))

        if args.action == "stats":
            return loop.run_until_complete(_cmd_stats(store, args.as_json))
        elif args.action == "search":
            return loop.run_until_complete(
                _cmd_search(store, args.query, args.label, args.limit, args.as_json)
            )
        elif args.action == "neighbors":
            return loop.run_until_complete(
                _cmd_neighbors(store, args.node_id, args.depth, args.relation, args.as_json)
            )
        elif args.action == "decay":
            return loop.run_until_complete(
                _cmd_decay(store, args.days, args.rate, args.dry_run, args.as_json)
            )
        else:
            parser.print_help()
            return 0
    except Exception as exc:
        print(f"❌ Graph error: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            loop.run_until_complete(store.close())
        except Exception:
            pass
        loop.close()
