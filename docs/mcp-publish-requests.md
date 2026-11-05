# MCP publication requests

`story_request_publish` asks for a person's approval of the current draft when the site's publish gate requires it. The request identifies the exact version and content hash, and the site's normal publish checks run first. A pending or rejected request is returned with its ID. An agent's approval never satisfies a gate that requires a person.

The tool does not publish. When the gate is off or a person has approved the version, it directs the caller to the staff console. A changed draft must be requested again. Tenant-scoped backends do not expose this operation because ReviewRequest records do not yet carry a tenant ownership key.
