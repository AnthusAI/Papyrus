"""Private IAM-invoked grant operations; browser identity is established by the CMS."""
import os

import boto3

from grants import Grants, InvalidGrant
from store import DynamoGrantStore


def handler(event, _context):
    origin = os.environ["MCP_ORIGIN"]
    store = DynamoGrantStore(boto3.client("dynamodb"), boto3.client("kms"), os.environ["MCP_GRANT_TABLE"],
                             os.environ["MCP_KMS_KEY"], origin)
    grants = Grants(store, origin)
    if not isinstance(event, dict):
        return {"error": "invalid_request"}
    operation = event.get("operation")
    fields = {
        "verify": ("token", "resource"),
        "exchange": ("code", "client", "redirect", "resource", "verifier"),
        "refresh": ("token", "client", "resource"),
        "revoke": ("token", "client"),
        "issue": ("client", "redirect", "resource", "challenge", "principal", "upstream_expiry", "transaction_id"),
    }
    if not isinstance(operation, str) or operation not in fields or any(key not in event for key in fields[operation]):
        return {"error": "invalid_request"}
    for key in fields[operation]:
        expected = dict if key == "principal" else int if key == "upstream_expiry" else str
        if not isinstance(event[key], expected):
            return {"error": "invalid_request"}
    try:
        if operation == "verify":
            return {"principal": grants.verify(event["token"], resource=event["resource"])}
        if operation == "exchange":
            return grants.exchange(event["code"], client=event["client"], redirect=event["redirect"],
                                   resource=event["resource"], verifier=event["verifier"])
        if operation == "refresh":
            return grants.refresh(event["token"], client=event["client"], resource=event["resource"])
        if operation == "revoke":
            grants.revoke(event["token"], client=event["client"])
            return {}
        # The caller must derive principal, client registration, redirect and expiry from trusted server-side
        # state, never copy these fields from an unauthenticated browser request.
        if operation == "issue":
            return {"code": grants.issue_code(client=event["client"], redirect=event["redirect"],
                    resource=event["resource"], challenge=event["challenge"], principal=event["principal"],
                    upstream_expiry=event["upstream_expiry"], transaction_id=event["transaction_id"])}
    except InvalidGrant:
        return {"error": "invalid_grant"}
    return {"error": "invalid_request"}
