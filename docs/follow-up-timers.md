# Follow-up timers

A record that waits names the time it waits for: `dueAt`, with `waitingFor` (a Delivery already carries both). One helper turns that time into a timer, and a timer does one thing: it puts a wake on the site's wake queue. Nothing polls. This is slice C2 (PPY-3ff011) of [the always-on agents design](design/always-on-agents-architecture.md#35-timers-are-events); its spec is `features_backend/follow-up-timers.feature`.

## The contract

One implementation holds it: `src/papyrus_content/follow_up_timers.py`. Python is where the equivalent code already lives (scheduled publishing's `story_schedule.py`, the schedule reconciler, the wake sender); the TypeScript side of the repository only holds the infrastructure, so there is no second helper to keep in step.

| Operation | What happens |
| --- | --- |
| Set a due time | One EventBridge Scheduler entry, `at(<UTC instant>)`, no flexible window, `ActionAfterCompletion: DELETE`. It is created, or, when the record already has one, moved (same name, so a record never has two). |
| Clear the due time | The entry is deleted. An entry the service already deleted after it fired is not an error. |
| The entry fires | The site's wake queue gets one message: a wake whose key is `<owner>\|<record id>\|<due time>\|due`. The service then deletes the entry. |
| The run starts | It reads the record again. `check_wake(wake_key, row)` says whether the record still waits for exactly the time the wake names. If not (the time moved, was cleared, or the record is done or gone), the wake does nothing and says why. |

`FollowUpTimers.sync(kind, record id, due_at, owner=..., base=..., waiting_for=...)` is the one call: call it wherever a record's `dueAt` is written, with `due_at=None` when the wait ends. `base` is the runner request as for any start (procedure, publication, policy location, input).

* **Where.** The entry is in the site's schedule group (`papyrus-<site>-agent-schedules`, from the `agents` stack) and its only target is the site's wake queue, through the scheduler role that may send to that queue and nothing else ([schedule trigger](design/always-on-agents-architecture.md)).
* **Name.** `follow-up-<digest of kind and record id>`. The reconciler for agent definitions only reads and deletes `agent-` entries, so it never touches a follow-up.
* **Key.** The record and the due time are in the key. The same time delivered twice is one message (the queue deduplicates by body, and the run record's own condition makes it one run); a new time is a different wake.
* **Message group.** The agent and the record, so two wakes about one record run one after the other and wakes about different records run at the same time.
* **Time.** A due time is a UTC instant written `2026-11-17T09:00:00Z`; anything else is refused before anything is written.

## Permission

`allowFollowUpTimers(lambda, brandId)` in `amplify/agents/schedule-group.ts` gives a site function the right to create, update and delete entries named `follow-up-*` in that site's group, and to hand the scheduler role to the scheduler service. It reads nothing, cannot touch the reconciler's `agent-*` entries, another site's group or the default group, and adds no resource (two statements on the function's own role). `scripts/test-agents-stack.ts` asserts all of that and prints the count. The first consumer, a Delivery's lock and release times (`announcements/delivery_timers.py`, PPY-e8ec54), calls `FollowUpTimers.sync` from `Deliveries` wherever it writes `dueAt`; the function that does so in a deployed site needs this permission, and none has it yet.

## Scheduled publishing

Scheduled publishing ([scheduled publishing](scheduled-publishing.md)) is the same mechanism with a different target: `story_schedule.EventBridgeScheduler` now makes and deletes its per-version entries through `OneShotSchedules`, the class the follow-ups use. Its entries are unchanged: the account's default group, `papyrus-pub-<site>-<digest>` names, the content-actions function as target, the dead-letter queue, and the claim on the Story's row that makes a late or duplicate event harmless. It does not move into the agent schedule group, because its target is a function, not the wake queue, and its permission is already written for the default group.

## What a live proof still needs

The fakes follow the Scheduler's documented behaviour; a deploy is needed to see the real service do it: a one-shot entry in the real group delivering to the real FIFO queue (the scheduler sets no deduplication id, so the queue deduplicates by body) and deleting itself, and the first consumer's function holding `allowFollowUpTimers`. Recorded on PPY-3ff011.
