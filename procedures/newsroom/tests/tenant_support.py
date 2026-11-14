"""The tenant context a handler's own functions run in when a test calls them without the handler (PPY-7dc463)."""
from __future__ import annotations

from papyrus_content.tenant_context import acting_for, build_invocation_tenant_context


def dedicated_call():
    """One call on a dedicated site with no tenant, which is every site today: ``with dedicated_call():`` or ``self.enterContext(dedicated_call())``."""
    return acting_for(build_invocation_tenant_context(None))


#: What AppSync gives a function for a call signed with IAM (an operator or another function): no user, no claims.
IAM_IDENTITY = {"accountId": "000000000000", "userArn": "arn:aws:iam::000000000000:role/operator"}
