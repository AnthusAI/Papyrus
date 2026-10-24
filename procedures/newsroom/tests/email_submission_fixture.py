"""Offline SES and table fixtures shared by email intake unit and narrative tests."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

from papyrus_content.email_submission_intake import EmailStore, process_ses_record
from papyrus_content.monitoring_router import RouterStore, run_router
from procedures.newsroom.tests.test_monitoring_router import FakeTable

RAW = b'''From: Editor <editor@example.org>\r
To: submissions@publication.example\r
Subject: Sources\r
Message-ID: <newsletter-1@example.org>\r
Content-Type: text/plain; charset=utf-8\r
\r
https://example.org/alpha\r
https://example.org/beta\r
'''


class S3:
    def __init__(self, raw=RAW):
        self.raw, self.calls = raw, []

    def get_object(self, *, Bucket, Key):
        self.calls.append((Bucket, Key))
        return {"ContentLength": len(self.raw), "Body": BytesIO(self.raw)}


class Cognito:
    def __init__(self, editors=None, *, enabled=True, verified=True, fail=False):
        self.editors = editors or {"us-east-1_fixture": {"editor@example.org"}}
        self.groups = {pool: {"editor"} for pool in self.editors}
        self.enabled, self.verified, self.fail = enabled, verified, fail
        self.calls = []

    def list_users(self, *, UserPoolId, Filter, Limit, AttributesToGet=None):
        self.calls.append(("list", UserPoolId, Filter, Limit))
        if self.fail:
            raise RuntimeError("directory unavailable")
        address = Filter[len('email = "'):-1]
        if address not in self.editors.get(UserPoolId, set()):
            return {"Users": []}
        return {"Users": [{"Username": "user-1", "Enabled": self.enabled, "Attributes": [
            {"Name": "email", "Value": address}, {"Name": "email_verified", "Value": str(self.verified).lower()}]}]}

    def admin_list_groups_for_user(self, *, UserPoolId, Username):
        self.calls.append(("groups", UserPoolId, Username))
        if self.fail:
            raise RuntimeError("directory unavailable")
        return {"Groups": [{"GroupName": name} for name in self.groups.get(UserPoolId, set())]}


def email_fixture():
    table = FakeTable()
    config = {"pk": "MONITOR#email-publication", "sk": "CONFIG#email", "schemaVersion": 1,
              "enabled": True, "accountId": "account-fixture", "kind": "publication",
              "addresses": ["submissions@publication.example"],
              "publicationIds": ["publication"], "maxMessagesPerSenderHour": 5}
    router = {"pk": config["pk"], "sk": "CONFIG#router", "accountId": config["accountId"],
              "mode": "live", "decisions": "direct", "maxItemsPerRun": 5,
              "publications": [{"publicationId": "publication", "site": "publication.example",
                                "userPoolId": "us-east-1_fixture",
                                "appsyncEndpoint": "https://fixture.appsync-api.us-east-1.amazonaws.com/graphql"}]}
    table.put_item(Item=config)
    table.put_item(Item=router)
    event = {"Records": [{"eventSource": "aws:ses", "ses": {
        "mail": {"messageId": "ses-delivery-1", "source": "editor@example.org",
                 "destination": config["addresses"], "commonHeaders": {"from": ["Editor <editor@example.org>"]}},
        "receipt": {"recipients": config["addresses"], **{field: {"status": "PASS"} for field in
                    ("spfVerdict", "dkimVerdict", "dmarcVerdict", "spamVerdict", "virusVerdict")}}
    }}]}
    return SimpleNamespace(table=table, config=config, router=router, event=deepcopy(event), s3=S3(), cognito=Cognito())


def collect_email(fixture, **options):
    return process_ses_record(fixture.event["Records"][0], EmailStore(fixture.table),
                              monitor_id="email-publication", bucket="mail-fixture", prefix="email-submissions/",
                              s3=fixture.s3, cognito=fixture.cognito, now=1000, **options)


def route_email(fixture, **options):
    delivered = []
    def deliver(_client, publication, discovery, _decision, _config):
        delivered.append((publication, discovery))
        return {"referenceId": "ref-" + discovery["sourceId"]}
    result = run_router(RouterStore(fixture.table), "email-publication", now=2000,
                        appsync=lambda endpoint: object(), deliver=deliver,
                        context_receipt=lambda client, publication: {}, cognito=fixture.cognito, **options)
    return result, delivered
