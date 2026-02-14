"""Hierarchical task decomposition — DAG-based multi-step planner (Issue #1279).

Provides ``Subtask`` / ``SubtaskPlan`` data structures and utilities
for decomposing complex user requests into ordered sub-goals.

Design constraints
------------------
- **Max 5 subtasks** per plan (prevents infinite decomposition).
- ``depends_on`` encodes a DAG; topological sort determines execution order.
- ``dynamic: true`` means params are resolved from previous subtask results.
- Backwards compatible: single-tool requests bypass decomposition entirely.
- Integrates with ReAct (#1273) — each subtask can trigger observation/replan.

Example subtask list (from LLM)::

    [
        {"id": 1, "goal": "List this week's events",
         "tool": "calendar.list_events", "params": {"date_range": "this_week"},
         "depends_on": []},
        {"id": 2, "goal": "Create study blocks in free slots",
         "tool": "calendar.create_event",
         "params": {"dynamic": true, "from_result_of": 1},
         "depends_on": [1]},
    ]
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Hard ceiling — LLM may try to over-decompose
MAX_SUBTASKS = 5


@dataclass
class Subtask:
    """A single step within a multi-step task decomposition."""

    id: int
    goal: str
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)

    # Execution state (mutated by executor)
    status: str = "pending"  # pending | running | done | failed | cancelled
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def is_dynamic(self) -> bool:
        """True when params should be resolved from a previous result."""
        return bool(self.params.get("dynamic"))

    @property
    def from_result_of(self) -> Optional[int]:
        """ID of the subtask whose result feeds this one's params."""
        val = self.params.get("from_result_of")
        return int(val) if val is not None else None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "goal": self.goal,
            "tool": self.tool,
            "params": self.params,
            "depends_on": self.depends_on,
            "status": self.status,
        }
        if self.result is not None:
            d["result_summary"] = str(self.result.get("result_summary", ""))[:200]
        if self.error:
            d["error"] = self.error[:200]
        return d


@dataclass
class SubtaskPlan:
    """An ordered plan of subtasks with DAG-based execution order.

    Use :func:`build_plan` to construct from raw LLM output,
    then iterate execution with :meth:`next_subtask` / :meth:`complete_subtask`.
    """

    subtasks: list[Subtask] = field(default_factory=list)

    # Computed execution order (topological sort)
    _execution_order: list[int] = field(default_factory=list, repr=False)
    _exec_index: int = field(default=0, repr=False)

    @property
    def is_empty(self) -> bool:
        return len(self.subtasks) == 0

    @property
    def is_complete(self) -> bool:
        return all(s.status in ("done", "failed", "cancelled") for s in self.subtasks)

    @property
    def current_subtask(self) -> Optional[Subtask]:
        """Return the currently running subtask, if any."""
        for s in self.subtasks:
            if s.status == "running":
                return s
        return None

    @property
    def pending_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == "pending")

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == "done")

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == "failed")

    def get_subtask(self, subtask_id: int) -> Optional[Subtask]:
        for s in self.subtasks:
            if s.id == subtask_id:
                return s
        return None

    def next_subtask(self) -> Optional[Subtask]:
        """Return the next subtask to execute (respecting DAG order).

        Returns ``None`` when all subtasks are done/failed/cancelled.
        """
        while self._exec_index < len(self._execution_order):
            sid = self._execution_order[self._exec_index]
            sub = self.get_subtask(sid)
            if sub is None:
                self._exec_index += 1
                continue
            if sub.status == "pending":
                # Check dependencies are satisfied
                if self._deps_satisfied(sub):
                    return sub
                else:
                    # Dep failed → cancel this subtask
                    sub.status = "cancelled"
                    sub.error = "dependency_failed"
                    self._exec_index += 1
                    continue
            self._exec_index += 1
        return None

    def complete_subtask(
        self,
        subtask_id: int,
        *,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a subtask as done or failed."""
        sub = self.get_subtask(subtask_id)
        if sub is None:
            return
        if error:
            sub.status = "failed"
            sub.error = error
            # Cancel all downstream dependents
            self._cancel_dependents(subtask_id)
        else:
            sub.status = "done"
            sub.result = result or {}
        self._exec_index += 1

    def cancel_remaining(self) -> None:
        """Cancel all pending subtasks (e.g. on fatal error)."""
        for s in self.subtasks:
            if s.status == "pending":
                s.status = "cancelled"
                s.error = "plan_cancelled"

    def get_results(self) -> dict[int, dict[str, Any]]:
        """Return mapping of subtask_id → result for completed subtasks."""
        return {
            s.id: s.result
            for s in self.subtasks
            if s.status == "done" and s.result is not None
        }

    def to_progress_block(self) -> str:
        """Human-readable progress summary for LLM context."""
        if not self.subtasks:
            return ""
        lines = ["SUBTASK_PROGRESS:"]
        for s in self.subtasks:
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "done": "✅",
                "failed": "❌",
                "cancelled": "⛔",
            }.get(s.status, "?")
            result_hint = ""
            if s.result:
                summary = str(s.result.get("result_summary", ""))[:80]
                if summary:
                    result_hint = f" → {summary}"
            lines.append(f"  {status_icon} [{s.id}] {s.goal} ({s.tool}){result_hint}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _deps_satisfied(self, sub: Subtask) -> bool:
        for dep_id in sub.depends_on:
            dep = self.get_subtask(dep_id)
            if dep is None or dep.status != "done":
                return False
        return True

    def _cancel_dependents(self, failed_id: int) -> None:
        """Recursively cancel subtasks that depend on a failed one."""
        for s in self.subtasks:
            if failed_id in s.depends_on and s.status == "pending":
                s.status = "cancelled"
                s.error = f"depends_on #{failed_id} failed"
                self._cancel_dependents(s.id)


# ══════════════════════════════════════════════════════════════════════
#  Builder functions
# ══════════════════════════════════════════════════════════════════════


def build_plan(
    raw_subtasks: list[dict[str, Any]],
    *,
    valid_tools: frozenset[str] | set[str] | None = None,
) -> SubtaskPlan:
    """Build a ``SubtaskPlan`` from raw LLM output.

    - Validates tool names against *valid_tools* if provided.
    - Enforces ``MAX_SUBTASKS`` ceiling.
    - Computes topological sort for DAG execution.
    - Returns empty plan for empty/invalid input.
    """
    if not raw_subtasks or not isinstance(raw_subtasks, list):
        return SubtaskPlan()

    # Enforce max subtasks
    if len(raw_subtasks) > MAX_SUBTASKS:
        logger.warning(
            "[task_planner] Truncating %d subtasks to %d",
            len(raw_subtasks), MAX_SUBTASKS,
        )
        raw_subtasks = raw_subtasks[:MAX_SUBTASKS]

    subtasks: list[Subtask] = []
    seen_ids: set[int] = set()

    for raw in raw_subtasks:
        if not isinstance(raw, dict):
            continue

        sid = raw.get("id")
        if sid is None or not isinstance(sid, (int, float)):
            continue
        sid = int(sid)
        if sid in seen_ids:
            continue  # Skip duplicate IDs
        seen_ids.add(sid)

        tool = str(raw.get("tool") or "").strip()
        if valid_tools and tool not in valid_tools:
            logger.info("[task_planner] Invalid tool '%s' in subtask %d, skipping", tool, sid)
            continue

        goal = str(raw.get("goal") or "").strip()[:200]
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        deps = raw.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        deps = [int(d) for d in deps if isinstance(d, (int, float))]
        # Remove deps that reference non-existent subtasks
        deps = [d for d in deps if d in seen_ids]

        subtasks.append(Subtask(
            id=sid,
            goal=goal,
            tool=tool,
            params=params,
            depends_on=deps,
        ))

    if not subtasks:
        return SubtaskPlan()

    # Compute execution order (topological sort)
    execution_order = _topological_sort(subtasks)

    plan = SubtaskPlan(subtasks=subtasks)
    plan._execution_order = execution_order
    return plan


def _topological_sort(subtasks: list[Subtask]) -> list[int]:
    """Kahn's algorithm for topological sort of the subtask DAG.

    Returns list of subtask IDs in valid execution order.
    If a cycle is detected, returns subtasks in ID order (best-effort).
    """
    id_set = {s.id for s in subtasks}

    # In-degree computation
    in_degree: dict[int, int] = {s.id: 0 for s in subtasks}
    adjacency: dict[int, list[int]] = {s.id: [] for s in subtasks}

    for s in subtasks:
        for dep_id in s.depends_on:
            if dep_id in id_set:
                in_degree[s.id] += 1
                adjacency[dep_id].append(s.id)

    # BFS
    queue: deque[int] = deque()
    for sid, deg in in_degree.items():
        if deg == 0:
            queue.append(sid)

    result: list[int] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(subtasks):
        # Cycle detected — fallback to ID order
        logger.warning("[task_planner] Cycle detected in subtask DAG, using ID order")
        result = sorted(s.id for s in subtasks)

    return result


def resolve_params(
    subtask: Subtask,
    completed_results: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve dynamic params from completed subtask results.

    If ``subtask.is_dynamic`` and ``from_result_of`` points to a completed
    subtask, the result data is merged into the params.  Otherwise,
    returns the subtask's static params (without ``dynamic``/``from_result_of``
    control keys).
    """
    params = dict(subtask.params)

    # Remove control keys
    params.pop("dynamic", None)
    from_id = params.pop("from_result_of", None)

    if subtask.is_dynamic and subtask.from_result_of is not None:
        source_result = completed_results.get(subtask.from_result_of)
        if source_result:
            # Inject source result data into params
            params["_source_result"] = source_result
            # If source has specific useful fields, forward them
            for key in ("result_summary", "events", "messages", "data"):
                if key in source_result:
                    params.setdefault(f"_from_{key}", source_result[key])

    return params


def is_decomposition_candidate(tool_plan: list[str], status: str) -> bool:
    """Check if the LLM output looks like a decomposition candidate.

    Simple heuristic: >1 tool in plan AND status is needs_more_info.
    Single-tool plans bypass decomposition entirely (backwards compat).
    """
    return len(tool_plan) > 1 and status == "needs_more_info"
