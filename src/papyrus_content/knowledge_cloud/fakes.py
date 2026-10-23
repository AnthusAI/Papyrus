"""Test doubles for the cloud knowledge run: a recording shell that fakes the CLIs, and an AWS-backed Run (moto)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import boto3

from .config import CloudRunConfig
from .ledger import RunLedger
from .stages import Run, StageFailed
from .state import StateStore

STATE_BUCKET = "knowledge-state"
LEDGER_TABLE = "knowledge-ledger"
SITE_BUCKET = "site-bucket"
ENVIRONMENT = {
    "KNOWLEDGE_PUBLICATION": "shipped",
    "KNOWLEDGE_STATE_BUCKET": STATE_BUCKET,
    "KNOWLEDGE_LEDGER_TABLE": LEDGER_TABLE,
    "KNOWLEDGE_EXECUTION_NAME": "manual-1",
    "KNOWLEDGE_EXECUTION_START": "2026-10-26T05:00:00Z",
    "KNOWLEDGE_ALLOW_TEST_FAILURE": "true",
    "KNOWLEDGE_SITE_REPO": "https://example.test/site.git",
    "KNOWLEDGE_BEATS_CONFIG": "web/scoring.json",
    "KNOWLEDGE_CONCEPT_KINDS": "task,concept",
    "PAPYRUS_SITE_BUCKET": SITE_BUCKET,
    "AWS_REGION": "us-east-1",
    "PAPYRUS_PLUGINS": "newsletter,reader-steering",
    "KNOWLEDGE_CONTENT_ACTIONS_FUNCTION": "content-actions-fn",
    "KNOWLEDGE_AMPLIFY_APP_ID": "dapp123",
}
DEPLOYED_COMMIT = "d" * 40


class FakeSite:
    """The deployed site's Lambda: its environment is what the plugin check compares with."""

    def __init__(self, plugins: str = "reader-steering,newsletter") -> None:
        self.variables = {"PAPYRUS_PLUGINS": plugins}
        self.objects: dict[str, bytes] = {}

    def read_object(self, bucket: str, key: str) -> bytes | None:
        assert bucket == SITE_BUCKET
        return self.objects.get(key)

    def deployed_commit(self, app_id: str, branch: str) -> str:
        assert (app_id, branch) == ("dapp123", "main")
        return DEPLOYED_COMMIT

    def deployed_environment(self, function: str) -> dict[str, str]:
        assert function == "content-actions-fn"
        return dict(self.variables)


class FakeShell:
    """Records every command; fakes the files the real tools write so the next stage can read them."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self.calls: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []
        self.fail_on: str | None = None
        self.head = DEPLOYED_COMMIT
        self.tip = DEPLOYED_COMMIT
        self.current = "cur" + "0" * 61
        self.trends = "trd" + "0" * 61

    def __call__(self, args: list[str], *, cwd: Path, env: Mapping[str, str], stdout: Path | None = None) -> None:
        self.calls.append(list(args))
        self.envs.append(dict(env))
        text = " ".join(args)
        if self.fail_on and self.fail_on in text:
            raise StageFailed(f"`{args[0]}` exited with 1")
        out = ""
        if args[:2] in (["git", "clone"], ["git", "init"]):
            site = Path(args[-1])
            (site / "web").mkdir(parents=True, exist_ok=True)
            (site / "web" / "scoring.json").write_text("{}")
            (site / "requirements-publication.txt").write_text("papyrus-newsroom[markus]==5.28.0\n")
        elif args[:2] == ["pip", "install"]:
            Path(args[args.index("--target") + 1]).mkdir(parents=True, exist_ok=True)
        elif args[:2] == ["python", "-c"]:
            pass
        elif args[:2] == ["git", "ls-remote"]:
            out = f"{self.tip}\trefs/heads/main\n"
        elif "rev-parse" in args:
            out = self.head + "\n"
        elif args[:3] == ["papyrus", "knowledge", "corpus"]:
            raw = Path(args[args.index("--out") + 1])
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "item-1.md").write_text("# one")
        elif args[:2] == ["biblicus", "init"]:
            (Path(args[2]) / "metadata").mkdir(parents=True, exist_ok=True)
        elif args[:3] == ["biblicus", "extract", "build"]:
            latest = Path(args[args.index("--corpus") + 1]) / "extracted" / "pipeline"
            latest.mkdir(parents=True, exist_ok=True)
            (latest / "latest.json").write_text(json.dumps({"snapshot_id": "ext1"}))
        elif args[:3] == ["biblicus", "analyze", "topics"]:
            out = json.dumps({"snapshot": {"snapshot_id": self.current}})
        elif args[:3] == ["biblicus", "analyze", "topic-trends"]:
            out = json.dumps({"snapshot_id": self.trends})
        elif args[:3] == ["biblicus", "analyze", "topic-identity"]:
            out = "{}"
        elif args[:3] == ["biblicus", "extract", "typed-entities"]:
            typed = Path(args[args.index("--out") + 1])
            typed.mkdir(parents=True, exist_ok=True)
            (typed / "output.json").write_text("{}")
            out = "{}"
        elif args[:4] == ["papyrus", "ops", "content", "project"]:
            out = json.dumps({"written": 3, "deleted": 0})
        if stdout is not None:
            stdout.parent.mkdir(parents=True, exist_ok=True)
            stdout.write_text(out)


def make_run(work: Path, environment: Mapping[str, str] | None = None, *, execution: str | None = None) -> tuple[Run, FakeShell]:
    """A Run over moto S3 and DynamoDB (call inside ``mock_aws``). ``config/`` holds the operator-maintained files."""
    values = {**ENVIRONMENT, "KNOWLEDGE_WORK_DIR": str(work), **(environment or {})}
    if execution:
        values["KNOWLEDGE_EXECUTION_NAME"] = execution
    config = CloudRunConfig.from_environment(values)
    s3 = boto3.client("s3", region_name="us-east-1")
    if STATE_BUCKET not in [bucket["Name"] for bucket in s3.list_buckets()["Buckets"]]:
        s3.create_bucket(Bucket=STATE_BUCKET)
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=LEDGER_TABLE,
            KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}, {"AttributeName": "runKey", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}, {"AttributeName": "runKey", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        state = StateStore(s3, STATE_BUCKET, config.state_prefix)
        state.write_text("config/vocabulary.yml", "entity_kinds:\n  - {key: maker, label: company or developer}\n")
        state.write_text("config/stop-words.txt", "card\n")
        state.write_text("config/amplify_outputs.json", json.dumps({"data": {"url": "https://api.example.test/graphql"}}))
    state = StateStore(s3, STATE_BUCKET, config.state_prefix)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(LEDGER_TABLE)
    ledger = RunLedger(table, config.publication, config.week, config.execution_name, clock=lambda: dt.datetime(2026, 10, 26, 5, tzinfo=dt.timezone.utc))
    shell = FakeShell(work)
    return Run(config=config, state=state, ledger=ledger, shell=shell, environment=values, services=FakeSite()), shell
