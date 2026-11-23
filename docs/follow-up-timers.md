# Follow-up timers

A record that waits names the time it waits for: `dueAt`, with `waitingFor` (a Delivery already carries both). One helper turns that time into a timer, and a timer does one thing: it puts a wake on the site's wake queue. Nothing polls. This is slice C2 (PPY-3ff011) of [the always-on agents design](design/always-on-agents-architecture.md#35-timers-are-events); its spec is `features_backend/agents/follow-up-timers.feature`.

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

`allowFollowUpTimers(lambda, brandId)` in `amplify/agents/schedule-group.ts` gives a site function the right to create, update and delete entries named `follow-up-*` in that site's group, and to hand the scheduler role to the scheduler service. It reads nothing, cannot touch the reconciler's `agent-*` entries, another site's group or the default group, and adds no resource (two statements on the function's own role). `scripts/test-agents-stack.ts` asserts all of that and prints the count. The first consumer, a Delivery's lock and release times (`announcements/delivery_timers.py`, PPY-e8ec54), calls `FollowUpTimers.sync` from `Deliveries` wherever it writes `dueAt`. Two deployed writers hold the right: the image service (the announcements write door, `wireImageService` gives it `allowFollowUpTimers` on a dedicated site with a tenant) and the shared procedure runner, whose role in `infra/procedures/papyrus-procedure-runner.yaml` (`ContinuationTimers`, `PassSchedulerRole`) is the same grant written for every site's group by name pattern: create, update and delete `follow-up-*` entries in `papyrus-*-agent-schedules`, and pass `papyrus-*-agent-scheduler` to the scheduler alone. The second consumer, a soft review's deadline, is set by whoever raises the request with a deadline: in the runner that now works, because the runner gives each procedure the site (`PAPYRUS_AGENT_PUBLICATION_ID`, from the wake's publication) and its own account and partition (`PAPYRUS_AWS_ACCOUNT_ID`, `PAPYRUS_AWS_PARTITION`).

`follow_up_timers.site_follow_ups(environment, ...)` builds a site's timers and the base of the wake request from those variables, for both consumers (`DeliveryTimers.from_environment`, `ReviewDeadlineTimers.from_environment`). A Delivery's wake must name the tenant and bucket where the runner reads the site's agent policy, so `DeliveryTimers` requires them (`PAPYRUS_AGENT_TENANT_ID` or `PAPYRUS_TENANT_ID`, and `PAPYRUS_SITE_BUCKET`); the image service carries the tenant as `PAPYRUS_AGENT_TENANT_ID`, because `PAPYRUS_TENANT_ID` would make it read and write as that tenant.

## Soft review deadlines (PPY-9b8e59)

The second consumer. An open soft review with a deadline carries `dueAt` (its deadline, to the whole second); a flag, a hard gate and a closed request carry none. `review_requests.raise_review` calls `ReviewDeadlineTimers.sync` (`src/papyrus_content/review_deadline_timers.py`, owner `review-deadline`) after the row exists; an answer or a withdrawal clears `dueAt` and, when the caller holds the site's timers, deletes the entry. A caller without them (the console) leaves the entry: it fires once and the wake does nothing, because the request no longer waits for that time. At the deadline the wake starts the procedure `review_deadline`, which calls `review_requests.on_deadline_wake`: `check_wake`, then one write conditional on `state = open` and the same `dueAt`, recording "proceeded without review". Overdue (`overdue.py`) reads open soft reviews whose `dueAt` passed from the open partition of the review request state index and re-sends the same wake.

## The engine's own follow-ups

A follow-up the engine sets is not an agent's wake: no Automation governs it, so the run gate would skip it as `not_adopted`. `engine_follow_ups.ENGINE_FOLLOW_UPS` lists the owners the runner starts with no adopted agent, each with its one procedure: `review-deadline` -> `review_deadline` and `deliver` -> `deliver_due`. A wake is one of them only when its trigger is a follow-up, it names no automation, the owner in its key is on the list and its procedure is that owner's. The site's pause still stops it (the request keeps its due time and shows as Overdue); a per-agent pause and a rung do not apply.

## The scheduled send (PPY-e2829f)

A Delivery's wake (owner `deliver`) starts `deliver_due` (`announcements/deliver_due.py`). It reads the Delivery again (`check_wake`), raises the lock when the lock time has come (`delivery_lock.lock_at_time`: soft review is approved by the policy when nobody acted; hard review with no approval raises one flag and ends `asked`), then sends what is due through the announce agent's own deliver steps, with their guards (mode, account, pause, budget). The run's own writes move the timer: a lock before the release moves it to the release time; an attempt that opens clears it (nothing is pending), which is why the runner's role may delete entries. The wake's input is `deliveryId` and `dueAt`. How a site configures it (the `editWindows` setting and the announce review) is in [announcement records](announcement-records.md#the-scheduled-send-ppy-e2829f).

## Scheduled publishing

Scheduled publishing ([scheduled publishing](scheduled-publishing.md)) is the same mechanism with a different target: `story_schedule.EventBridgeScheduler` now makes and deletes its per-version entries through `OneShotSchedules`, the class the follow-ups use. Its entries are unchanged: the account's default group, `papyrus-pub-<site>-<digest>` names, the content-actions function as target, the dead-letter queue, and the claim on the Story's row that makes a late or duplicate event harmless. It does not move into the agent schedule group, because its target is a function, not the wake queue, and its permission is already written for the default group.

## What a live proof still needs

The fakes follow the Scheduler's documented behaviour; a deploy is needed to see the real service do it: a one-shot entry in the real group delivering to the real FIFO queue (the scheduler sets no deduplication id, so the queue deduplicates by body) and deleting itself, and the first consumer's function holding `allowFollowUpTimers`. Recorded on PPY-3ff011.
