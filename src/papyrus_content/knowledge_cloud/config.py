"""What a stage of the cloud knowledge run knows, read from the container environment the stack sets."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

STAGES = (
    "corpus-sync",
    "topic-model",
    "typed-extraction",
    "publish-run",
    "ai-review",
    "publish-relations",
    "snapshot",
    "archive",
    "wiki-sync",
    "projection",
)
PROJECTION_STAGE = STAGES[-1]
TEST_EXECUTION_PREFIX = "test-"
DEFAULT_MONITOR_WEEKS = 52


class ConfigError(ValueError):
    pass


def iso_week(day: dt.date) -> str:
    year, week, _weekday = day.isocalendar()
    return f"{year}-W{week:02d}"


def monday_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def parse_start(value: str | None, *, now: dt.datetime | None = None) -> dt.datetime:
    text = (value or "").strip()
    if not text:
        return now or dt.datetime.now(dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _monitor_sources(value: str | None) -> tuple[str, ...]:
    from ..knowledge_snapshot.monitor_records import parse_sources  # noqa: PLC0415

    try:
        return parse_sources(value)
    except ValueError as error:
        raise ConfigError(f"KNOWLEDGE_MONITOR_SOURCES: {error}") from error


def _required(environment: Mapping[str, str], name: str) -> str:
    value = (environment.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name} is not set.")
    return value


@dataclass(frozen=True)
class CloudRunConfig:
    publication: str
    state_bucket: str
    ledger_table: str
    execution_name: str
    started: dt.datetime
    fail_stage: str
    allow_test_failure: bool
    site_repo: str
    site_branch: str
    static_subdir: str
    site_bucket: str
    beats_config: str | None
    concept_kinds: str | None
    monitor_sources: tuple[str, ...]
    monitor_weeks: int
    openai_parameter: str
    work_dir: Path
    region: str

    @property
    def as_of(self) -> dt.date:
        return self.started.date()

    @property
    def week(self) -> str:
        return iso_week(self.as_of)

    @property
    def monday(self) -> dt.date:
        return monday_of(self.as_of)

    @property
    def state_prefix(self) -> str:
        return f"publications/{self.publication}/"

    @property
    def actor_name(self) -> str:
        return f"{self.publication.capitalize()} research agent"

    @property
    def failure_injection_allowed(self) -> bool:
        return self.allow_test_failure and self.execution_name.startswith(TEST_EXECUTION_PREFIX)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], *, now: dt.datetime | None = None) -> "CloudRunConfig":
        publication = _required(environment, "KNOWLEDGE_PUBLICATION")
        return cls(
            publication=publication,
            state_bucket=_required(environment, "KNOWLEDGE_STATE_BUCKET"),
            ledger_table=_required(environment, "KNOWLEDGE_LEDGER_TABLE"),
            execution_name=(environment.get("KNOWLEDGE_EXECUTION_NAME") or "manual").strip(),
            started=parse_start(environment.get("KNOWLEDGE_EXECUTION_START"), now=now),
            fail_stage=(environment.get("KNOWLEDGE_FAIL_STAGE") or "").strip(),
            allow_test_failure=(environment.get("KNOWLEDGE_ALLOW_TEST_FAILURE") or "").strip().lower() == "true",
            site_repo=_required(environment, "KNOWLEDGE_SITE_REPO"),
            site_branch=(environment.get("KNOWLEDGE_SITE_BRANCH") or "main").strip(),
            static_subdir=(environment.get("KNOWLEDGE_STATIC_SUBDIR") or "web").strip(),
            site_bucket=_required(environment, "PAPYRUS_SITE_BUCKET"),
            beats_config=(environment.get("KNOWLEDGE_BEATS_CONFIG") or "").strip() or None,
            concept_kinds=(environment.get("KNOWLEDGE_CONCEPT_KINDS") or "").strip() or None,
            monitor_sources=_monitor_sources(environment.get("KNOWLEDGE_MONITOR_SOURCES")),
            monitor_weeks=int((environment.get("KNOWLEDGE_MONITOR_WEEKS") or "").strip() or DEFAULT_MONITOR_WEEKS),
            openai_parameter=(environment.get("KNOWLEDGE_OPENAI_KEY_PARAMETER") or f"/papyrus/{publication}/openai-api-key").strip(),
            work_dir=Path((environment.get("KNOWLEDGE_WORK_DIR") or "/work").strip()),
            region=(environment.get("AWS_REGION") or "us-east-1").strip(),
        )
