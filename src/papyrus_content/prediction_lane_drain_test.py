"""Every partition a site backend queues prediction requests into has a schedule that drains it (features_backend/reference-prediction-on-create.feature).

On 2026-11-06 Machines on Machines had 366 requests queued in the shared ``hn`` partition (every site's ``monitoring.emailMonitorId`` defaults to it,
amplify/site-backend.ts) and the only ``email-references`` schedule drained ``p-apyr-us-email``: no request was ever read. This reads the two files that must
agree, so that cannot recur.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "infra/monitoring/papyrus-monitoring.yaml").read_text()
SITE_BACKEND = (ROOT / "amplify/site-backend.ts").read_text()


def site_default_partition() -> str:
    match = re.search(r'const emailMonitorId = site\.monitoring\?\.emailMonitorId \?\? "([a-z0-9-]+)"', SITE_BACKEND)
    assert match, "amplify/site-backend.ts no longer defaults emailMonitorId; update this test with the new rule"
    return match.group(1)


def parameter_default(name: str) -> str:
    match = re.search(rf'^  {name}:\n(?:    .*\n)*?    Default: "?([^"\n]*)"?\n', TEMPLATE, re.M)
    assert match, f"parameter {name} not found"
    return match.group(1)


def test_the_partition_sites_queue_into_by_default_is_drained_by_a_schedule():
    block = re.search(r"^  ReferencePredictionSchedule:\n(?:    .*\n|\n)+", TEMPLATE, re.M)
    assert block, "no ReferencePredictionSchedule"
    text = block.group(0)
    assert '"task":"email-references"' in text and '"monitorId":"${ReferencePredictionMonitorId}"' in text
    assert "rate(5 minutes)" in text
    assert parameter_default("ReferencePredictionMonitorId") == site_default_partition()


def test_the_drain_is_not_created_twice_for_one_partition():
    assert re.search(r"HasReferencePredictionMonitor: !And\n.*\n.*Equals \[!Ref ReferencePredictionMonitorId, !Ref EmailReferenceMonitorId\]", TEMPLATE)
