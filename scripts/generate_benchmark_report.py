#!/usr/bin/env python3
"""Generate Markdown Report from Benchmark Results (Issue #161).

Creates comprehensive markdown reports with:
- Performance comparison table (3B vs Hybrid)
- Quality metrics
- Regression alerts
- Category breakdown
- Individual test case results
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class BenchmarkReportGenerator:
    """Generate markdown reports from benchmark results."""
    
    def __init__(self, results_dir: Path = Path("artifacts/results")):
        self.results_dir = results_dir
        self.data_3b: Optional[dict] = None
        self.data_hybrid: Optional[dict] = None
    
    def load_results(self) -> bool:
        """Load benchmark results."""
        file_3b = self.results_dir / "bench_hybrid_3b_only.json"
        file_hybrid = self.results_dir / "bench_hybrid_hybrid.json"
        
        if file_3b.exists():
            with file_3b.open("r", encoding="utf-8") as f:
                self.data_3b = json.load(f)
        
        if file_hybrid.exists():
            with file_hybrid.open("r", encoding="utf-8") as f:
                self.data_hybrid = json.load(f)
        
        return self.data_3b is not None or self.data_hybrid is not None
    
    def generate_header(self) -> str:
        """Generate report header."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        lines = [
            "# Bantz Benchmark Report",
            "",
            f"**Generated:** {now}",
            "",
            "## Overview",
            "",
            "This report compares performance between:",
            "- **3B-only**: Single Qwen 2.5 3B model for all tasks",
            "- **Hybrid**: 3B router + 7B finalizer for quality responses",
            "",
        ]
        
        return "\n".join(lines)
    
    def generate_summary_table(self) -> str:
        """Generate summary comparison table."""
        lines = [
            "## Summary Comparison",
            "",
            "| Metric | 3B-only | Hybrid | Winner |",
            "|--------|---------|--------|--------|",
        ]
        
        if self.data_3b and self.data_hybrid:
            s3b = self.data_3b.get("summary", {})
            shybrid = self.data_hybrid.get("summary", {})
            
            # Accuracy
            acc_3b = s3b.get("overall_accuracy", 0)
            acc_hybrid = shybrid.get("overall_accuracy", 0)
            winner_acc = "🏆 Hybrid" if acc_hybrid > acc_3b else "3B-only"
            lines.append(f"| Overall Accuracy | {acc_3b:.1%} | {acc_hybrid:.1%} | {winner_acc} |")
            
            # Route accuracy
            route_3b = s3b.get("route_accuracy", 0)
            route_hybrid = shybrid.get("route_accuracy", 0)
            winner_route = "🏆 Hybrid" if route_hybrid > route_3b else "3B-only"
            lines.append(f"| Route Accuracy | {route_3b:.1%} | {route_hybrid:.1%} | {winner_route} |")
            
            # TTFT p50
            ttft_3b = s3b.get("ttft_p50_ms", 0)
            ttft_hybrid = shybrid.get("ttft_p50_ms", 0)
            winner_ttft = "🏆 3B-only" if ttft_3b < ttft_hybrid else "Hybrid"
            lines.append(f"| TTFT p50 | {ttft_3b:.0f}ms | {ttft_hybrid:.0f}ms | {winner_ttft} |")
            
            # TTFT p95
            ttft95_3b = s3b.get("ttft_p95_ms", 0)
            ttft95_hybrid = shybrid.get("ttft_p95_ms", 0)
            winner_ttft95 = "🏆 3B-only" if ttft95_3b < ttft95_hybrid else "Hybrid"
            lines.append(f"| TTFT p95 | {ttft95_3b:.0f}ms | {ttft95_hybrid:.0f}ms | {winner_ttft95} |")
            
            # Total latency
            lat_3b = s3b.get("latency_mean_ms", 0)
            lat_hybrid = shybrid.get("latency_mean_ms", 0)
            winner_lat = "🏆 3B-only" if lat_3b < lat_hybrid else "Hybrid"
            lines.append(f"| Latency (mean) | {lat_3b:.0f}ms | {lat_hybrid:.0f}ms | {winner_lat} |")
            
            # Token usage
            tok_3b = s3b.get("avg_tokens_per_case", 0)
            tok_hybrid = shybrid.get("avg_tokens_per_case", 0)
            winner_tok = "🏆 3B-only" if tok_3b < tok_hybrid else "Hybrid"
            lines.append(f"| Tokens/case | {tok_3b:.0f} | {tok_hybrid:.0f} | {winner_tok} |")
        
        lines.append("")
        return "\n".join(lines)
    
    def generate_regression_alerts(self) -> str:
        """Generate regression alerts."""
        lines = [
            "## Regression Alerts",
            "",
        ]
        
        alerts = []
        
        if self.data_hybrid:
            s = self.data_hybrid.get("summary", {})
            
            # TTFT regression
            if s.get("ttft_p95_ms", 0) > 400:
                alerts.append(
                    f"⚠️  **TTFT Regression**: p95 is {s['ttft_p95_ms']:.0f}ms (threshold: 400ms)"
                )
            
            # Accuracy regression
            if s.get("overall_accuracy", 1.0) < 0.85:
                alerts.append(
                    f"⚠️  **Accuracy Regression**: {s['overall_accuracy']:.1%} (threshold: 85%)"
                )
            
            # Route accuracy
            if s.get("route_accuracy", 1.0) < 0.90:
                alerts.append(
                    f"⚠️  **Route Accuracy Low**: {s['route_accuracy']:.1%} (threshold: 90%)"
                )
            
            # Failure rate
            if s.get("total_cases", 0) > 0:
                failure_rate = s.get("failed_cases", 0) / s["total_cases"]
                if failure_rate > 0.10:
                    alerts.append(
                        f"⚠️  **High Failure Rate**: {failure_rate:.1%} (threshold: 10%)"
                    )
        
        if alerts:
            lines.extend(alerts)
        else:
            lines.append("✅ No regression alerts - all metrics within thresholds!")
        
        lines.append("")
        return "\n".join(lines)
    
    def generate_performance_details(self, mode: str, data: dict) -> str:
        """Generate detailed performance metrics for one mode."""
        s = data.get("summary", {})
        
        lines = [
            f"### {mode.upper()} Performance",
            "",
            f"**Test Cases:** {s.get('total_cases', 0)} total, "
            f"{s.get('successful_cases', 0)} successful, "
            f"{s.get('failed_cases', 0)} failed",
            "",
            "**Accuracy Metrics:**",
            f"- Overall: {s.get('overall_accuracy', 0):.1%}",
            f"- Route: {s.get('route_accuracy', 0):.1%}",
            f"- Intent: {s.get('intent_accuracy', 0):.1%}",
            f"- Tools: {s.get('tools_accuracy', 0):.1%}",
            "",
            "**Performance Metrics:**",
            f"- TTFT p50: {s.get('ttft_p50_ms', 0):.0f}ms",
            f"- TTFT p95: {s.get('ttft_p95_ms', 0):.0f}ms",
            f"- TTFT p99: {s.get('ttft_p99_ms', 0):.0f}ms",
            f"- Latency (mean): {s.get('latency_mean_ms', 0):.0f}ms",
            f"- Latency p95: {s.get('latency_p95_ms', 0):.0f}ms",
            "",
            "**Token Usage:**",
            f"- Total input: {s.get('total_input_tokens', 0):,}",
            f"- Total output: {s.get('total_output_tokens', 0):,}",
            f"- Avg per case: {s.get('avg_tokens_per_case', 0):.0f}",
            "",
        ]
        
        # Accuracy by category
        if s.get("accuracy_by_category"):
            lines.append("**Accuracy by Category:**")
            for cat, acc in sorted(s["accuracy_by_category"].items()):
                lines.append(f"- {cat}: {acc:.1%}")
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_category_breakdown(self) -> str:
        """Generate category-wise breakdown."""
        lines = [
            "## Category Breakdown",
            "",
        ]
        
        if self.data_hybrid:
            s = self.data_hybrid.get("summary", {})
            acc_by_cat = s.get("accuracy_by_category", {})
            lat_by_cat = s.get("latency_by_category", {})
            
            if acc_by_cat:
                lines.append("| Category | Accuracy | Latency (mean) | Status |")
                lines.append("|----------|----------|----------------|--------|")
                
                for cat in sorted(acc_by_cat.keys()):
                    acc = acc_by_cat.get(cat, 0)
                    lat = lat_by_cat.get(cat, 0)
                    status = "✅" if acc > 0.80 else "⚠️ " if acc > 0.70 else "❌"
                    lines.append(f"| {cat} | {acc:.1%} | {lat:.0f}ms | {status} |")
                
                lines.append("")
        
        return "\n".join(lines)
    
    def generate_failed_cases(self, mode: str, data: dict) -> str:
        """Generate list of failed test cases."""
        results = data.get("results", [])
        failed = [r for r in results if r.get("error") or not r.get("overall_correct")]
        
        if not failed:
            return ""
        
        lines = [
            f"### Failed Cases ({mode})",
            "",
            f"Total failed: {len(failed)}/{len(results)}",
            "",
            "| Test ID | Category | Error | Route | Tools |",
            "|---------|----------|-------|-------|-------|",
        ]
        
        for r in failed[:20]:  # Limit to 20
            test_id = r.get("test_id", "unknown")
            category = r.get("category", "unknown")
            error = r.get("error", "incorrect")[:50]
            route = r.get("route", "")
            tools = ", ".join(r.get("tools_called", []))[:30]
            lines.append(f"| {test_id} | {category} | {error} | {route} | {tools} |")
        
        lines.append("")
        return "\n".join(lines)
    
    def generate_recommendations(self) -> str:
        """Generate recommendations based on results."""
        lines = [
            "## Recommendations",
            "",
        ]
        
        recommendations = []
        
        if self.data_hybrid:
            s = self.data_hybrid.get("summary", {})
            
            # TTFT recommendations
            if s.get("ttft_p95_ms", 0) > 300:
                recommendations.append(
                    "- **TTFT Optimization**: Consider reducing prompt size or using smaller router model"
                )
            
            # Accuracy recommendations
            if s.get("overall_accuracy", 1.0) < 0.90:
                recommendations.append(
                    "- **Accuracy Improvement**: Review failed cases and improve prompt engineering"
                )
            
            # Route accuracy
            if s.get("route_accuracy", 1.0) < 0.92:
                recommendations.append(
                    "- **Route Classification**: Add more route examples to prompt"
                )
            
            # Tools accuracy
            if s.get("tools_accuracy", 1.0) < 0.80:
                recommendations.append(
                    "- **Tool Selection**: Improve tool descriptions and examples"
                )
        
        # Compare modes
        if self.data_3b and self.data_hybrid:
            s3b = self.data_3b.get("summary", {})
            shybrid = self.data_hybrid.get("summary", {})
            
            acc_diff = shybrid.get("overall_accuracy", 0) - s3b.get("overall_accuracy", 0)
            if acc_diff < 0.05:
                recommendations.append(
                    "- **Hybrid Benefit**: Accuracy gain from hybrid is small - consider cost/latency tradeoff"
                )
        
        if recommendations:
            lines.extend(recommendations)
        else:
            lines.append("✅ All metrics look good - no immediate recommendations!")
        
        lines.append("")
        return "\n".join(lines)
    
    def generate_report(self) -> str:
        """Generate complete markdown report."""
        if not self.load_results():
            return "# Error\n\nNo benchmark results found.\n"
        
        sections = [
            self.generate_header(),
            self.generate_summary_table(),
            self.generate_regression_alerts(),
        ]
        
        if self.data_3b:
            sections.append("## Performance Details\n")
            sections.append(self.generate_performance_details("3b_only", self.data_3b))
        
        if self.data_hybrid:
            if not self.data_3b:
                sections.append("## Performance Details\n")
            sections.append(self.generate_performance_details("hybrid", self.data_hybrid))
        
        sections.append(self.generate_category_breakdown())
        
        if self.data_hybrid:
            failed = self.generate_failed_cases("hybrid", self.data_hybrid)
            if failed:
                sections.append(failed)
        
        sections.append(self.generate_recommendations())
        
        return "\n".join(sections)
    
    def save_report(self, output_file: Path) -> None:
        """Generate and save report."""
        report = self.generate_report()
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(report, encoding="utf-8")
        
        print(f"Report saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("artifacts/results"),
        help="Directory with benchmark results",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/results/BENCHMARK_REPORT.md"),
        help="Output markdown file",
    )
    
    args = parser.parse_args()
    
    generator = BenchmarkReportGenerator(results_dir=args.results_dir)
    generator.save_report(args.output)
    
    # Also print to console
    print("\n" + "="*60)
    print(generator.generate_report())
    print("="*60)


if __name__ == "__main__":
    main()
