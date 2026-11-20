"""The fakes of the schedule features (schedule-trigger.feature, list-cadence.feature): EventBridge Scheduler, the FIFO wake queue, the site's API and its router
publications. No step is defined here, so any steps file may import it. No network."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import follow_up_timers as fu  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

ACCOUNT, REGION = "123456789012", "us-east-1"
ENDPOINT = "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql"
KEY_PARAMETER = "/amplify/shared/app123/OPENAI_API_KEY"
MONITOR = "hn"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
PROCEDURES = {"rate_items"}


class MissingGroup(Exception):
    response = {"Error": {"Code": "ResourceNotFoundException"}}


class FakeScheduler:
    """The parts of EventBridge Scheduler the reconciler uses: one group of named entries, and a count of what was written."""

    def __init__(self, group):
        self.group, self.entries, self.writes, self.deployed = group, {}, 0, True

    def _check(self, group):
        assert group == self.group, f"a schedule outside the site's group: {group}"
        if not self.deployed:
            raise MissingGroup()

    def list_schedules(self, GroupName, NamePrefix=None, NextToken=None):
        self._check(GroupName)
        assert NextToken is None
        return {"Schedules": [{"Name": name, "GroupName": GroupName} for name in sorted(self.entries) if name.startswith(NamePrefix or "")]}

    def get_schedule(self, Name, GroupName):
        self._check(GroupName)
        return copy.deepcopy(self.entries[Name])

    def create_schedule(self, **entry):
        self._check(entry["GroupName"])
        assert entry["Name"] not in self.entries, "created twice"
        self.writes += 1
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def update_schedule(self, **entry):
        self._check(entry["GroupName"])
        assert entry["Name"] in self.entries
        self.writes += 1
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def delete_schedule(self, Name, GroupName):
        self._check(GroupName)
        self.writes += 1
        del self.entries[Name]


class FakeSqs:
    def __init__(self, queue_name):
        self.queue_name = queue_name

    def get_queue_url(self, QueueName):
        assert QueueName == self.queue_name
        return {"QueueUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{QueueName}"}


class Message:
    def __init__(self, body, group):
        self.body, self.group, self.held = body, group, False


class WakeQueue:
    """A FIFO queue with content-based deduplication: a body already seen inside the window is dropped."""

    def __init__(self):
        self.messages, self.window, self.deleted = [], set(), []

    def send(self, body, group):
        identity = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if identity not in self.window:
            self.window.add(identity)
            self.messages.append(Message(body, group))

    def receive(self):
        message = next(iter(self.messages), None)
        if message is not None:
            message.held = True
        return message

    def delete(self, message):
        self.messages.remove(message)
        self.deleted.append(message)


class Backend(tpr.NewsroomClient):
    """The site's API as the start mutation behaves: the run's id comes from the wake key, and a second create is answered as a duplicate."""

    def __init__(self):
        super().__init__()
        self.records = {}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": "started"})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result


class Site:
    """The site's Automation records as the API stores them (JSON fields as strings), its run records and its agent policy document."""

    def __init__(self, site):
        self.rows, self.s3, self.table = {}, FakeS3(), FakeTable()
        self.site_store = SiteStore(self.s3, "bucket", self.table, now=lambda: "2026-11-17T00:00:00Z")
        self.policy = AgentPolicyStore(self.site_store)
        self.site, self.tenant_id = site, site

    def list_tenant_rows(self, model, fields):
        return [dict(row) for row in self.rows.values()]

    def get_record(self, model, record_id):
        return self.rows.get(record_id)

    def create_record(self, model, payload):
        self.rows[payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.rows[payload["id"]] = {**self.rows[payload["id"]], **payload}


class Reader:
    """The router config of the monitor: the publications an agent may name."""

    def __init__(self, site):
        known = {"appsyncEndpoint": ENDPOINT, "openaiKeyParameter": KEY_PARAMETER, "tenantId": site, "siteBucket": f"{site}-site-bucket"}
        self.publications = [{"publicationId": site, "site": f"{site}.example.test", **known}, {"publicationId": "another-site", "site": "another.example.test", **known}]

    def router_config(self, monitor_id):
        return {"publications": self.publications} if monitor_id == MONITOR else None


class Exceptions:
    ConflictException = type("ConflictException", (Exception,), {})
    ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})


class TimerScheduler:
    """The parts of EventBridge Scheduler a one-shot entry uses: create (a second create of one name conflicts), update, delete, and firing at a time."""

    exceptions = Exceptions

    def __init__(self, group, queue):
        self.group, self.queue, self.entries, self.delivered = group, queue, {}, []

    def create_schedule(self, **entry):
        assert entry["GroupName"] == self.group, f"an entry outside the site's group: {entry['GroupName']}"
        if entry["Name"] in self.entries:
            raise self.exceptions.ConflictException()
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def update_schedule(self, **entry):
        assert entry["GroupName"] == self.group and entry["Name"] in self.entries
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def delete_schedule(self, Name, GroupName):  # noqa: N803
        assert GroupName == self.group
        if Name not in self.entries:
            raise self.exceptions.ResourceNotFoundException()
        del self.entries[Name]

    @staticmethod
    def at_of(entry):
        expression = entry["ScheduleExpression"]
        assert expression.startswith("at(") and entry["ScheduleExpressionTimezone"] == "UTC", expression
        return datetime.strptime(expression[3:-1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

    def fire_until(self, moment):
        for name in sorted(self.entries, key=lambda n: self.at_of(self.entries[n])):
            entry = self.entries[name]
            if self.at_of(entry) <= moment:
                self.deliver(name, entry["Target"])
                if entry["ActionAfterCompletion"] == "DELETE":
                    del self.entries[name]

    def deliver(self, name, target):
        self.delivered.append((name, target))
        self.queue.send(target["Input"], target["SqsParameters"]["MessageGroupId"])


def utc(text):
    return datetime.strptime(text, fu.TIME_FORMAT).replace(tzinfo=timezone.utc)
