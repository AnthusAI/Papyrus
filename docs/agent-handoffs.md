# Handoffs: an Assignment is the request between agents

Slice F1 of the always-on agents design (PPY-51f96f; `docs/design/always-on-agents-architecture.md` section 4 and epic F). When one agent needs another's work (the
fact-checker needs a source found, the copy editor needs a figure) it asks for it as an Assignment on the Story. A person files the same record. Nothing is sent
between agents and no Message is written: Messages come only from people.

## Asking

```
papyrus handoffs request STORY_LINEAGE --responsibility research --why "Claim 3 cites no source. Find one."
```

An agent makes the same call as the operation `handoffs_request`, through the one gate: it needs the rung `propose` for its own responsibility. The responsible agent's own
rung decides what it may do about the request.

* The Assignment has the type `responsibility.<responsibility>`, sits on the Story, names who asked (`createdBy`: `agent:<id>`, or the person) and why (`summary`), and
  has a `created` event. The Story's reporting trail shows it.
* An agent that asks again with the same words gets the Assignment it already made, however it ended. A person's request is always new.
* An agent cannot ask its own responsibility. A responsibility nobody listens for leaves the Assignment open on the Story; nothing is woken.

## Running

The Assignment change feed wakes each agent whose definition listens for `Assignment/created` (or `Assignment/reopened`) with `filter: {responsibility: <its own>}`. The wake
key `<agent>|<Assignment id>|unversioned|created` is the claim: the run record made from it runs once. The runner marks the Assignment `claimed` when the run starts and closes
it when the run ends:

| The run ended | The Assignment | Then |
|---|---|---|
| `acted` or `nothing` | `completed`; the run, its outcome and what it said are the completion event's payload | the agent that asked is woken (`Assignment/completed`, addressed to it alone) |
| `asked` | stays `claimed` | the person's answer wakes the agent |
| `failed` | `failed`, with the error on the event | one flag for a person; nothing retries it. A person reopens it, which is a new wake |

## Stream

The feed reads the Assignment table's stream (a mapping with a filter on the type prefix `responsibility.`). The stream is the only way a request a person files in the newsroom
wakes an agent without a second code path.
