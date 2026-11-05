"""User-scoped client for the dedicated conditional agent draft mutation."""
from __future__ import annotations
import json


class StaffStoryWrites:
    """Compose into the staff adapter only when the site supports the mutation."""
    def story_save_draft(self, principal, *, lineageId: str, expectedCurrentVersionId: str, body: str, reason: str, frontMatter: str | None = None) -> dict:
        query = """mutation AgentSaveStoryDraft($input: AWSJSON!) {
          agentSaveStoryDraft(input: $input)
        }"""
        payload = {"lineageId": lineageId, "expectedCurrentVersionId": expectedCurrentVersionId, "body": body, "reason": reason}
        if frontMatter is not None:
            payload["frontMatter"] = frontMatter
        result = self.client.graphql(query, {"input": json.dumps(payload)})["agentSaveStoryDraft"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            raise ValueError("Invalid Story save response.")
        return result

    def story_request_publish(self, principal, *, lineageId: str, expectedCurrentVersionId: str) -> dict:
        query = """mutation AgentRequestStoryPublish($input: AWSJSON!) {
          agentRequestStoryPublish(input: $input)
        }"""
        payload = {"lineageId": lineageId, "expectedCurrentVersionId": expectedCurrentVersionId}
        result = self.client.graphql(query, {"input": json.dumps(payload)})["agentRequestStoryPublish"]
        if isinstance(result, str): result = json.loads(result)
        if not isinstance(result, dict): raise ValueError("Invalid publish request response.")
        return result
