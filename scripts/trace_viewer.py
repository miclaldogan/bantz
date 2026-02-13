#!/usr/bin/env python3
"""Trace Viewer — simple web UI for Bantz orchestrator traces (Issue #664).

Serves a timeline view of recent traces on localhost:5050.

Usage:
    python scripts/trace_viewer.py                # default: localhost:5050
    python scripts/trace_viewer.py --port 8080    # custom port
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bantz.brain.trace_exporter import (
  aggregate_metrics,
  build_tool_dag,
  detect_anomalies,
  load_traces,
)

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>Bantz Trace Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 10px; }
  .summary { display: flex; gap: 20px; margin: 16px 0; flex-wrap: wrap; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 16px 20px; min-width: 160px; }
  .card .label { font-size: 12px; color: #8b949e; text-transform: uppercase; }
  .card .value { font-size: 28px; font-weight: 600; color: #58a6ff; margin-top: 4px; }
  .card .value.warn { color: #d29922; }
  .card .value.bad  { color: #f85149; }
  .timeline { margin-top: 24px; }
  #dag { height: 360px; border: 1px solid #30363d; border-radius: 8px; background: #0d1117; }
  .turn { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
          padding: 16px; margin-bottom: 12px; }
  .turn-header { display: flex; justify-content: space-between; align-items: center; }
  .turn-route { font-size: 14px; padding: 2px 10px; border-radius: 12px;
                font-weight: 600; }
  .route-calendar { background: #1f3d2e; color: #3fb950; }
  .route-gmail    { background: #2d1f3d; color: #a371f7; }
  .route-system   { background: #1f2d3d; color: #58a6ff; }
  .route-smalltalk{ background: #3d3d1f; color: #d29922; }
  .route-unknown  { background: #3d1f1f; color: #f85149; }
  .turn-input { margin: 8px 0; font-style: italic; color: #8b949e; }
  .turn-reply { margin: 8px 0; color: #c9d1d9; }
  .turn-tools { margin: 6px 0; }
  .tool-badge { display: inline-block; font-size: 12px; padding: 2px 8px;
                border-radius: 4px; margin-right: 6px; margin-bottom: 4px; }
  .tool-ok   { background: #1f3d2e; color: #3fb950; }
  .tool-fail { background: #3d1f1f; color: #f85149; }
  .latency { font-size: 13px; color: #8b949e; }
  .anomalies { margin: 16px 0; }
  .anomaly { background: #3d1f1f; border: 1px solid #f85149; border-radius: 8px;
             padding: 12px; margin-bottom: 8px; color: #f85149; }
  .tier-badge { font-size: 11px; padding: 1px 6px; border-radius: 4px;
                background: #1f2d3d; color: #58a6ff; margin-left: 6px; }
  footer { margin-top: 30px; color: #484f58; font-size: 12px; text-align: center; }
</style>
</head>
<body>
<h1>🔍 Bantz Trace Viewer</h1>
<div style="margin:12px 0;">
  <h2 style="color:#c9d1d9;margin:8px 0">Tool/Intent DAG</h2>
  <div id="dag"></div>
</div>
<div class="summary" id="summary"></div>
<div class="anomalies" id="anomalies"></div>
<h2 style="color:#c9d1d9;margin:16px 0 8px">Timeline</h2>
<div class="timeline" id="timeline"></div>
<footer>Bantz Observability — Issue #664</footer>

<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<script>
async function load() {
  const [tracesRes, metricsRes, anomRes] = await Promise.all([
    fetch('/api/traces?limit=50'),
    fetch('/api/metrics'),
    fetch('/api/anomalies'),
  ]);
  const traces  = await tracesRes.json();
  const metrics = await metricsRes.json();
  const anomalies = await anomRes.json();

  // DAG
  try {
    const dagRes = await fetch('/api/dag');
    const dag = await dagRes.json();
    const container = document.getElementById('dag');
    const nodes = new vis.DataSet(dag.nodes.map(n => ({
      id: n.id,
      label: n.label,
      color: n.type === 'route' ? '#58a6ff' : n.type === 'intent' ? '#3fb950' : '#a371f7',
      shape: n.type === 'tool' ? 'box' : 'ellipse',
    })));
    const edges = new vis.DataSet(dag.edges.map(e => ({ from: e.from, to: e.to })));
    new vis.Network(container, { nodes, edges }, {
      layout: { improvedLayout: true },
      interaction: { hover: true },
      physics: { stabilization: true }
    });
  } catch (e) {
    // Best-effort: DAG is optional
  }

  // Summary cards
  const sum = document.getElementById('summary');
  const cards = [
    {label:'Turns', value: metrics.total_turns || 0},
    {label:'Avg Latency', value: (metrics.avg_latency_ms||0)+'ms',
     cls: (metrics.avg_latency_ms||0) > 2000 ? 'bad' : (metrics.avg_latency_ms||0) > 1000 ? 'warn' : ''},
    {label:'P95 Latency', value: (metrics.p95_latency_ms||0)+'ms',
     cls: (metrics.p95_latency_ms||0) > 3000 ? 'bad' : (metrics.p95_latency_ms||0) > 1500 ? 'warn' : ''},
    {label:'Tool Success', value: ((metrics.tool_success_rate||1)*100).toFixed(1)+'%',
     cls: (metrics.tool_success_rate||1) < 0.9 ? 'bad' : (metrics.tool_success_rate||1) < 0.95 ? 'warn' : ''},
    {label:'Anomalies', value: anomalies.length,
     cls: anomalies.length > 5 ? 'bad' : anomalies.length > 0 ? 'warn' : ''},
  ];
  sum.innerHTML = cards.map(c =>
    `<div class="card"><div class="label">${c.label}</div><div class="value ${c.cls||''}">${c.value}</div></div>`
  ).join('');

  // Anomalies
  const aDiv = document.getElementById('anomalies');
  if (anomalies.length) {
    aDiv.innerHTML = '<h3 style="color:#f85149;margin-bottom:8px">⚠️ Anomalies</h3>' +
      anomalies.slice(0,10).map(a =>
        `<div class="anomaly">Turn #${a.turn_id||'?'}: ${a.type} — ${a.user_input||''}</div>`
      ).join('');
  }

  // Timeline
  const tl = document.getElementById('timeline');
  tl.innerHTML = traces.map(t => {
    const route = t.route||'unknown';
    const routeCls = 'route-'+ ({'calendar':'calendar','gmail':'gmail','system':'system','smalltalk':'smalltalk'}[route]||'unknown');
    const tools = (t.tools||[]).map(tool =>
      `<span class="tool-badge ${tool.success?'tool-ok':'tool-fail'}">${tool.name} (${tool.elapsed_ms}ms)</span>`
    ).join('');
    const tier = t.tier_decision||{};
    return `<div class="turn">
      <div class="turn-header">
        <span><strong>#${t.turn_id||'?'}</strong> <span class="turn-route ${routeCls}">${route}</span>
          <span class="tier-badge">R:${tier.router||'?'}</span>
          <span class="tier-badge">F:${tier.finalizer||'?'}</span></span>
        <span class="latency">${t.total_elapsed_ms||0}ms</span>
      </div>
      <div class="turn-input">💬 ${t.user_input||''}</div>
      ${tools ? '<div class="turn-tools">'+tools+'</div>' : ''}
      <div class="turn-reply">🤖 ${(t.assistant_reply||'').substring(0,200)}</div>
    </div>`;
  }).join('');
}
load();
</script>
</body>
</html>"""


class TraceViewerHandler(SimpleHTTPRequestHandler):
    """HTTP handler for trace viewer API + static HTML."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._respond_html(_HTML_TEMPLATE)
        elif path == "/api/traces":
            limit = int(qs.get("limit", ["50"])[0])
            data = load_traces(limit=limit)
            self._respond_json(data)
        elif path == "/api/metrics":
            data = aggregate_metrics()
            self._respond_json(data)
        elif path == "/api/anomalies":
            data = detect_anomalies()
            self._respond_json(data)
        elif path == "/api/dag":
          data = build_tool_dag()
          self._respond_json(data)
        else:
            self.send_error(404)

    def _respond_json(self, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default access logs
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Bantz Trace Viewer")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), TraceViewerHandler)
    print(f"🔍 Bantz Trace Viewer → http://{args.host}:{args.port}")
    print("   Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
