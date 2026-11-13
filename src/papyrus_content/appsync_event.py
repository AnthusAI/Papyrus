"""The one place a Lambda behind ``functionHandler`` reads which GraphQL field a request is for.

``functionHandler`` (amplify/data/function-handler.ts) is ``a.handler.function``, which Amplify compiles to its function
directive. That directive's AppSync function invokes the Lambda with this payload (``@aws-amplify/graphql-function-transformer``,
``graphql-function-transformer.js``)::

    {"typeName": ..., "fieldName": ..., "arguments": ..., "identity": ..., "source": ..., "request": ..., "prev": ...}

``fieldName`` is at the top level. There is no ``info`` object: ``info.fieldName`` is the shape of an AppSync direct Lambda
resolver, which these functions are not. A function that reads ``info.fieldName`` gets nothing on every real request.
``amplify_function_event`` builds the payload exactly as that template does, for tests.
"""

from __future__ import annotations

from typing import Any, Mapping

NO_OPERATION_MESSAGE = "The request carried no operation: it named no GraphQL field."


class NoOperation(ValueError):
    """The invocation named no GraphQL field, so there is nothing to run."""

    def __init__(self) -> None:
        super().__init__(NO_OPERATION_MESSAGE)


def operation_name(event: Mapping[str, Any]) -> str:
    """The GraphQL field the request is for, from the top-level ``fieldName`` Amplify's function directive sends."""
    name = event.get("fieldName")
    if not isinstance(name, str) or not name:
        raise NoOperation()
    return name


def amplify_function_event(type_name: str, field_name: str, arguments: Mapping[str, Any], identity: Mapping[str, Any] | None) -> dict[str, Any]:
    """The payload Amplify's function directive sends for one call: the same seven keys its request template writes."""
    return {
        "typeName": type_name,
        "fieldName": field_name,
        "arguments": dict(arguments),
        "identity": dict(identity) if identity is not None else None,
        "source": None,
        "request": {"headers": {}, "domainName": None},
        "prev": None,
    }


def user_pool_identity(username: str, groups: list[str], email: str | None = None) -> dict[str, Any]:
    """``$ctx.identity`` for a Cognito user pool caller, as AppSync gives it."""
    claims: dict[str, Any] = {"sub": f"sub-{username}", "cognito:username": username, "cognito:groups": list(groups)}
    if email is not None:
        claims["email"] = email
    return {"sub": f"sub-{username}", "issuer": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test", "username": username,
            "claims": claims, "sourceIp": ["203.0.113.1"], "defaultAuthStrategy": "ALLOW", "groups": list(groups)}
