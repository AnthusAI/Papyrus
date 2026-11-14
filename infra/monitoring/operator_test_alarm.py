#!/usr/bin/env python3
"""Raise or clear the one dedicated test alarm, to prove operator email with a real message (docs/operator-alerts.md).

  AWS_PROFILE=papyrus-production python3 infra/monitoring/operator_test_alarm.py raise     # state ALARM: one email
  AWS_PROFILE=papyrus-production python3 infra/monitoring/operator_test_alarm.py clear     # state OK: one clearing email
  AWS_PROFILE=papyrus-production python3 infra/monitoring/operator_test_alarm.py status    # read only
  ... --dry-run                                                                            # print what it would do

It changes the state of exactly one alarm, papyrus-notify-test-alarm, which has no alarm actions, no data and no dependents, so nothing
else hears it (the SNS email included). It refuses any other account, and it has no argument that names another alarm. CloudWatch puts
the alarm back to OK by itself at the next evaluation if you forget `clear`; the clearing email then follows.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import ACCOUNT  # noqa: E402  (the one place the production account is named)

REGION = "us-east-1"
ALARM = "papyrus-notify-test-alarm"
STATES = {"raise": "ALARM", "clear": "OK"}
REASON = "Operator email test, raised by hand with operator_test_alarm.py. Nothing is wrong."


def run(command: str, cloudwatch, sts, dry_run: bool = False, out=print) -> int:
    account = sts.get_caller_identity()["Account"]
    if account != ACCOUNT:
        out("Refusing: the caller is not in the papyrus-production account.")
        return 2
    if command == "status":
        for alarm in cloudwatch.describe_alarms(AlarmNames=[ALARM])["MetricAlarms"]:
            out(f"{alarm['AlarmName']}: {alarm['StateValue']} since {alarm['StateUpdatedTimestamp']:%Y-%m-%d %H:%M:%S%z}")
            return 0
        out(f"{ALARM} does not exist: the papyrus-monitoring operator change set has not been applied.")
        return 1
    state = STATES[command]
    if dry_run:
        out(f"Would set {ALARM} to {state}.")
        return 0
    cloudwatch.set_alarm_state(AlarmName=ALARM, StateValue=state, StateReason=REASON)
    out(f"Set {ALARM} to {state}. Expect one operator email within about two minutes.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("raise", "clear", "status"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    import boto3

    session = boto3.session.Session(region_name=REGION)
    return run(args.command, session.client("cloudwatch"), session.client("sts"), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
