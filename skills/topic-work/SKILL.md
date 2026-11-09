---
name: topic-work
description: Use when you want to know what the newsroom's recent References are about: the topics of the last week, two weeks or four, which are rising or falling, and which References show them.
---

# Topic work

This skill is for any agent that needs the shape of recent References, through `papyrus topics model` or the `topics_model` MCP tool. They are
the same operation, with the same input and the same JSON result.

Start with the default (the last 14 days, accepted and pending References, compared with the 14 days before). Narrow it with `--section` or
`--monitor` only when you have a reason. Read the marks as words as well as symbols: a topic marked rising has a larger share of this window
than of the one before, a new one had nothing like it before. A topic is a lead, not a verdict: open its representative References before you
write about it. Nothing here publishes anything.

<!-- generated:topic-operations -->
<!-- Generated from src/papyrus_content/topics/operations.py. Do not edit by hand; run scripts/generate-topic-operations.py. -->

## Reference: the operations

Each operation is a command and a tool with the same input and the same JSON result.

| Operation (MCP tool) | Command | What it does | Agent may call | Errors it can return |
| --- | --- | --- | --- | --- |
| `topics_model` | `papyrus topics model` | Find the topics in the References of the last 7, 14 or 28 days, by their source date, and say which are rising or falling. | yes | `not_found`, `engine_failed` |

Every operation may also return: `invalid_input`, `not_authorized`, `service_unavailable`, `not_implemented`.

### Every result

Success: `{"ok": true, "op": "...", "publication": "...", "result": {...}, "warnings": []}`. Failure: `{"ok": false, "op": "...", "error": {"code": "...", "message": "...", "retryable": false, "details": {}}}`. The command prints this JSON; it exits 0 on success and 2 on any error. `warnings` can say that a safety stop ended the read, that there were too few References for topics, or that the previous window was empty: read them.

### Errors

| Code | Meaning | Retry? | Details |
| --- | --- | --- | --- |
| `invalid_input` | The request does not fit the operation's input. | no | path names the field |
| `unknown_operation` | There is no topic operation by that name. | no | operation, or command for the CLI |
| `not_implemented` | This operation is described but not built yet. | no | operation |
| `not_authorized` | You are not an editor or admin of this site. | no |  |
| `not_found` | No such section in this publication. | no | section |
| `engine_failed` | The topic engine could not run, so nothing was modeled and nothing was saved. | yes | message says why, for example that Biblicus is not installed |
| `service_unavailable` | A permission or backend check could not be made. Nothing was changed. | yes |  |
<!-- /generated:topic-operations -->
