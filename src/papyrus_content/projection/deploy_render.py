"""The post-deploy render: project every published page, then look for drift without repairing it."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .engine import ProjectionContext, ReconcileReport, project_all, reconcile
from .model import ProjectionReport

METRIC_NAMESPACE = "Papyrus/Projection"
DRIFT_METRIC_NAME = "DeployRenderDrift"
LISTED_KEYS_LIMIT = 25


@dataclass
class DeployRenderReport:
    render: ProjectionReport
    drift: ReconcileReport

    @property
    def ok(self) -> bool:
        return self.render.ok and self.drift.ok

    @property
    def drift_count(self) -> int:
        return (
            len(self.drift.stale_items)
            + len(self.drift.removed_items)
            + len(self.drift.stale_listings)
            + len(self.drift.orphan_pages)
            + self.drift.redirects_repaired
        )

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "written": len(self.render.written),
            "deleted": len(self.render.deleted),
            "redirectsWritten": self.render.redirects_written,
            "errors": [*self.render.errors, *self.drift.errors],
            "drift": {
                "found": self.drift.drift,
                "count": self.drift_count,
                "staleItems": self.drift.stale_items[:LISTED_KEYS_LIMIT],
                "removedItems": self.drift.removed_items[:LISTED_KEYS_LIMIT],
                "staleListings": self.drift.stale_listings[:LISTED_KEYS_LIMIT],
                "orphanPages": self.drift.orphan_pages[:LISTED_KEYS_LIMIT],
                "redirectsToRepair": self.drift.redirects_repaired,
                "redirectsUnexpected": self.drift.redirects_unexpected,
            },
        }


def deploy_render(context: ProjectionContext) -> DeployRenderReport:
    """Render everything, then run reconcile as a dry run: orphans and other drift are reported, never deleted."""
    render = project_all(context)
    drift = reconcile(context, dry_run=True)
    return DeployRenderReport(render=render, drift=drift)


def drift_metric_line(report: DeployRenderReport) -> str:
    """A CloudWatch embedded-metric-format log line: it becomes the metric the drift alarm watches."""
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {"Namespace": METRIC_NAMESPACE, "Dimensions": [["FunctionName"]], "Metrics": [{"Name": DRIFT_METRIC_NAME, "Unit": "Count"}]}
                ],
            },
            "FunctionName": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown"),
            DRIFT_METRIC_NAME: report.drift_count,
            "deployRender": report.to_dict(),
        }
    )
