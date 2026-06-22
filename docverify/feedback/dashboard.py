"""Feedback dashboard — CLI summary of error rate trends and accuracy.

Usage:
    python -m docverify.feedback.dashboard
    python -m docverify.feedback.dashboard --html --output data/feedback/dashboard.html
"""

import argparse
import json
import os
from datetime import datetime

from docverify.feedback.tracker import FeedbackTracker, FeedbackMetrics
from docverify.utils import get_logger

logger = get_logger(__name__)


def format_cli(metrics: FeedbackMetrics) -> str:
    """Format metrics as a CLI-friendly text dashboard."""
    lines = []
    lines.append("=" * 60)
    lines.append("DOCVERIFY FEEDBACK DASHBOARD")
    lines.append("=" * 60)
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  Total reviews: {metrics.total_reviews}")
    lines.append(f"  Confirmed:     {metrics.confirmed}")
    lines.append(f"  Rejected:      {metrics.rejected}")
    lines.append(f"  Corrected:     {metrics.corrected}")
    lines.append(f"  Accuracy:      {metrics.accuracy:.1%}")
    lines.append("")

    # Error rate by field
    if metrics.error_rate_by_field:
        lines.append("ERROR RATE BY FIELD:")
        lines.append(f"  {'Field':<30} {'Error Rate':>10}")
        lines.append(f"  {'-'*30} {'-'*10}")
        for field, rate in sorted(metrics.error_rate_by_field.items(),
                                   key=lambda x: x[1], reverse=True):
            bar = "█" * int(rate * 20)
            lines.append(f"  {field:<30} {rate:>8.1%}  {bar}")
        lines.append("")

    # Error rate by doc type
    if metrics.error_rate_by_doc_type:
        lines.append("ERROR RATE BY DOCUMENT TYPE:")
        lines.append(f"  {'Doc Type':<30} {'Error Rate':>10}")
        lines.append(f"  {'-'*30} {'-'*10}")
        for dt, rate in sorted(metrics.error_rate_by_doc_type.items(),
                                key=lambda x: x[1], reverse=True):
            bar = "█" * int(rate * 20)
            lines.append(f"  {dt:<30} {rate:>8.1%}  {bar}")
        lines.append("")

    # Trend
    if metrics.trend:
        lines.append("ACCURACY TREND:")
        lines.append(f"  {'Date':<12} {'Accuracy':>10} {'Reviews':>8}  {'Chart'}")
        lines.append(f"  {'-'*12} {'-'*10} {'-'*8}  {'-'*20}")
        for point in metrics.trend[-14:]:  # last 14 days
            acc = point["accuracy"]
            count = point["count"]
            bar = "█" * int(acc * 20)
            lines.append(f"  {point['date']:<12} {acc:>8.1%} {count:>8}  {bar}")
        lines.append("")

    # Overall assessment
    lines.append("ASSESSMENT:")
    if metrics.total_reviews == 0:
        lines.append("  No feedback data yet. Start reviewing pipeline findings!")
    elif metrics.accuracy >= 0.95:
        lines.append("  ✓ Excellent accuracy — pipeline is performing well.")
    elif metrics.accuracy >= 0.85:
        lines.append("  ~ Good accuracy — some fields may need tuning.")
    elif metrics.accuracy >= 0.70:
        lines.append("  ⚠ Moderate accuracy — review rejected findings for patterns.")
    else:
        lines.append("  ✗ Low accuracy — significant tuning needed.")
        worst_fields = sorted(metrics.error_rate_by_field.items(),
                              key=lambda x: x[1], reverse=True)[:3]
        if worst_fields:
            lines.append(f"  Worst fields: {', '.join(f[0] for f in worst_fields)}")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_html(metrics: FeedbackMetrics) -> str:
    """Format metrics as an HTML dashboard."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>DocVerify Feedback Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               max-width: 800px; margin: 40px auto; padding: 0 20px;
               background: #1a1a2e; color: #e0e0e0; }}
        h1 {{ color: #00d4aa; border-bottom: 2px solid #00d4aa; padding-bottom: 10px; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0; }}
        .stat {{ background: #16213e; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat .value {{ font-size: 28px; font-weight: bold; color: #00d4aa; }}
        .stat .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #2a2a4a; }}
        th {{ color: #00d4aa; }}
        .bar {{ height: 16px; background: #00d4aa; border-radius: 3px; display: inline-block; }}
        .bar-bg {{ height: 16px; background: #2a2a4a; border-radius: 3px; width: 200px; display: inline-block; }}
        .good {{ color: #4ade80; }}
        .warn {{ color: #fbbf24; }}
        .bad {{ color: #f87171; }}
    </style>
</head>
<body>
    <h1>📊 DocVerify Feedback Dashboard</h1>
    <p style="color: #888;">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

    <div class="stats">
        <div class="stat">
            <div class="value">{metrics.total_reviews}</div>
            <div class="label">Total Reviews</div>
        </div>
        <div class="stat">
            <div class="value good">{metrics.confirmed}</div>
            <div class="label">Confirmed</div>
        </div>
        <div class="stat">
            <div class="value bad">{metrics.rejected}</div>
            <div class="label">Rejected</div>
        </div>
        <div class="stat">
            <div class="value {'good' if metrics.accuracy >= 0.9 else 'warn' if metrics.accuracy >= 0.7 else 'bad'}">{metrics.accuracy:.1%}</div>
            <div class="label">Accuracy</div>
        </div>
    </div>
"""

    if metrics.error_rate_by_field:
        html += """
    <h2>Error Rate by Field</h2>
    <table>
        <tr><th>Field</th><th>Error Rate</th><th></th></tr>
"""
        for field, rate in sorted(metrics.error_rate_by_field.items(),
                                   key=lambda x: x[1], reverse=True):
            bar_width = int(rate * 200)
            css_class = "bad" if rate > 0.3 else "warn" if rate > 0.1 else "good"
            html += f"""        <tr>
            <td>{field}</td>
            <td class="{css_class}">{rate:.1%}</td>
            <td><div class="bar-bg"><div class="bar" style="width: {bar_width}px;"></div></div></td>
        </tr>
"""
        html += "    </table>\n"

    if metrics.trend:
        html += """
    <h2>Accuracy Trend</h2>
    <table>
        <tr><th>Date</th><th>Accuracy</th><th>Reviews</th></tr>
"""
        for point in metrics.trend[-14:]:
            css_class = "good" if point["accuracy"] >= 0.9 else "warn" if point["accuracy"] >= 0.7 else "bad"
            html += f"""        <tr>
            <td>{point['date']}</td>
            <td class="{css_class}">{point['accuracy']:.1%}</td>
            <td>{point['count']}</td>
        </tr>
"""
        html += "    </table>\n"

    html += """
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description="DocVerify Feedback Dashboard")
    parser.add_argument("--html", action="store_true", help="Output as HTML")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--log-path", type=str, help="Custom feedback log path")
    args = parser.parse_args()

    tracker = FeedbackTracker(log_path=args.log_path)
    metrics = tracker.compute_metrics()

    if args.html:
        content = format_html(metrics)
        if args.output:
            from pathlib import Path
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Dashboard written to {out}")
        else:
            print(content)
    else:
        print(format_cli(metrics))


if __name__ == "__main__":
    main()
