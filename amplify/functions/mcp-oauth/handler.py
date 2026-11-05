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
    operation = event.get("operation")
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
                    upstream_expiry=event["upstream_expiry"])}
    except InvalidGrant:
        return {"error": "invalid_grant"}
    except (KeyError, TypeError):
        return {"error": "invalid_request"}
    return {"error": "invalid_request"}
