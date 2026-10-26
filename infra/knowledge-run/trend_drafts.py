"""Optional last step of the scheduled knowledge run: draft trend stories from the fresh snapshot (docs/knowledge-cloud-run.md).

Runs `papyrus ideas trends --site <publication> --snapshot <published index.json> --store proposals --max 2` once, after the
run's projection has published the snapshot. It files private `story_draft` Proposals and raises one soft review request;
nothing is published.

This script never fails the run: every problem is logged as `trend-drafts: skipped: <reason>` or `trend-drafts: failed: <reason>`
and the exit status is 0. It reads the OpenAI key from SSM at run time and hands it to the child process only; the key is never
printed.

Freshness: the published snapshot is fresh when its `asOf` is the execution's start date (UTC), or at most TREND_DRAFTS_MAX_AGE_DAYS
(default 1) before it, or the Monday of the start week, which is the `asOf` the `snapshot` stage writes (the knowledge snapshot is
weekly, so on any other day of the week the stage still stamps the Monday). So a scheduled, a daily and a manual run all draft, and a
snapshot of an earlier week is still skipped.

Environment: KNOWLEDGE_PUBLICATION, KNOWLEDGE_EXECUTION_START (ISO time),
KNOWLEDGE_OPENAI_KEY_PARAMETER, TREND_DRAFTS_ENDPOINT, TREND_DRAFTS_SNAPSHOT_URL, and optionally TREND_DRAFTS_MAX (2),
TREND_DRAFTS_MAX_AGE_DAYS (1), TREND_DRAFTS_WINDOW_DAYS (unset: the command's 28), TREND_DRAFTS_COOLDOWN_DAYS (unset: the
command's 7; 0 turns the anchor cooldown off), TREND_DRAFTS_FRESH_ATTEMPTS (3) and
TREND_DRAFTS_FRESH_WAIT_SECONDS (60).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from typing import Callable, Mapping

ENDPOINT_PATTERN = re.compile(r"^https://[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com/graphql$")


class Skip(Exception):
    """A reason to do nothing this week; logged, never an error."""


def start_date(started: str) -> dt.date:
    """The UTC date the execution started."""
    text = started.strip()
    if not text:
        raise Skip("KNOWLEDGE_EXECUTION_START is not set")
    moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is not None:
        moment = moment.astimezone(dt.timezone.utc)
    return moment.date()


def monday_of_start(started: str) -> dt.date:
    day = start_date(started)
    return day - dt.timedelta(days=day.weekday())


def fresh_dates(started: str, max_age_days: int) -> list[dt.date]:
    """The `asOf` dates that count as this execution's snapshot: the start date, up to `max_age_days` before it, and the Monday of the
    start week (what the `snapshot` stage writes). Newest first, no repeats."""
    if max_age_days < 0:
        raise Skip("TREND_DRAFTS_MAX_AGE_DAYS must not be negative")
    day = start_date(started)
    accepted = [day - dt.timedelta(days=age) for age in range(max_age_days + 1)]
    monday = monday_of_start(started)
    if monday not in accepted:
        accepted.append(monday)
    return accepted


def fetch_as_of(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "papyrus-trend-drafts"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https URL validated by the caller
        return json.load(response).get("asOf")


def wait_for_fresh_snapshot(url: str, accepted: list[dt.date], *, attempts: int, wait_seconds: float,
                            fetch: Callable[[str], str | None] = fetch_as_of, sleep: Callable[[float], None] = time.sleep) -> str:
    """Returns the published snapshot's asOf when it is one of the `accepted` dates; raises Skip with the reason when it never is."""
    wanted = {day.isoformat() for day in accepted}
    description = " or ".join(day.isoformat() for day in accepted)
    seen = "nothing readable"
    for attempt in range(1, attempts + 1):
        try:
            seen = str(fetch(url))
        except Exception as error:  # noqa: BLE001 - a CDN hiccup is a reason to wait, then to skip
            seen = f"unreadable ({type(error).__name__})"
        if seen in wanted:
            return seen
        print(f"trend-drafts: snapshot asOf is {seen}, want {description} (attempt {attempt} of {attempts})", flush=True)
        if attempt < attempts:
            sleep(wait_seconds)
    raise Skip(f"the published snapshot is stale: asOf {seen}, wanted {description}")


def read_openai_key(parameter: str) -> str:
    import boto3  # in the image; imported late so the module loads without it

    value = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()
    if not value:
        raise Skip(f"SSM parameter {parameter} is empty")
    return value


def trends_command(publication: str, snapshot_url: str, maximum: int, window_days: int | None = None, cooldown_days: int | None = None) -> list[str]:
    command = ["papyrus", "ideas", "trends", "--site", publication, "--snapshot", snapshot_url, "--store", "proposals", "--max", str(maximum)]
    command += ["--window-days", str(window_days)] if window_days else []
    return command + (["--cooldown-days", str(cooldown_days)] if cooldown_days is not None else [])


def run(environment: Mapping[str, str], *, fetch: Callable[[str], str | None] = fetch_as_of, sleep: Callable[[float], None] = time.sleep,
        read_key: Callable[[str], str] = read_openai_key, execute: Callable[..., int] | None = None) -> str:
    """Does the step; returns a one-line outcome. Raises Skip for a reason not to run and any other exception for a failure."""
    publication = (environment.get("KNOWLEDGE_PUBLICATION") or "").strip()
    endpoint = (environment.get("TREND_DRAFTS_ENDPOINT") or "").strip()
    snapshot_url = (environment.get("TREND_DRAFTS_SNAPSHOT_URL") or "").strip()
    key_parameter = (environment.get("KNOWLEDGE_OPENAI_KEY_PARAMETER") or "").strip()
    if not publication:
        raise Skip("KNOWLEDGE_PUBLICATION is not set")
    if not ENDPOINT_PATTERN.match(endpoint):
        raise Skip("TREND_DRAFTS_ENDPOINT is not an AppSync GraphQL address")
    if not snapshot_url.startswith("https://") or not snapshot_url.endswith("/index.json"):
        raise Skip("TREND_DRAFTS_SNAPSHOT_URL is not an https address of the snapshot's index.json")
    if not key_parameter:
        raise Skip("KNOWLEDGE_OPENAI_KEY_PARAMETER is not set")
    max_age = int(environment.get("TREND_DRAFTS_MAX_AGE_DAYS") or 1)
    accepted = fresh_dates(environment.get("KNOWLEDGE_EXECUTION_START", ""), max_age)
    as_of = wait_for_fresh_snapshot(
        snapshot_url, accepted, attempts=int(environment.get("TREND_DRAFTS_FRESH_ATTEMPTS") or 3),
        wait_seconds=float(environment.get("TREND_DRAFTS_FRESH_WAIT_SECONDS") or 60), fetch=fetch, sleep=sleep,
    )
    child_environment = dict(environment)
    child_environment.update(PAPYRUS_GRAPHQL_AUTH="iam", PAPYRUS_GRAPHQL_ENDPOINT=endpoint, OPENAI_API_KEY=read_key(key_parameter))
    window = (environment.get("TREND_DRAFTS_WINDOW_DAYS") or "").strip()
    cooldown = (environment.get("TREND_DRAFTS_COOLDOWN_DAYS") or "").strip()
    command = trends_command(publication, snapshot_url, int(environment.get("TREND_DRAFTS_MAX") or 2), int(window) if window else None, int(cooldown) if cooldown else None)
    print("+ " + " ".join(command), flush=True)
    status = (execute or (lambda args, env: subprocess.run(args, env=env, check=False).returncode))(command, child_environment)
    if status != 0:
        raise RuntimeError(f"`papyrus ideas trends` exited with {status}")
    return f"drafted from the snapshot of {as_of}"


def main() -> int:
    try:
        outcome = run(os.environ)
    except Skip as skip:
        print(f"trend-drafts: skipped: {skip}", flush=True)
    except Exception as error:  # noqa: BLE001 - this step must never fail the knowledge run
        print(f"trend-drafts: failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
    else:
        print(f"trend-drafts: ok: {outcome}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
