"""Structured trace export for observability (Issue #664).

Exports per-turn JSON traces to artifacts/logs/traces/ and provides helpers
for replay, trace viewer, golden flow comparison, and regression detection.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

TRACE_DIR = Path(__file__).resolve().parents[3] / "artifacts" / "logs" / "traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "golden" / "traces"


def _default_tier_decision() -> dict[str, str]:
    return {"router": "unknown", "finalizer": "unknown", "reason": "unknown"}


def _trace_filename(turn_id: int, timestamp: str) -> str:
    ts = timestamp.replace(":", "-").replace(".", "-")
    return f"trace_{turn_id:04d}_{ts}.json"


def build_turn_trace(
    *,
    turn_id: int,
    user_input: str,
    output: Any,
    tool_results: list[dict[str, Any]],
    state_trace: dict[str, Any],
    total_elapsed_ms: int,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a structured turn trace dict.

    Required format:
    {turn_id, timestamp, user_input, route, intent, confidence,
     tier_decision, tools: [{name, params, result, elapsed_ms}],
     finalizer_strategy, assistant_reply, total_elapsed_ms}
    """
    ts = timestamp or datetime.now().isoformat()
    tier_decision = state_trace.get("tier_decision") or _default_tier_decision()

    tools = []
    for r in tool_results or []:
        result = None
        if "raw_result" in r:
            result = r.get("raw_result")
        elif "result" in r:
            result = r.get("result")
        elif "result_summary" in r:
            result = r.get("result_summary")
        elif "error" in r:
            result = {"error": r.get("error")}

        tools.append({
            "name": str(r.get("tool") or ""),
            "params": r.get("params") or {},
            "result": result,
            "elapsed_ms": int(r.get("elapsed_ms") or 0),
            "success": bool(r.get("success", False)),
            "error": r.get("error") if r.get("error") else None,
        })

    return {
        "turn_id": int(turn_id),
        "timestamp": ts,
        "user_input": user_input,
        "route": getattr(output, "route", ""),
        "intent": getattr(output, "calendar_intent", ""),
        "confidence": float(getattr(output, "confidence", 0.0)),
        "tier_decision": tier_decision,
        "tools": tools,
        "finalizer_strategy": str(state_trace.get("finalizer_strategy") or ""),
        "assistant_reply": str(getattr(output, "assistant_reply", "") or ""),
        "total_elapsed_ms": int(total_elapsed_ms),
    }


def write_turn_trace(trace: dict[str, Any]) -> Path:
    """Write a single turn trace to TRACE_DIR and return the path."""
    turn_id = int(trace.get("turn_id") or 0)
    timestamp = str(trace.get("timestamp") or datetime.now().isoformat())
    path = TRACE_DIR / _trace_filename(turn_id, timestamp)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_trace_files(limit: Optional[int] = None) -> list[Path]:
    """List trace files sorted by modified time (newest first)."""
    files = sorted(TRACE_DIR.glob("trace_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        files = files[: int(limit)]
    return files


def load_traces(limit: Optional[int] = None) -> list[dict[str, Any]]:
    """Load recent traces from disk."""
    traces: list[dict[str, Any]] = []
    for p in list_trace_files(limit=limit):
        try:
            traces.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return traces


def export_recent_traces(n: int) -> Path:
    """Export last N traces into a single JSON file and return the path."""
    data = load_traces(limit=n)
    ts = datetime.now().isoformat().replace(":", "-").replace(".", "-")
    out = TRACE_DIR / f"trace_export_last_{n}_{ts}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def compare_traces(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Compare two traces and return a minimal diff.

    Regression criteria: route and tool names should match.
    """
    diff: dict[str, Any] = {}
    if expected.get("route") != actual.get("route"):
        diff["route"] = {"expected": expected.get("route"), "actual": actual.get("route")}

    exp_tools = [t.get("name") for t in expected.get("tools", []) if t.get("name")]
    act_tools = [t.get("name") for t in actual.get("tools", []) if t.get("name")]
    if exp_tools != act_tools:
        diff["tools"] = {"expected": exp_tools, "actual": act_tools}

    return diff


# ---------------------------------------------------------------------------
# Golden flow traces (Issue #664 Faz 2)
# ---------------------------------------------------------------------------

def load_golden_traces() -> list[dict[str, Any]]:
    """Load all golden flow traces from tests/golden/traces/."""
    if not GOLDEN_DIR.is_dir():
        return []
    traces: list[dict[str, Any]] = []
    for p in sorted(GOLDEN_DIR.glob("*.json")):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                traces.extend(raw)
            elif isinstance(raw, dict):
                traces.append(raw)
        except Exception:
            continue
    return traces


def replay_golden_traces(
    router_fn: Any = None,
) -> dict[str, Any]:
    """Replay golden traces and return pass/fail summary.

    If *router_fn* is None, uses echo mode (trace vs itself → always pass).

    Returns:
        {total, passed, failed, diffs: [{turn, diff, user_input}]}
    """
    goldens = load_golden_traces()
    diffs: list[dict[str, Any]] = []

    for idx, golden in enumerate(goldens):
        if router_fn is None:
            # Echo mode: expected == actual
            actual = {"route": golden.get("route"), "tools": golden.get("tools", [])}
        else:
            user_input = golden.get("user_input", "")
            result = router_fn(user_input)
            actual = {
                "route": result.get("route", ""),
                "tools": [{"name": t} for t in result.get("tools", [])],
            }

        diff = compare_traces(golden, actual)
        if diff:
            diffs.append({
                "turn": idx + 1,
                "diff": diff,
                "user_input": golden.get("user_input"),
            })

    total = len(goldens)
    return {
        "total": total,
        "passed": total - len(diffs),
        "failed": len(diffs),
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Metrics aggregation (Issue #664 Faz 4)
# ---------------------------------------------------------------------------

def aggregate_metrics(traces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Aggregate metrics from the last N traces.

    Returns:
        {total_turns, avg_latency_ms, p95_latency_ms, tool_success_rate,
         tier_distribution: {router: {}, finalizer: {}},
         route_distribution: {route: count},
         tool_frequency: {tool: count}}
    """
    if traces is None:
        traces = load_traces(limit=100)

    if not traces:
        return {"total_turns": 0}

    latencies = [t.get("total_elapsed_ms", 0) for t in traces]
    tool_counts = {"total": 0, "success": 0}
    route_dist: dict[str, int] = {}
    tier_router: dict[str, int] = {}
    tier_finalizer: dict[str, int] = {}
    tool_freq: dict[str, int] = {}

    for t in traces:
        route = t.get("route", "unknown")
        route_dist[route] = route_dist.get(route, 0) + 1

        td = t.get("tier_decision") or {}
        r_tier = td.get("router", "unknown")
        f_tier = td.get("finalizer", "unknown")
        tier_router[r_tier] = tier_router.get(r_tier, 0) + 1
        tier_finalizer[f_tier] = tier_finalizer.get(f_tier, 0) + 1

        for tool in t.get("tools", []):
            tool_counts["total"] += 1
            if tool.get("success"):
                tool_counts["success"] += 1
            name = tool.get("name", "unknown")
            tool_freq[name] = tool_freq.get(name, 0) + 1

    sorted_latencies = sorted(latencies)
    p95_idx = int(len(sorted_latencies) * 0.95)

    return {
        "total_turns": len(traces),
        "avg_latency_ms": int(statistics.mean(latencies)) if latencies else 0,
        "p95_latency_ms": sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)] if sorted_latencies else 0,
        "tool_success_rate": round(tool_counts["success"] / tool_counts["total"], 3) if tool_counts["total"] else 1.0,
        "tier_distribution": {"router": tier_router, "finalizer": tier_finalizer},
        "route_distribution": route_dist,
        "tool_frequency": tool_freq,
    }


def detect_anomalies(
    traces: list[dict[str, Any]] | None = None,
    *,
    latency_threshold_ms: int = 3000,
    confidence_floor: float = 0.5,
) -> list[dict[str, Any]]:
    """Detect anomalies in recent traces.

    Checks:
    - TTFT / latency spikes above threshold
    - Tool failure bursts (>50% fail rate in window)
    - Low-confidence routing
    """
    if traces is None:
        traces = load_traces(limit=100)

    anomalies: list[dict[str, Any]] = []

    # Latency spikes
    for t in traces:
        ms = t.get("total_elapsed_ms", 0)
        if ms > latency_threshold_ms:
            anomalies.append({
                "type": "latency_spike",
                "turn_id": t.get("turn_id"),
                "value": ms,
                "threshold": latency_threshold_ms,
                "user_input": (t.get("user_input") or "")[:60],
            })

    # Low confidence
    for t in traces:
        conf = t.get("confidence", 1.0)
        if conf < confidence_floor:
            anomalies.append({
                "type": "low_confidence",
                "turn_id": t.get("turn_id"),
                "value": conf,
                "threshold": confidence_floor,
                "route": t.get("route"),
                "user_input": (t.get("user_input") or "")[:60],
            })

    # Tool failure burst (any turn with all tools failing)
    for t in traces:
        tools = t.get("tools", [])
        if tools and all(not tool.get("success") for tool in tools):
            anomalies.append({
                "type": "tool_failure_burst",
                "turn_id": t.get("turn_id"),
                "tools": [tool.get("name") for tool in tools],
                "user_input": (t.get("user_input") or "")[:60],
            })

    return anomalies


# ---------------------------------------------------------------------------
# Tool/Intent DAG export (Issue #664 Faz 3)
# ---------------------------------------------------------------------------

def _parse_enum_values(schema_json: str, field: str) -> list[str]:
    """Parse enum values from the router schema JSON string.

    Example: field="route" -> ["calendar", "gmail", "smalltalk", "unknown"]
    """
    try:
        # Very lightweight parser: find '"field":"a|b|c"'
        marker = f"\"{field}\":\""
        start = schema_json.find(marker)
        if start == -1:
            return []
        start += len(marker)
        end = schema_json.find("\"", start)
        if end == -1:
            return []
        raw = schema_json[start:end]
        return [v for v in raw.split("|") if v]
    except Exception:
        return []


def build_tool_dag() -> dict[str, Any]:
    """Export a JSON DAG from tool registry + intent catalog.

    Returns:
        {nodes: [{id, label, type}], edges: [{from, to, type}]}
    """
    # Lazy imports to avoid heavy deps during normal trace export
    from bantz.agent.registry import build_default_registry
    from bantz.brain.router_output_schema import SLIM_SCHEMA_JSON

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Routes from schema + system (not in schema but in runtime)
    routes = set(_parse_enum_values(SLIM_SCHEMA_JSON, "route"))
    routes.update({"system"})
    for r in sorted(routes):
        nodes.append({"id": f"route:{r}", "label": r, "type": "route"})

    # Calendar / Gmail intents from schema
    cal_intents = _parse_enum_values(SLIM_SCHEMA_JSON, "calendar_intent")
    for i in cal_intents:
        nodes.append({"id": f"intent:calendar:{i}", "label": f"calendar.{i}", "type": "intent"})
        edges.append({"from": "route:calendar", "to": f"intent:calendar:{i}", "type": "route_intent"})

    gmail_intents = _parse_enum_values(SLIM_SCHEMA_JSON, "gmail_intent")
    for i in gmail_intents:
        nodes.append({"id": f"intent:gmail:{i}", "label": f"gmail.{i}", "type": "intent"})
        edges.append({"from": "route:gmail", "to": f"intent:gmail:{i}", "type": "route_intent"})

    # Tools from runtime registry
    reg = build_default_registry()
    for tool in reg.list_tools():
        tool_id = f"tool:{tool.name}"
        nodes.append({"id": tool_id, "label": tool.name, "type": "tool"})

        # Route mapping by prefix
        if tool.name.startswith("calendar."):
            edges.append({"from": "route:calendar", "to": tool_id, "type": "route_tool"})
        elif tool.name.startswith("gmail."):
            edges.append({"from": "route:gmail", "to": tool_id, "type": "route_tool"})
        elif tool.name.startswith("system.") or tool.name.startswith("time."):
            edges.append({"from": "route:system", "to": tool_id, "type": "route_tool"})
        else:
            edges.append({"from": "route:unknown", "to": tool_id, "type": "route_tool"})

    return {"nodes": nodes, "edges": edges}
