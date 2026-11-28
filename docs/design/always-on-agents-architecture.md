# Always-on agents: one standard for every standing responsibility

Date: 2026-11-16. Owner: Ryan (product owner). Architecture and plan. No code was changed to write it.

Marks: **[V]** verified by reading code or the board; **[D]** read in a repository document, not re-checked in code; **[I]** my inference; **[P]** proposal.

Sources: Anthropic's "Building always-on agents" (read through a fetch tool that returns an outline, not the page word for word; I quote nothing from it); `docs/design/announcement-delivery-design.md` (section 13 especially); Papyrus at `origin/develop` `0fd146ba0` and the open branch `feature/announcement-delivery-records` (PR #1618); the Papyrus board (`kbs`); the memory notes named in the brief. What I could not verify is in section 14.

The official record is the Kanbus board. Every slice in section 12 is an issue whose text stands alone. This file is the companion. Slice codes such as A1 map to board ids in the appendix.

---

## 1. The one-page picture

**The problem.** Today only what Ryan drives forward in a coding session gets done. Translation, illustration, ideas, research, rating, announcements and upkeep happen when a session does them. When the session stops, they stop.

**The standard, in plain words.**

1. A **responsibility** is a standing duty: translate what needs translating, rate what is unrated, announce what qualifies. There is a short fixed list of them (section 2).
2. An **agent** is one responsibility on one site. It is one definition file in Git plus one line of site policy. The file says which procedure runs, what wakes it, and what it may do. The policy line says how far it may go on this site.
3. An agent is asleep almost all the time. Something **wakes** it: a record changed, or a timer came due. Every wake has a **key** that says exactly what it is about, so the same wake can never run twice.
4. A wake starts one short **run**. The run reads the records, does one piece of work, and ends with one of five **outcomes**: `acted`, `nothing`, `asked`, `failed`, `unknown`. That word is on the run record for ever.
5. How far an agent may go is a **rung** on one ladder, set per site and per responsibility: `off`, `observe`, `propose`, `draft`, `prepare`, `publish_soft`, `publish_auto`. Changing a rung is a settings change with a name and a reason. It is never a code change.
6. Agents **never chat** with each other. An agent changes a record. That change wakes the next agent. A question for a person is a review request. A request for another agent's work is an Assignment. A person's comment, answer, flag or pause goes into the same records.
7. Some rules hold on every rung (**hard floors**): a machine never gives five stars; nothing under three stars is shown or announced; doubt stops automatic publishing; spend stops at the budget.
8. A person stepping in is never needed for work the policy allows. A person stepping in is always possible: pause, change a rung, answer, redirect, undo.

```
 a record changes ─┐                                 ┌─> acted    (records changed; that wakes others)
                   ├─> wake (with a key) ─> one run ─┼─> nothing  (looked; nothing to do; says why)
 a timer comes due ┘      queue, one               ├─> asked    (review request; the answer is a wake)
                          worker per group           ├─> failed   (says why; nothing half-done)
                                                     └─> unknown  (started, no result; settled, never guessed)
```

**What changes for Ryan, day to day.**

- One page, **Today**, answers "what is the system doing today?": what is waiting for you, what is overdue, what ran, what it decided to do nothing about and why, what it cost.
- Each morning the work that policy allows has already happened. What policy does not allow is waiting as a short list of questions.
- To steer, change a record: answer a question, leave a comment, edit a draft, pause an agent, raise or lower a rung. No session is needed.
- A coding session becomes one more way to poke in. It is no longer the engine.

**What stays the same.**

- Stories, References, versions, stages, the checklist, review requests, guidelines, Caducus. The standard uses these records. It adds one queue per site, one policy document per site, a few fields and indexes, and no new store for agent state.
- Procedures stay Tactus files in Git. Skills stay skills.
- Human review is still never a Story stage. Messages still come only from people.
- Every site starts quiet. Nothing becomes more automatic until a person raises a rung.

**The five things to remember.** Wake, key, run, outcome, rung.

---

## 2. Responsibilities

### 2.1 The list

Each responsibility is filled in with the 11-point template from `docs/automated-processes.md` [D]. The table gives the lines that differ most. The full 11 lines for each live in its definition file (slice D1); a definition that cannot fill a line is refused.

| # | Responsibility | Trigger | Inputs | The decision | May write | Must never | Asks | Reversed by | "Nothing to do" |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Intake and capture** | Change: a Reference is created or its address changes | The page or PDF | Is the text captured; the summary; for papers, cited works | Capture card, extracted text and summary (S3), `captureState` | Change curation status; overwrite text a person pasted; create a second Reference for a document the site holds | Nobody; a final capture failure shows on the card | A person corrects or pastes; `--force` redoes | Reference already captured for this text |
| 2 | **Rate and curate** | Change: Story published, Reference accepted. Timer: daily | Unrated items, the site's rating policy | Three stars (default), four (clearly better), or "five-star candidate" | A machine rating of 3 or 4, or a suggestion | Write a five; change a person's rating; accept or reject at a rung that does not allow it | A person, for five-star candidates (one grouped request a day) | A person's rating replaces it | Nothing unrated |
| 3 | **Ideate** | Timer: daily per site; weekly trends | Accepted References with no idea yet, context packs | Is there a story here that adds something the source does not | Items at `idea`, based-on links, one soft review per pass | Publish; draft one Reference twice; file an idea that only restates its source | Editors, to pick | An editor spikes with a reason | No accepted References without an idea, or none passed the point check |
| 4 | **Select and assign** | Change: an idea is filed; timer: daily news meeting | Ideas, the section's mission, recent Stories | Which ideas are worth a Story | Stage move `idea` to `assignment`, a research Assignment | Select more than site policy allows; select against the mission | Editors, at low rungs | An editor moves it back or spikes it | No idea meets the bar |
| 5 | **Research** | Change: a research Assignment is created or reopened | The Assignment, search, the knowledge base | What sources and facts the Story needs | A research packet, proposed References (pending), Assignment events | Retry a failed run by itself; register a source the site already holds | The asker, through the Assignment | Reopen or cancel the Assignment | (Always has work when woken) |
| 6 | **Write and copy-edit (improve)** | Change: a checklist step becomes ready; a person's request; a new event that fits an article | The draft, guidelines, the context pack | What to change to meet the guidelines and the thesis | A new draft version with a reason; step evidence | Publish at a rung that does not allow it; overwrite a block a person pinned; walk the archive on a timer | A person, on doubt | Revert to the earlier version | The current version already passed this step |
| 7 | **Fact-check** | Change: the step is ready, after the quiet window | Claims, stored copies of cited sources | Verified, needs check, rejected, unchecked per claim | Verdicts and evidence on the step | Let a judge override a literal failure; count unchecked as verified | A person, by hard gate, on any contradicted claim | A person overrules with a reason | No claim changed since the last check |
| 8 | **Illustrate** | Change: the Illustration step is ready; an illustration Assignment | The Story, the image style profile | Which picture explains or leads | Image candidates, the placed image, alt text | Place a third-party image without credit; add a credit to a generated image; write "Approved by" | A person, to choose, at `prepare` | Choose another candidate; remove | The step is closed or not applicable |
| 9 | **Translate** | Change: a Story is published or its source blocks change | The source version, glossary, earlier corrections | The translation of each changed block | A translation version; `held` with a reason | Overwrite a block a person corrected; publish past a quotation hold | A person, by flag, on a hold | Revert; a person's correction is pinned | Every language is current |
| 10 | **Announce** | Change: a Story's page is live, or its rating changed | The Story, channel rules, channel guidelines, what the account already said | Does it qualify on each channel; the words for each | Announcement and Delivery records, text versions (S3) | Announce under three stars or unrated; supply the five; release under `prepare`; change a pinned block | A person, per the rung | Withdraw; correct (a superseding Delivery) | Qualifies on no channel (no row written) |
| 11 | **Newsletter and summaries** | Timer: the list's schedule; change: items qualify during the period | Qualifying items since the last sent issue | Which items fill the slots, in what order, with what blurbs | The issue's working document, the Announcement and its email Delivery | Re-add an item a person removed; send an empty issue; enrol a reader | A person, per the rung | Before send: cancel. After: a correction notice | No qualifying items and nothing a person wrote |
| 12 | **Learn from edits** | Change: a Delivery with a person's changes is sent | The machine draft, what was sent, the scope and reason | Is there a rule worth proposing | A proposal to change a guideline file | Change a guideline; propose from one unexplained edit | An admin, to accept or reject | Retire the rule; turn an example off | No scope given, or no pattern |
| 13 | **Relevance and acceptance** | Change: a decision is ready; timer: the learned delay | Cyclotron confidence, people's votes | Accept a pending Reference at the learned threshold | `curationStatus=accepted` with the numbers | Touch a Reference a person decided; count its own acceptance as a vote | Nobody | A person rejects; that trains | No confidence reaches the target |
| 14 | **Concepts and knowledge** | Timer: weekly knowledge run; change: a Reference's text is stored | Accepted References, the previous run | Topics, entities, suggested links, wiki pages to change | New concepts (create only), suggestions, wiki pages | Change an existing concept; revive a rejected one; reach projection after a failed stage | Editors, for suggestions | Entity undo commands; a person's edit always wins | The run's output matches the site's history |
| 15 | **Operations hygiene** | Timer: daily | Due indexes, dead-letter queues, deploy job logs, the spend ledger | What is overdue, stuck or broken | Flags; re-sent wakes with their original keys | Retry a deploy; purge a cache; touch AWS resources; do another agent's work | Admins | Acknowledge the flag | Everything is clean |
| 16 | **Monitoring collection** | Timer: per monitor | One source per monitor | Which items are new | Rows in the monitoring table only | Deliver to a publication, curate or train | Nobody | Nothing to reverse | The source has nothing new |

Rows 13, 14 and 16 exist today and work [D]. They join the standard for their records and outcomes; their engines (the router, the Cyclotron, the knowledge run's container) are not rewritten.

### 2.2 The template lines shared by every agent

These are the same for all, so the definition file inherits them:

- **Records.** One run record per wake, with the outcome, the reason, the policy version, the versions read and written, the operations asked for and the gate's answers, and the cost.
- **Fails.** Closed. A failed run leaves nothing that looks done. An interrupted run is `unknown` until settled.
- **Cost and bound.** Bounded by real things only: the runner's 15 minutes, the model provider's rate limit, the site's budget. No counts.
- **Measured.** How often people kept, changed or rejected its work (slice E6).
- **Seen.** On Today, on the subject's own page, and in the agent's run history.

---

## 3. The standard agent

### 3.1 What an agent definition is

One file in Git per agent (slice D1). It names:

| Part | Meaning |
|---|---|
| `responsibility` | One from the catalog in section 2. |
| `procedure` | The Tactus procedure's key. The procedure and the skills it names are registered by the release. |
| `wakes` | Changes it listens for (record kind, kind of change, a filter) and an optional schedule (cron and time zone). |
| `serialBy` | What runs one at a time: `subject`, `agent`, or a named key such as a channel account. |
| `paid`, `safeToRepeat` | Whether it calls a paid model (so it waits for quiet and counts against the budget); whether every write it makes is keyed, so running it twice is harmless. |
| `operations` | Each operation it uses and the lowest rung that allows it. |
| `tier` | `editorial`, `work`, `bulk` or `decision`. Never a model name. |
| `executor` | `lambda` (default) or `container` (the knowledge run only). |
| The 11 template lines | Trigger, inputs, decision, may write, must never, seen and reversed, records, fails, cost and bound, measured, Gherkin. |

The existing `Automation` record [V: `amplify/data/schema.ts:1532`] stays. It becomes the registered copy of a definition in a site: id, definition version, digest. What a person changes (rung, pause, budget, model, quiet window) lives in the **agent policy document** (section 5), not on this record. So a deploy can never change a rung, and a rung change never needs a deploy.

### 3.2 The wake-up contract

**In:** one wake: `{key, agent, subject, why}`.

**During:** the runner creates the run record from the key, with a condition, as `started`, before any procedure code loads. It loads the standard context (section 3.8), runs the procedure, and every write goes through the gate (section 5).

**Out:** exactly one outcome.

| Outcome | Shown as | Meaning | What happens next |
|---|---|---|---|
| `acted` | ✓ Did it | It changed records. | Those changes wake whoever listens. |
| `nothing` | – Nothing to do | It looked and nothing needed doing. A reason code says why. | Nothing. Counted on Today. |
| `asked` | ? Asked | It needs a person. A review request exists. | The answer is a wake for this agent. |
| `failed` | ✗ Failed | It could not do the work. Nothing is left half-done as if done. | One flag. A person or a later change wakes it again. |
| `unknown` | ! Outcome unknown | It started and no result was recorded. | Settled (below). Never guessed. |

The article's three endings are send, send nothing, and ask. I add `failed` and `unknown` because they are real and must be visible. I use `acted` and not `sent` because most agent work is not a send; a Delivery attempt keeps `sent`, `refused` and `unknown` for the same ideas (slice A1).

### 3.3 Keys: nothing runs twice

| Wake | Key |
|---|---|
| A record changed | `<agent>|<subject id>|<subject version>|<what>` |
| A schedule tick | `<agent>|schedule|<scheduled time>` |
| A follow-up time on a record | `<agent>|<record id>|due|<due time>` |
| A person's Run now | `<agent>|manual|<request id>` |
| A continuation | the original key plus `|c<n>` |

The run record's id is made from the key and created with a condition (slice A2). A second delivery of the same wake finds the record and starts nothing. Today run ids are random [V: `procedure-action/handler.ts:247`] and the once-only claims live in the monitoring table as `TRIGGER#`, `STAGE#` and `MANUAL#` rows [V]; those rows are borrowed plumbing and go away (slice B6).

Every write an agent makes is keyed too: an Announcement by its once-only key, a Delivery by its generation, a version by the version it replaces, a review request by subject and reason. That is what makes a repeat harmless.

### 3.4 The one runtime

**One contract, one queue, one runner.**

- Each site has one FIFO queue, `agent-wakes` (slice B1). A wake is a message. The **message group** is the agent plus its `serialBy` value. The deduplication id is the wake key.
- The procedure runner Lambda **consumes the queue**. It holds the message for the whole run. If the run dies, the queue delivers the message again. Today every caller invokes the runner directly and asynchronously with no retries [V: `InvocationType="Event"`, `MaximumRetryAttempts: 0`], so a lost invocation is a lost run.
- **One worker per responsibility and scope** comes from the queue: a FIFO queue gives one message of a group to one consumer at a time [I: standard SQS FIFO behaviour]. Two changes to one Story run in order. Changes to two Stories run together. This replaces `maxConcurrent`, the count of rows in flight, the 120-second grace and the deferred-retry sweep [V: `automation_gate.py`, `monitoring_router.py:2316`] (slice B4).
- **How many at once in total** is the queue mapping's maximum concurrency, set from the model provider's rate limit. That is a real constraint.
- The container executor remains for the weekly knowledge run only, started from the same kind of wake and recorded the same way (slice M9). It is compute, not an agent conversation.
- A local pod is not part of this design. Pods deliver in manual mode and have no unattended agents (decided in the announcement design).

**Long work is cut into short runs.**

1. Cut by record first: one Story, one step, one language, one candidate. A big job is a planner run that puts many small wakes on the queue. Monitor stories already work this way [D: the daily run only plans; a queue drafts one candidate per message].
2. If one unit still does not fit in a run, the procedure saves progress on the records it is changing and ends `acted` with a next-wake time. The next run re-reads and continues (slice A6). Progress never lives in a model transcript.
3. A run that neither finishes nor saves progress is `failed`. Today that is recorded only as "timed out" [V: `procedure_runner.py`].

**An interrupted run is settled, not guessed** (slice A3). The queue delivers a message at most twice by design: once to run, once to settle. On the second delivery the runner reads the run record. `started` with no outcome means the first attempt died. If the definition says `safeToRepeat`, it runs once more under the same key. If not, it records `unknown`, raises one flag, and stops. A third delivery can only mean settling itself crashed; that reaches the dead-letter queue and its alarm. No timeout and no retry count decides anything.

### 3.5 Timers are events

A timer does one thing: it puts a wake on the queue. The run re-reads the records and re-checks everything. The newsletter's start-send already works this way [D].

- **Schedules** (slice C1). A definition may carry a cron expression and a time zone. A reconciler keeps one EventBridge Scheduler entry per scheduled agent, named from the agent id, in the site's schedule group. Its target is the site's wake queue. The scheduled time is in the message and becomes the key. The `schedule` trigger kind is stored today and starts nothing [V: `automations.py:40`, `ACTIVE_KINDS = {"monitor"}`].
- **Follow-ups** (slice C2). Every wait is a named time on the record that waits: `dueAt` with `waitingFor`. One helper turns it into a one-shot schedule entry that deletes itself. Setting a new time replaces the entry. Scheduled publishing already creates per-Story entries this way [V: `story_schedule.py:186`]; both use the one helper.
- **Nothing polls.** The research worker's five-minute poll, the router's deferred sweep and the "checked on read" review deadline [V: `review_requests.py:238`] are each replaced by a wake.
- **Created by the pipeline.** The schedule group, the role the scheduler assumes and the reconciler are in the template. The entries are data, written by product code under that role, exactly as per-Story publish entries are today. No person creates a schedule.
- **Time zones.** The scheduler's own time zone support handles clock changes. Period keys use the local scheduled date (slice N3).

### 3.6 Concurrency, waiting and deadlines

- **Waiting is a state with a reason and a time**: `waiting` with `waitingFor` (`quiet window`, `budget cycle`, `release`, `rate limit`, `quiet hours`, `an answer`) and `dueAt`. It is never a sleep and never a held lock.
- **Quiet window** (slice B5). A burst of edits must not start ten paid runs. A paid step sets or replaces one follow-up timer for its subject. The window is site data: 30 minutes to 24 hours, about 5 minutes after a person's own action (Ryan, 2026-11-06). Free checks run at once.
- **Deadlines.** A soft review's deadline is a follow-up timer (slice C3). A Delivery's lock and release times are follow-up timers. A hard gate has no deadline, ever.
- **Overdue** (slice C4). Anything whose due time passed with no run is Overdue: shown on Today, re-woken once with its original key, and flagged once.

### 3.7 Spend is the real limit

- One ledger counts spend per site and budget cycle, by responsibility (slice G1), generalised from `AnnouncementSpend` [V].
- At the budget, paid wakes wait for the next cycle and one flag is raised. Free work, reading, editing and serving continue (slice G2). This is Ryan's ruling for the multi-tenant service (D19, 2026-11-13) applied to every site.
- An unusually costly run or Story raises a flag and is never stopped; "unusual" is learned from that agent's own history (slice G3).
- There are no per-day counts, item caps or run caps anywhere in the standard.

### 3.8 What a run loads (memory)

One loader gives every run (slice D4):

1. The **section context pack** that already exists: recent Stories, top-rated accepted References, core concepts.
2. The **guidelines** that apply: writing, image, channel.
3. The site's **instructions** for this responsibility, added on top of the engine's fixed base and never replacing it (Ryan, 2026-11-08).
4. For work aimed at an audience, **what was already said**: the account's recent Deliveries, the open questions on the subject.

Everything else the agent looks up. The run record names every version and hash it loaded.

### 3.9 Pause and resume

- Pause one agent, or every agent on a site, with a reason (slices E1, J2). The runner checks at the start of each run.
- A paused agent's schedule tick is consumed and recorded: nothing started, reason "paused by <who>".
- Resume does not replay skipped ticks. Records that are still waiting keep their due times and run when due. Change wakes that arrived during a pause are not lost: the work they point at is still visible in the records, and the next wake for that subject re-checks it. [I: for agents woken only by changes, resume issues one wake per subject that changed during the pause, read from the subject index, not from a table walk.]
- Built (slices H3 in part and J2, PPY-e6f31e and PPY-3f68f4; `agent_poke_in.py`): `agents_pause`, `agents_resume`, `agents_pauses` and `agents_wake` are rows of the one operation table, run by `papyrus agents pause|resume|pauses|wake` and by the Automation page. A pause keeps when it began and who made it (`pausedAt`, `pausedBy`). Every run record of an agent's change wake keeps the wake (`wake`, `procedure_runner.kept_wake`), whatever came of it. Resume reads, for each agent the pause is lifted from that listens for changes, its runs from `pausedAt` on through the run index by automation and request time (not the subject index the line above names: the stopped wake is the exact change the agent missed, and it is found the same way for every kind of subject), and sends once each subject's latest wake the pause stopped, keyed by the stopped wake and the resume's policy version. A schedule tick keeps no wake and is never sent again. A pause or resume goes through the agent-policy function (an admin signed in to the console); wake now through the Automation page's function (`agentWake`, editors and admins). Specs: `poke-in.feature`, `kill-switches.feature`.
- Built (PPY-97180c; `overdue.wake_now`): `agents_wake_overdue` (`papyrus agents wake-overdue`, Today's Wake now beside an Overdue record) is the per-record form of `overdue.recover` for what the engine's follow-up timers wake (a Delivery, a soft review's deadline), which `agents_wake` cannot reach. The record is read by id and must be Overdue; its timer's own request is sent again with the same key, its trigger naming who and why, through the Automation page's function (`agentWake` with the operation's name). Spec: `overdue-wake-now.feature`.

---

## 4. How agents talk to each other over time

### 4.1 The answer: durable records, not chat

An agent's output is a record change. The change feed turns it into the next agent's wake. Nothing else carries meaning between agents.

There are exactly three kinds of work item, and all three exist today:

| Record | Who it is for | Example | Exists |
|---|---|---|---|
| **Checklist step** (an Item of type `sub-task` under the Story) | The agent that owns that step | "Fact check: open" | [V] `story_checklist.py` |
| **Assignment** | Another responsibility, asked for one piece of work | "Find a source for this claim"; "Draw a figure for section 3" | [V] `Assignment` with claim, release, complete, cancel, reopen and events |
| **Review request** (flag, soft review, hard gate) | A person | "Publish?"; "This quotation is held" | [V] `ReviewRequest` |

Everything else is state on the subject itself: the stage, the version, the rating, a translation's state, a Delivery's state.

### 4.2 How one agent's output becomes another's event

```
copy editor saves version 12 of a Story
   └─ Item table stream ─> change feed ─> {item, <lineage>, v12, version_created, by agent}
        ├─ wake: sources check   key  sources|<lineage>|12|step        (free: runs at once)
        ├─ wake: fact check      key  fact_check|<lineage>|step        (paid: waits for quiet)
        └─ no wake for the copy editor itself (its own version, same step)
```

The change feed (PPY-8a374e, slices B3) is one small function per table. It reads which agents listen from the site's cached definitions, by index. Stream records are not AppSync requests, so this costs almost nothing. Today a console board move fires nothing [V: `content-actions/handler.py:1000` does not call the trigger code] and each delivery lists the whole Automation table [V: `story_triggers.py:101`].

### 4.3 Claiming and releasing responsibility

- **Who owns a step** is configuration: the Story procedure profile binds each step to a responsibility.
- **A claim is the run record.** Creating it from the wake key is the claim. Finishing it is the release. There is no lease to expire and no lock to steal.
- **Hand back** (slice F2): an agent reopens an earlier step with a reason. That change wakes the step's agent with the reason as input.
- **Hand on** (slice F1): an agent creates an Assignment for another responsibility. Its completion wakes the asker.
- **A person takes over** (slice F2): they assign the step to themselves. Agents stand down on that step until it is released or closed.

### 4.4 How agents see what was already done or said

Memory is the records:

- Done: the step's status, evidence and actor; the version history; the run history by subject.
- Said to people in the newsroom: review requests by subject. An agent asks once per subject and reason (slice F5).
- Said to readers: the account's sent Deliveries, newest first, by index.
- Decided by people: ratings, votes, answers, pins, removals, the scope of an edit.

Nothing an agent needs to remember lives only in a transcript.

### 4.5 How a person's message or flag enters the same channel

- **An answer** to a review request is a change that wakes the agent that asked (slice F4). The request's `appliedIn` names the run that used it [V: the field exists].
- **A comment** on a Story, Reference or Delivery is a Message from a person. The Message change feed wakes that subject's agents with the comment as steering (slice F3).
- **A flag** a person raises is a review request with a person as the raiser.
- **A redirect** from the Today page or the CLI is an instruction recorded on the subject; it reaches the next run as steering (slice H3).

### 4.6 Conversations (Message and MessageThread)

Messages come only from people [V: `AGENTS.md`, epic PPY-781d26]. So:

- A thread is where people talk about a subject. Agents read it. Agents do not write to it.
- An agent's reply is what it did. The thread shows a **run card** ("the copy editor made version 13: tightened the lede") read from the run record by subject. It is displayed, not stored as a Message.
- The Message's response fields (`responseTarget`, `responseStatus`, `responseOwner`) [V] record that an agent picked it up and which run.

### 4.7 Is a mailbox object needed? No

A mailbox would be a second copy of the truth. A message saying "please translate this" can disagree with the Story's real state. It needs its own read-tracking, its own retries and its own clean-up, and a lost message is lost work. With records as the mailbox, "what needs doing" is always a question about current state, so a lost wake loses nothing: the next wake, or the overdue check, finds the same work. That is what makes the system eventually consistent.

The one thing that looks like an inbox is the wake queue. It carries no meaning of its own: a wake only says "look at this record now".

---

## 5. Authorization as configuration

### 5.1 The ladder

| Rung | The agent may | Typical use |
|---|---|---|
| `off` | Nothing. It is not woken. | A responsibility the site does not want. |
| `observe` | Read, and record what it would have done. Writes nothing else. | Every new agent starts here. This is the dry run (slice J4). |
| `propose` | File suggestions beside records: proposed ratings, idea recommendations, candidate links. Changes no content. | Building trust. |
| `draft` | Write drafts and candidates that nobody outside the newsroom sees: draft versions, Delivery drafts, image candidates, translation drafts. | Normal working level for writing work. |
| `prepare` | Take work to the door and stop: close steps, move stages up to the last one, then raise a hard gate for a person. | "A person approves first." |
| `publish_soft` | Go through the door unless a person stops it in time, or publish and then ask for a read. | "Publish, then review." |
| `publish_auto` | Go through the door. No request. It appears in the digest. | Fully automatic sites. |

Each responsibility says what each rung means for it, in its definition. Some examples:

| Responsibility | `propose` | `draft` | `prepare` | `publish_soft` | `publish_auto` |
|---|---|---|---|---|---|
| Rate | Suggest stars | (same as propose: a machine never writes a rating) | (same) | (same) | (same; a rating is a person's alone) |
| Ideate | Recommend | File ideas | (same) | (same) | (same) |
| Write and improve | Suggest edits | Save draft versions | Ready to publish; hard gate | Publish, then soft review | Publish |
| Translate | — | Translation drafts | Ready; a person publishes | Publish unless held | Publish unless held |
| Announce | — | Draft Deliveries | A person releases (`hard`) | Silence releases at the lock time (`soft`) | Released by policy (`none`) |
| Accept References | Suggest | — | — | — | Accept at the learned threshold |

### 5.2 Where it is stored and how it is changed

One **agent policy document** per site (slice E1): a `SiteDocument` of kind `agents` [V: `SiteDocument` and `SiteDocumentVersion` exist, body in S3, admin scoped]. No new table.

```
rate:        { rung: propose }
ideate:      { rung: draft }
improve:     { rung: prepare, overrides: [ { storyType: post, rung: publish_soft } ] }
translate:   { rung: publish_soft }
announce:    { rung: publish_soft,
               overrides: [ { channel: linkedin, rung: prepare },
                            { kind: roundup,     rung: prepare } ] }
site:        { paused: false, quietWindow: ..., budget: ..., tiers: { editorial: ..., work: ..., bulk: ... } }
```

- Overrides narrow by section, Story type, channel, Announcement kind or list. The narrowest wins.
- Every change is a new version with who, when and why. Only an admin may change it. An agent is blocked from it at every rung.
- Each run records the policy version and rung it ran under, so "sent automatically by site policy, version 14" is a fact on the record.
- Built (slice E1, PPY-51ea61) in `src/papyrus_content/agent_policy/`: an unnamed responsibility is `off`; the narrowest matching override decides, ranked by the dimensions it names in the order list, kind, channel, story type, section (a kind override beats a channel override, PPY-97c0f2); a pause (site or agent) carries its reason in the document; `decide_start` answers start or skip and returns the `policyVersion` and `rung` the run record carries. Hard floors (E4) are a separate slice. The runner reads it before every run (PPY-c8175e, `agent_policy/run_gate.py`): an automation is enforced only once a person has adopted it onto a responsibility (`papyrus automations adopt`) and the policy raises that responsibility above `off`; otherwise the run is recorded as `nothing` with the reason `not_adopted`, `rung_off` or `paused`, and every run names the `policyVersion` and `rung` it was decided under.
- Built (slice E2, PPY-611397) in `src/papyrus_content/agent_gate/`: each `Operation` in `images/operations.py` has `agent_rung` (the lowest rung that lets an agent call it, or `person`) and `agent_refusal` (`human_required` or `blocked` when no rung does). `decide` answers `allowed`, `blocked` (the table says never, or the agent is off or paused, or the operation is unknown) or `human_required` (the policy's rung for this call is below the table's). A person is always `allowed`. `GateRun` holds the policy read once for a run, keeps every answer for the run record, and the one review request and `asked` outcome that `human_required` raises. A caller that carries a `GateRun` is answered by it in `images.handlers.execute`; making that the only path is slice E3.
- Built (slice L1, PPY-d85860): the first agent, `rate`, runs the procedure `rate_items` (`src/papyrus_content/rating_agent.py`) on its daily schedule. It reads the published Stories nobody has rated from the head stage index, newest first, until the index ends or the run's deadline is near; asks the bulk-tier model for three, four or five; lists a five as a candidate for a person and never as a rating; and asks the one gate about `ratings_set` (rung `draft`) before it writes anything. At `observe` it writes nothing and files no review request; at `draft` the same run writes the threes and fours. The runner hands the procedure the run's policy in `PAPYRUS_AGENT_RUN` (`agent_gate/run_context.py`). Accepted References are not read: no index lists the ones without stars. Steps to take it live: [releasing](../releasing.md#the-first-agent-rating-on-machines-on-machines-ppy-d85860).
- Built (slice L2, PPY-e61642): suggestions only. A machine never writes a rating: `ratings_set` is a person's operation and refuses an agent at every rung. At `propose` the agent calls `ratings_suggest` and writes `starSuggestion` (3, 4, or 5 for a five-star candidate), `starSuggestedBy`, `starSuggestedAt` and `starSuggestionRun` beside the rating on the Story's working record (`rating_suggestions.py`; private, carried to new versions, never published), skips a Story somebody rated or one with a suggestion waiting, and raises the day's one soft review with `ratings_suggestions_review` (`rr-ratings-<day>`, "N ratings suggested, M five-star candidates", a link per Story carrying its title, suggested stars, five-star flag and the agent's one-line reason; a later run that day adds to it). A person confirms in the Story editor ("Use 4 stars"), with `papyrus ratings confirm`, or row by row in the review itself (PPY-5d3abd: the Notification Center lists each Story with "Use N stars", other stars and "Leave it"; a rating goes through `setItemStars` as that person, the row records the choice, and the review is answered when every row is or when the person dismisses it; it offers no generic Accept or Reject). Confirming makes it that person's rating; other stars replace it; ignoring leaves it pending. `papyrus reviews show` lists the rows and `papyrus stories show` prints a pending suggestion.
- Changed in the newsroom (the Agents page) or with `papyrus agents set-rung` (slice H3). Built (slice H3 in part, PPY-e6f31e): `papyrus agents set-rung --id --rung --reason [--scope] [--apply]` in `agent_policy/set_rung.py`, over the site store with a GraphQL-backed catalogue (`agent_policy/catalogue.py`). Admin who is a person only; a dry run unless `--apply`, printing the entry before and after; each apply is a new version. It refuses an unknown rung, a rung above the highest one the agent's definition needs, and `publish_auto` until the hard-floor gate (E4) exists (`agent_policy/floors.py`). Pause, resume and wake now are built (section 3.9); redirect and undo are still to do.

### 5.3 Starting quiet and being promoted

1. A new agent arrives at `off` (slice D2). A new site's policy sets each to `off` or `observe`.
2. At `observe` its runs list what it would have done. A person reads them.
3. At `propose` and `draft` every item it produces is kept, changed or rejected by people. That is evidence.
4. The Agents page shows the evidence with its interval and may say "ready to promote" when the lower bound meets the site's target, the way automatic acceptance learns its threshold [D]. The system never promotes (slice E6).
5. A person raises the rung, with a reason. Demotion is the same operation and takes effect at the next wake.

### 5.4 One gate

Each operation in the operation table carries, for an agent, the lowest rung that allows it (slice E2). One gate on the server answers every call:

- `allowed`: it happens.
- `blocked`: never for an agent (change policy, budget, account; unpin a person's block; set five stars).
- `human_required`: a person must do it or approve it. The engine raises the review request and the run ends `asked`.

`human_required` is already what guidelines answer to an agent [D]. The runner's role is narrowed so it can reach writes only through the gate (slice E3); today it may call every Query and Mutation field of a site's API [D: `docs/automations.md`, "Deployment needs"].

A person's own action is never limited by an agent's rung. An agent using Ryan's signed-in session in a coding session acts as Ryan (Ryan, 2026-11-05); that is a person's session, not an always-on agent. An always-on agent runs as itself and is a machine for every floor.

### 5.5 Hard floors, under every setting

| Floor | Where it is enforced |
|---|---|
| Default rating is three; a machine writes three or four; a five needs a person. Machines list five-star candidates. | The gate refuses a five from any agent (slices E4, L3). |
| Nothing under three stars, unrated or only predicted, on any public page or notification. Concept pages are the stated exception. | Channel and list rules cannot be set under three (slice N1); announce eligibility. |
| No "Approved by" credit on any image. Generated images carry no credit. Third-party images are always credited. | The gate on image operations. |
| Spend stops at the budget. | The gate before a paid run (slice G2). |
| A quotation hold or a translation hold stops that item. | The existing holds [V: `localize/record.py:378` raises the flag]. |
| Doubt stops automatic publishing, even on a fully automatic site: an error-level finding a bot cannot fix, a contradicted claim, a legal-screen hit, the loop limit. | The gate turns `publish_*` into a hard gate (slice E4). |
| A machine never changes an existing concept, never resets a Reference a person decided, never overwrites a pinned block. | Existing guards [D], restated in the gate. |
| Messages come only from people. | No operation lets an agent write a Message. |
| Machines never release under `prepare`; never change policy, budget or accounts. | `blocked` or `human_required`. |

Slice E4 is one spec suite that runs every floor against the top rung.

### 5.6 How this meets the announcement review policy

The announcement design's `announcementReview` (`none`, `soft`, `hard`) is the announce responsibility's rung:

| `announcementReview` | Rung | On each Delivery |
|---|---|---|
| `hard` | `prepare` | `approval: hard` |
| `soft` | `publish_soft` | `approval: soft` |
| `none` | `publish_auto` | `approval: none` |

- Its overrides (publication, then channel, then kind) are the ladder's overrides. I add **list** as the narrowest scope, for newsletters.
- The value chosen is written on each Delivery as `approval` with `approvalPolicy` saying where it came from [V: built that way in PR #1618].
- `requireReviewedSource` is **not** a rung. It is an input rule: no Announcement for a Story no person has reviewed ("reviewed" means the human review stamp of section 6.4.1: the lineage's review step done on its current version by a person, or by an agent on a person's recorded instruction). It stays a separate setting, on the list or channel rule.
- So PPY-97c0f2 is built as the ladder's first client, not as a setting of its own. One page shows how automatic everything is.

The other switches that say "how automatic" also become rungs (slice E5): the publish gate [V: `publish_gate.py`], `autoAccept` in the router config [V: on by default], and `languages.auto`. `publishRequiresRating` stays a floor.

---

## 6. Lifecycles that run themselves

For each record type: the stages, who moves each, where a person is needed by policy, and what happens when nobody acts. The shared rules come first.

**Shared rules.**

- **Re-check on every wake.** A run never trusts the wake. It reads the record and decides from what is true now.
- **No whole-table reads.** Find work by index: stage indexes, parent-and-order, due indexes, by account, by subject.
- **Compute once on change.** Derived work runs when its input changes. Nothing walks a corpus on a timer.
- **Coalesce in windows.** Paid work waits for quiet.
- **Never silent.** A record that is due and untouched is Overdue: on Today, flagged once.
- **A person is never a stage.** Where a person is wanted there is a review request.

### 6.1 Story

Stages [V: `content_item_lifecycle.py`]: `idea`, `assignment`, `reporting`, `copywriting`, `illustration`, `typesetting`, `published`; also `held`, `spiked`, `retired`.

| Move | Moved by | A person by policy? | Nobody acts |
|---|---|---|---|
| (filed) to `idea` | Ideate | No | — |
| `idea` to `assignment` | Select and assign, or an editor | At `propose` and below, yes | The idea stays; counted on Today; never spiked for age |
| `assignment` to `reporting` | Research completes its Assignment | No | A failed Assignment is flagged once and waits |
| `reporting` to `copywriting` | Write (outline, then draft) | No | — |
| Steps inside `copywriting`: sources, proofread, fact check, headline, rated | Each step's agent; the engine moves the stage when every required step is closed | Doubt raises a hard gate | An open step with no run is Overdue |
| `copywriting` to `illustration` to `typesetting` | Illustrate; typeset | At `prepare`, a person chooses the picture | — |
| `typesetting` to `published` | The engine, when the checklist is closed and the rung allows | `prepare`: hard gate. `publish_soft`: publishes, then a soft review with no expiry. `publish_auto`: publishes. | At `prepare` it waits, shown under "Waiting for you". It never publishes by itself. |
| After `published`: improve, translate, rate, announce | Their agents, from the publish change | Per rung | Each shows on Today if due and untouched |

This is epic PPY-959e41. Its step runner (PPY-8a374e) is the standard's change feed for Items; I re-use that issue and do not file a second.

### 6.2 Reference

| Stage | Moved by | Person? | Nobody acts |
|---|---|---|---|
| Collected | Monitoring collection | No | — |
| Delivered (pending) | The router | No | — |
| Captured, summarised | Intake and capture | Only to paste text a machine could not read | Transient failure: one retry at its due time. Final failure: `capture_failed`, visible, waits |
| Predicted | The Cyclotron | No | An outage leaves it undecided; re-posted once |
| Accepted or rejected | A person, or the acceptance agent at `publish_auto` | Below that rung, yes | Stays pending. Pending is not an error. Counted on Today |
| Rated | Rate | A five, always | Unrated accepted References show as a count |
| Grouped (same document, same story) | Concepts and knowledge; epic PPY-24fdf4 | Merges are confirmed by a person | Suggestions wait |

### 6.3 Idea

An idea is an Item at `idea` [D]. Generated by Ideate. Selected by a person or the selecting agent. Spiked only with a reason, by a person or by an agent whose rung allows it. Spiking is viable (Ryan, 2026-11-09) and is recorded. An unselected idea stays.

### 6.4 Translation

Per published Story and language: `wanted`, `translating`, `held`, `ready`, `published`, `stale`.

- A publish wants one translation per configured language.
- A source edit marks only the changed blocks stale and wakes the translator for those.
- A block a person corrected is pinned and never overwritten.
- A hold flags once and blocks only that translation.
- Whole-site translation is many wakes, one per Story and language (slice M4). Today the CLI path runs for up to an hour in one process [V: `localize/start.py:17`].

#### 6.4.1 The per-language checklist, the review stamp and the translation agent (PPY-473f8f, PPY-97c0f2, PPY-98f88e)

One design, three parts, built in this order. Each is checked against the states above.

**Per-language checklist.** Every language lineage (`{story}--{language}`) has its own checklist rows, written by the same code as a Story's (`story_checklist.py`). A translation's template is: `translate`, `faithfulness`, `copy_edit`, `human_review` (required only where the site's procedure requires it), and `publish`. Rating and the cover are served by the original (decision 10 of the translation plan) and are not rows of the translation. Publish checks the checklist of the lineage being published, at that lineage's current version, with the same open-step refusal a Story gets. An imported or pod-loaded Story keeps its not-applicable rows only for steps that genuinely do not apply; `human_review` stays open for it, so a person must tick it. This replaces the interim `publish_by_person.py` block, which is deleted with its one call in `publish_item` and the `by_person` argument when this gate is verified.

**Review stamp and delegation.** The stamp is the `review_people` step (for a translation, `human_review`) marked done against that language version's current version; an edit afterwards drops it. It is set the same way from the CLI, the API and the web UI, through one operation. It records who set it (`actor`) and, for an agent, the person it acts for (`onBehalfOf`). It counts when a person set it, or when an agent set it under a recorded, revocable delegation that names the person and the sites or steps it covers. An agent with no delegation is refused with a typed reason (`delegation-required`) saying how a person grants one. A delegation is a record (person, agent, sites, steps, granted at, revoked at); revoking it stops the stamp counting for later reads, and a stamp set under a delegation shows as delegated, naming the person, in the checklist. The PROVISIONAL labels are removed.

*Built (PR 2 of PPY-473f8f).* The stamp is read from the lineage being published or announced (`story_checklist.review_stamp`; a translation's own rows). An agent closes `review_people` or `human_review` only with a person's instruction recorded on that change (`onBehalfOf` and the person's words, as `announcements_delivery_review_set` records them; `papyrus stories step --agent --on-instruction-of --quote`, `setStoryStep`), otherwise `delegation-required`. The standing, revocable delegation record (person, agent, sites, steps, granted, revoked) is not built: each delegated change carries its own instruction, so there is nothing to revoke later. The PROVISIONAL labels are removed.

**Translation agent (PPY-98f88e).** The only translation path. It wakes from the Item change feed through the per-scope queue, one wake per Story and language, with `wanted` created when a publish (or a source edit marking blocks stale) names a configured language. It writes its steps into that language lineage's own checklist as it runs, so `wanted -> translating -> ready` is visible as rows. A hold (`held`) is a flag review request that blocks only that language; the other languages of the Story go on. Its rung is `draft` until the gate above is verified, so it leaves a ready draft and never publishes. The `LocalizationRequest` stream, `localization-dispatch` and the dispatcher's direct invocation are deleted in the same change, with no shim. Tests use fakes only. A block a person corrected stays pinned (`stale` never overwrites it).

### 6.5 Illustration

A step of the Story: needed, candidates, chosen, placed. One image when unattended; several when a person is choosing (Ryan, 2026-11-07). Alt text and credit rules keep the step open until met.

### 6.6 Announcement and Delivery

From the announcement design, with the standard's parts named:

| Stage | Moved by | Timer or change | Nobody acts |
|---|---|---|---|
| Decide (create the Announcement and its first Delivery) | Announce | Change: page is live; rating changed | No channel qualifies: no row |
| `drafted` to `ready` | Announce (drafter and checks) | — | A failed check raises one flag, grouped per Announcement |
| Edit window | People, and the machine on unpinned blocks | — | — |
| Lock at `lockAt` | The engine | Follow-up timer | `prepare` with no approval: not locked, not sent, Overdue, one flag. `publish_soft`: the current version is approved by policy and locked. `publish_auto`: approved at creation |
| Attempt | Caducus, one consumer per channel account | Follow-up timer at `releaseAt`, `nextAttemptAt` | An attempt left `started` is settled by Caducus's reconcile, shown as Outcome unknown until then |
| `sent`, `failed`, `blocked` | The engine from the provider's answer | — | `blocked` names its reason and is on Today |
| Correct | A person, or the agent per rung | — | — |

### 6.7 Newsletter issue

An issue is an Announcement of kind `roundup` with one email Delivery (section 15). Its working document fills during the period. At the send time the rung decides. An issue not released before the next period is cancelled with a reason and its items carry forward (slice N3). An empty period sends nothing (slice N4).

---

## 7. The human surface

### 7.1 Today

One page: the newsroom home, which is already the Notification Center [D]. And `papyrus today`.

```
TODAY · Machines on Machines · Monday 16 November

WAITING FOR YOU (3)
  ? Weekly newsletter locks at 3:30 AM — not yet approved            [Open] [Approve]
  ? "Agents that lie" — contradicted claim in paragraph 4            [Open]
  ? 4 five-star candidates                                           [Review]

NEEDS ATTENTION (2)
  ! Outcome unknown — translate · "Eternal October" (es)             [Settle]
  ⏰ Overdue — daily summary was due 6:00 AM, no attempt              [Wake now]

DUE TODAY
  6:00 AM  Daily summary (soft: goes unless stopped)
  ...

WHAT RAN                      ✓ did   – nothing   ? asked   ✗ failed   cost
  Intake and capture            41        0          0         1       $0.38
  Rate                           6        1          1         0       $0.02
  Translate                      3        0          0         0       $0.41
  Announce                       2        9          0         0       $0.00
     – nothing: 7 "not rated", 2 "under the channel's bar"
  ...

PAUSED  none
```

- Order: what only a person can move comes first (slice H2).
- Every status is a word with a mark. Never colour alone.
- "Nothing to do" is shown with its reasons (slice H1). It is how you see an agent is alive.
- Every read is an index: runs by site and day, the attention index, the due indexes (slices A5, C3).
- No subscriptions. It refreshes on focus and every five minutes (Ryan, 2026-11-06).

### 7.2 Poke-in operations

One operation table gives the newsroom, the CLI and MCP the same operations (slices H3, H5):

| Operation | CLI | Who |
|---|---|---|
| Pause or resume one agent, or the site | `papyrus agents pause|resume [--id] --reason` | Editor or admin |
| Change a rung | `papyrus agents set-rung --id --rung [--scope] --reason` | Admin |
| Answer a question | `papyrus reviews answer` (exists) | The person asked |
| Wake now | `papyrus agents wake --id --subject` | Editor |
| Redirect | `papyrus agents redirect --subject --say "..."` | Editor |
| Undo one run | `papyrus agents undo --run` | Editor; lists what cannot be undone |
| Explain | `papyrus agents explain --subject [--agent]` | Anyone signed in |
| Evidence for promotion | `papyrus agents evidence --id` | Anyone signed in |
| Runbook | `papyrus agents runbook --id` | Anyone signed in |

Every write takes `--dry-run`. Every write records who and why.

### 7.3 The generated runbook

Generated from the definition, the site's policy and the operation table (slice D3). For each agent:

1. What wakes it.
2. Its rung on this site, and what that allows and does not.
3. What it may write. What it must never do.
4. How to pause it.
5. How to undo what a run did, and what cannot be undone.
6. What "Outcome unknown" means for this agent and how to settle one.
7. Who it asks, and where the questions appear.
8. Its alarms and what to do for each.

The inventory in `docs/automated-processes.md` becomes generated from the same files, with a test that fails when it is stale.

### 7.4 Email nudges

Admins get "waiting for you" and "something broke"; editors opt in to the rest (Ryan, 2026-11-08). This is PPY-e2d276, after Caducus milestone 3. It is the outbox to people and starts quiet: grouped, one per subject.

---

## 8. Infrastructure as code

Nothing is created by hand. Everything below is in a template applied by the release.

### 8.1 What changes

| Where | Resource | Slice |
|---|---|---|
| Per site (Amplify backend) | One nested `agents` stack, deferred by a new site's first deploy, holding everything below | I4 |
| Per site (Amplify backend) | FIFO queue `agent-wakes`, its dead-letter queue, alarm, event source mapping to the runner | B1 |
| Per site | Stream on the Item table and a change feed function (none today [V]) | PPY-8a374e |
| Per site | Streams and feeds for ReviewRequest and Delivery; feeds on the existing Reference, Message and LocalizationRequest streams | B3 |
| Per site | EventBridge Scheduler group, the scheduler's role (send to the wake queue only), the reconciler and the one-shot helper | C1, C2 |
| Per site | `ProcedureRun`: new fields; two indexes, one per release | A1, A5 |
| Per site | `ReviewRequest`: one index | C3 |
| Per site | `Delivery`: one sparse index for examples | O1 |
| Per site | Spend ledger (generalised from `AnnouncementSpend`) | G1 |
| Per site | `SiteDocument` kind `agents` (no new table) | E1 |
| Per account, shared | Procedure runner: into the release pipeline; role may read wake queues by name pattern; role narrowed to gated operations; self-invoke removed | I1, B1, E3, B6 |
| Per account, shared | Monitoring stack: router sends wakes; per-publication idea and research schedules removed | B6, M2, M3 |
| Alarms | Dead letters, stuck unknowns, feed lag, budget | J1 |

**New tables: none for agent state.** The run record is the wake ledger. The policy is a site document. The work items are existing records. The one generalisation is the spend ledger, which exists as `AnnouncementSpend`.

**The resource ceilings** [V: `scripts/test-bootstrap-stage.ts`, `scripts/test-function-directive-stack.ts`]. Two CloudFormation limits already bite:

- A brand-new site's **first deploy** may create at most 2,500 resources in one stack operation, nested stacks included. The test holds the first stage under 2,000. After the Announcement and Delivery models it stood at 2,062; putting those two models in an optional model group that the first deploy defers brought it to 1,972. **Headroom: about 28.**
- The data API's **function stack** may hold at most 500 resources. A Lambda-backed field that does not share a function costs six.

What the standard costs against them:

| Piece | Resources (estimate [I]) | In the first stage? |
|---|---|---|
| New fields and indexes on `ProcedureRun`, `ReviewRequest`, `SiteDocument`, `Delivery` | 0 (those models are already in deferred groups: procedures, review, tenancy, announcements) | No |
| Spend ledger model | about 15 to 20, as any model | No: it goes in a deferred group |
| Wake queue, dead-letter queue, alarm, event source mapping | 4 to 6 | No: the `agents` stack |
| Schedule group, scheduler role, reconciler function with role and policy, one-shot helper policy | 6 to 9 | No: the `agents` stack |
| Change feed function, role, policy, and one mapping per table | 4 plus 1 per table, about 10 | No: the `agents` stack |
| Alarms (feed lag, stuck unknowns, budget) | 3 to 5 | No: the `agents` stack |
| The gate and the agent operations | 0 new if served by the operation function that exists; 6 per unshared field otherwise | Function stack |

So: about 30 to 45 non-model resources per site, more than the 28 left. The plan therefore puts **every agent resource in one nested `agents` stack that the first deploy defers**, exactly as it defers the optional model groups, and extends the two tests to count it (slice I4, first week, before the queue lands). No stack is split and the budget is not raised. Existing sites are not affected by the first-deploy limit: for them these are ordinary updates.

**One index per table per release** [D: `AGENTS.md`]. The plan stages them: `ProcedureRun` by agent, then `ProcedureRun` attention, `ReviewRequest`, `Delivery` examples, each in its own release.

**Stream readers.** A DynamoDB stream should have at most two readers [I: AWS guidance]. The Reference table has up to two today and the Message table up to three when every feature is on [V]. So a feed on those tables takes the place of a reader by moving an existing consumer behind the feed, not by adding one (slice B3). This is a finding, not something this design fixes for the existing consumers.

### 8.2 Per site and shared tier

- **Dedicated sites** (today's seven): one queue, one schedule group and one policy document per site, in the site's own backend.
- **Shared tier** (multi-tenant, in the existing production account; no new AWS account, per Ryan 2026-11-13): one queue and one schedule group for the tier. The tenant id is part of every message group, wake key, schedule name, ledger scope and policy lookup (slice I2). FIFO groups give each tenant its own lane. Budgets and pauses are per tenant. The cross-tenant isolation suite gains agent cases, and nothing ships to the shared tier before that suite and the security review pass, as already agreed.
- A site in another AWS account (Humorus) gets its own runner from the same template.

### 8.3 Cost model

| Thing | Cost shape |
|---|---|
| An idle agent | Zero. No poll, no schedule that walks a table. |
| A schedule tick | One scheduler invocation and one queue message. Fractions of a cent a month per agent. [I] |
| A change | Stream records are free of AppSync charges; one small function invocation; one queue message per listening agent. |
| A run | Lambda time for its length, plus model spend, counted on the ledger. |
| A "nothing" run | A few indexed reads. No model call. |
| Follow-up timers | One scheduler entry per waiting record, deleted when it fires. |

The dominant cost is model spend. It is the one thing with a budget (slice G2) and it is visible by responsibility (slice I3).

---

## 9. Observability and safety

- **Receipts.** The run record: wake key, outcome, reason, rung and policy version, versions read and written, each operation asked and the gate's answer, tools used, cost (slices A1, J3). No text in the row; bodies in S3 (slice A4).
- **Proving an agent did nothing wrong.** List its writes from the run record and match them to immutable record versions. A refused operation is on the record. At `observe` the list of writes is empty by construction.
- **Alarms** (slice J1): a dead-lettered wake; an `unknown` that stays unknown; a change feed falling behind; the budget reached.
- **Kill switches** (slice J2): pause one agent; pause the site; pause sending on one channel account. Each has a test that proves it stops the next run or attempt.
- **Spend guards.** The budget stop; the unusual-cost flag.
- **Dry run.** The `observe` rung (slice J4). One mechanism.
- **Rollback.** `agents undo --run` restores the versions a run replaced and lists what cannot be undone. A rung is lowered in one operation. A learned rule is retired in one operation. Tables have point-in-time recovery [D].
- **Loop guard** (slice B7). A count of agent runs per subject since a person last acted. At the owner's limit, one hard gate.
- **Invariant checks** (slice J6) for the Announcement and Delivery writes that cannot be one transaction (section 17).

---

## 10. Models and tiers

| Tier | Used for | Which responsibilities |
|---|---|---|
| `editorial` | Writing and rewriting that readers will see; theses; headlines | Write and improve; drafting an issue's lead |
| `work` | Structured tasks and checks | Fact check, translation, capture and summary, announce drafting, ideation, learn from edits |
| `bulk` | Rating and bookkeeping | Rate, operations hygiene |
| `decision` | The trained decision model, never a general model | Relevance, acceptance, "does this edit change meaning" |

- A definition names a tier. The site policy maps a tier to a model id (slice G4). Changing a model is a policy change with a version.
- Ryan's rules: the strongest model only for editorial writing; cheaper models for work; the cheapest for bulk curation; the decision model is Jev or its successors and never a general chat model.
- **Quota.** The weekly quota Ryan is conserving belongs to coding sessions. Always-on agents run in the cloud on API keys and spend dollars, which the ledger counts and the budget stops. Moving standing work out of sessions is itself the quota saving. [I]
- An agent with nothing to do makes no model call. Free checks run in code.

---

## 11. Compare and contrast with what exists

| Existing piece | Verdict | What happens |
|---|---|---|
| `Automation` records [V] | **Extend** | Becomes the registered copy of a definition. `enabled`, `limits` and `trigger` move to the definition and the policy document. |
| `ProcedureRun` [V] | **Extend** | Gains the wake key as its id, outcome, subject, rung, policy version. Bodies move to S3. Two indexes. |
| Procedure runner Lambda [V] | **Keep, change how it is started** | Consumes the wake queue. Role narrowed. Deployed by the pipeline. |
| `TRIGGER#`, `STAGE#`, `MANUAL#` rows in the monitoring table [V] | **Replace** | The run record is the claim. Rows deleted after one conversion for history (slice B6). |
| Stage Bots [V] | **Extend** | Stage entry comes from the Item change feed, so console moves count. The engine still moves the stage. Hop limit becomes the loop guard. |
| Monitoring router [V] | **Keep** | Still decides delivery. Starts procedures by sending a wake. `procedureTriggers` in the router config becomes a definition's `wakes`. |
| Review requests [V] | **Keep, fix reads and deadlines** | Index and timers (slice C3). They are the outbox to people. |
| Messages and threads [V] | **Keep, people only** | A person's Message wakes agents. Agents answer with run cards. |
| Story checklist [V] | **Keep** | Steps are the work items. |
| `Assignment` [V] | **Extend** | Any responsibility, not only research. |
| Caducus | **Keep** | The transport and the outbox to readers. |
| Newsroom procedures and skills | **Keep** | Each gets a definition. |
| Notification Center | **Extend** | Becomes Today. |
| The publish gate, `autoAccept`, `languages.auto`, `announcementReview` | **Replace with rungs** | One conversion each (slice E5, PPY-97c0f2). |
| `docs/automated-processes.md` inventory | **Replace with a generated one** | Slice D3. |
| PPY-9ff95b's "three runtimes" | **Narrow** | Lambda by default, container for the knowledge run. Local pods run no unattended agents. |
| PPY-2b4bda (outputs go to review by default) | **Superseded** | The ladder's default rung is that rule. Closed with a pointer to E1 and E2. |

### Findings: things that contradict the standing rules

I list these. I did not fix them.

| # | Finding | Rule | Evidence | Fixed by |
|---|---|---|---|---|
| F1 | `START_AS_BEFORE`: when the Automation record is missing or unreadable, or counting fails, the router starts the run anyway. | No fallbacks | [V] `automation_gate.py:47`, `monitoring_router.py:2248`; documented as deliberate in `docs/automations.md` | B6 |
| F2 | The runner records a run again without usage fields for a backend that predates them; `graphql_authoring.py` retries without cost fields. | No shims for schema drift | [V] `procedure_runner.py:218`, `graphql_authoring.py:1165` | A1 (remove when the fields are everywhere) |
| F3 | `procedure-action` lists whole tables when an index query is missing. | No fallbacks; indexes over scans | [V] `handler.ts:416` | A5 |
| F4 | `list_records("Automation")` on every stage delivery and every router gate; `list_records("ReviewRequest")` on every read, every answer and every gated publish. | No O(N) per change | [V] `story_triggers.py:101`, `monitoring_router.py:2254`, `review_requests.py:227,258`, `publish_gate.py:96` | PPY-8a374e, B6, C3 |
| F5 | A fixed 0.50 dollar guard per publication per run. | No arbitrary limits | [V] `monitoring_stories.py:71` | Removed (PPY-45c2ef): monitor stories run under the spend ledger, the budget and the unusual-cost flag |
| F6 | `KNOWLEDGE_REVIEW_MAX_CALLS` default 150 per run. | No arbitrary limits | [D] `docs/automated-processes.md` | M9 (make it a budget) |
| F7 | `research_explorer.tac` retries malformed output three times, then "falls back to a deterministic snippet"; web search tries three providers in order. | No fallbacks | [D] `docs/agent-loop-patterns.md` | M3 (decide: fail and flag) |
| F8 | Subscriber `history` "capped at 50"; `MAX_HISTORY=50` on review requests; "the last 20" stage moves. | No arbitrary limits | [D], [V] `review_requests.py:52` | Not in this plan; the real constraint is the item size limit. Listed for Ryan. |
| F9 | `ProcedureRun.input`, `output`, `error` hold whole bodies in DynamoDB. Message `content` is a DynamoDB string. | Never store text in DynamoDB | [V] `schema.ts:1496`, `2236` | A4 for runs. Messages are outside this plan. |
| F10 | The procedure runner stack is updated by a hand-run change set. | Nothing by hand | [D] `AGENTS.md`, "Other shared stacks" | I1 |
| F11 | The publish path tells the newsletter and notifications functions with a best-effort call whose errors are swallowed. | No lost events | [D] `docs/newsletter.md` | PPY-e3bb2b |
| F12 | A Stage Bot start refused at the concurrency limit writes no row and nothing retries it. | Never silent | [V] `story_triggers.py:178` | B4 |
| F13 | A console board move fires no trigger. | — | [V] | PPY-8a374e |
| F14 | `request_meter` budgets only warn; enforcement was due 2026-11-13. | — | [V] `request_meter.py` | Not in this plan. Listed. |
| F15 | The research worker polls every 5 minutes; the notifications flush runs every minute. | Compute once on change | [D] | M3 for research. The flush is Caducus's pacing; listed. |
| F16 | Soft review deadlines only fire when someone reads the list. | Never silent | [V] `review_requests.py:238` | C3 |
| F17 | Machine Messages still exist: research packets, console chat (stage 2 of PPY-781d26 is open). | Messages only from people | [D] `AGENTS.md` | F3 depends on that epic for the chat. |
| F18 | Corrections in PR #1618: see section 17.2. | — | [V] PR branch | PPY-3e0a8a, PPY-a570e8, J6 |

---

## 12. The plan

The plan is filed on the Papyrus board as initiative **PPY-a3fceb**, "Always-on agents: one standard for every standing responsibility". Every slice below is a task whose text stands alone on the board. Codes (A1, B3) are for reading this document; the board id follows each.

### 12.1 Which responsibility first, and why

**Rating, on Machines on Machines** (epic L, PPY-24b2ac).

- **Most value.** Stars decide what the home page shows, what a newsletter includes, what is announced. Machines on Machines has a backlog of unrated published Stories, and `publishRequiresRating` needs every Story rated.
- **Lowest risk.** The rule is already written: three by default, four if clearly better, never five. A person's rating always replaces the agent's. Nothing it writes is public text. The model is the cheapest tier.
- **It exercises the whole standard**: a schedule, a wake key, a run, an outcome, a rung, Today. And then change triggers when it is promoted.

Second: ideation and intake, because they already run and only need moving onto the standard. Third: announcements and newsletters, on the records already being built.

### 12.2 The first week: baby steps that show something

| Day | Slice | What is visible afterwards |
|---|---|---|
| 1 | I1 (PPY-624dab) The runner deploys through the pipeline | A release updates the runner with no hand step. |
| 1 | I4 (PPY-e06835) Agent resources in one deferred stack, counted | The first-deploy count does not rise as agent pieces land. |
| 1 | A1 (PPY-f58445) Outcome vocabulary | Every run in the history shows one of five words. |
| 2 | A2 (PPY-70c6e8) Wake keys | The same wake twice makes one run. |
| 2 | D1 (PPY-68abaa) The agent definition file | `papyrus agents validate` checks a definition offline. |
| 2 | E1 (PPY-51ea61) The agent policy document | An admin sets a rung with a reason; a pause stops runs. |
| 3 | B1 (PPY-567bf9) The wake queue | Run now goes through the queue; a crash is redelivered. |
| 4 | C1 (PPY-2a53cd) The schedule trigger | An agent runs on a clock from data. |
| 5 | L1 (PPY-d85860) Rating agent at `observe` on Machines on Machines | A real daily agent runs end to end and lists what it would rate. |
| 5 | H1 (PPY-5bcf42) Today v1 | One page says what ran, what it decided and what it cost. |

Nothing in week one changes what any site publishes.

### 12.3 Where the announcement epic's tasks sit

The epic PPY-a36492 has 21 tasks on the board (the brief counted 20 before the pod base task was added), plus one follow-up filed today (PPY-58f931). It is now a child of the initiative and one client of the standard.

| Order | Tasks | Waits for | Why |
|---|---|---|---|
| Now, in parallel with week one | PPY-9c2ea0 (closed, merged), PPY-4834f3 (closed, merged), PPY-58f931 pod check validates guideline files, PPY-1d5c43 guideline files in the cloud, PPY-e4fd0c then PPY-50a7f5 then PPY-8195a4 (pod lifecycle), PPY-3792dd (records; PR #1618 in CI) | Nothing in the standard | Files, pods and plain records. No agent, no timer, no send. |
| After A1 (PPY-f58445) | PPY-a570e8 attempt log | The outcome words | Attempts and runs must use one vocabulary. Small. |
| After B1 (PPY-567bf9) and PPY-8a374e | PPY-e3bb2b durable triggers | The wake queue and the Item change feed | Built once as the standard's feed, not as a path of its own. |
| After E1 (PPY-51ea61) and E2 (PPY-611397) | PPY-97c0f2 review policy | The ladder and the gate | `announcementReview` is a rung. Building it first as its own setting would have to be converted later. |
| After PPY-97c0f2 and C2 (PPY-3ff011) | PPY-e8ec54 editing window and lock | Follow-up timers | Lock and release times are timers. |
| Then | PPY-efd06c X on the new records (X off), PPY-3e0a8a corrections, PPY-4410fc manual mode, PPY-9c6b89 channel guidelines, PPY-e4ae3a drawer and list | The four above | Unchanged order among themselves. |
| After PPY-824c14 (Caducus move), C1 (PPY-2a53cd) and N1 (PPY-4d74d9) | PPY-58d962 email alerts, PPY-1e75aa roundup issues, PPY-cb3cc9 assembly | The schedule trigger and list cadence | Roundups are scheduled agents; cadence is list data. |
| After PPY-3792dd, PPY-e4fd0c | PPY-e78134 Announcement and Delivery notes in a pod | — | Unchanged. |
| Last | PPY-e7eaa3 the p.apyr.us page | N9 (PPY-00817a) the five walkthrough specs | Document what is proven. |

The change from the order in section 13.4 of the announcement design: the review policy and the durable triggers now wait for the standard's ladder and change feed, so each is built once. The records, the attempt log, the guideline and pod tracks do not wait.

### 12.4 The epics

| Epic | Board id | Tasks | Purpose |
|---|---|---|---|
| A. Wake contract and run outcomes | PPY-865e83 | 6 | Every run of every agent has the same shape: a wake comes in with a key, a short run happens, and one of five outcomes is recorded (acted, nothing, asked, failed, unknown). The run record (`ProcedureRun`) is extended; no new table. |
| B. Inbox: change feeds, the wake queue and one worker | PPY-cd706f | 7 | Changes to records become wakes without anyone calling anything: a change feed per table sends wakes to one FIFO queue per site, and the procedure runner consumes the queue. The queue's message group gives one worker per responsibility and scope. |
| C. Timers: the schedule trigger and follow-ups | PPY-4bc313 | 4 | A timer only raises a wake; the run re-reads the records and re-checks everything. Recurring schedules come from agent definitions; one-off follow-ups come from a due time on a record. |
| D. Agent definitions, the catalog and generated runbooks | PPY-b05940 | 4 | One way to set up an agent: a definition file in Git that fills the 11-point template, validated and applied by the release. |
| E. Authorization: the autonomy ladder as configuration | PPY-077760 | 6 | How far an agent may go is site data, not code: seven rungs (off, observe, propose, draft, prepare, publish with soft review, publish automatically), set per site and responsibility with narrower overrides, in one versioned policy document. One gate at the operation table answers allowed, blocked or human_required. Hard floors hold at every rung. |
| F. Work items and handoffs between agents and people | PPY-928a91 | 5 | Agents talk through durable records, never chat: a checklist step, an Assignment (a request for work), a review request (a question for a person). A person's comment or answer enters the same way. No mailbox object. |
| G. Spend, budgets and model tiers | PPY-6505b3 | 4 | Money is a real constraint and the only cap on agent work. One ledger counts spend per site and budget cycle; at the budget, paid work waits for the next cycle and one flag is raised. Which model does which work is configuration. |
| H. Human surface: Today, poke-in operations and explanations | PPY-767813 | 5 | One page answers 'what is the system doing today?': waiting for you, overdue, outcome unknown, failed, what ran, what it decided to do nothing about, what it cost. Every poke-in (pause, change a rung, answer, redirect, undo, wake now) is one operation with the same name in the newsroom and the CLI. |
| I. Infrastructure as code and the shared tier | PPY-33e622 | 4 | Everything the standard needs is in templates applied by the release: queues, dead-letter queues, alarms, the schedule group and its role, change feed mappings, indexes. Nothing is created by hand, including the procedure runner, which today is updated with a hand-run change set. |
| J. Observability, safety and release readiness | PPY-b7039f | 6 | Prove what an agent did and did not do; stop anything fast; turn things on in a safe order. |
| K. Lifecycles that run themselves: Reference, Idea, Translation, Illustration | PPY-462d6e | 4 | For each record type: its stages, which agent moves each stage, which stage needs a person by policy, and what happens when nobody acts. (Story is PPY-959e41; Announcement, Delivery and newsletter issues are PPY-a36492 and the newsletters epic.) |
| L. First agent: rating and curation on one site | PPY-24b2ac | 4 | The first real daily agent, end to end, at the lowest rung. It suggests stars for what is unrated (three or four, or five as a candidate) beside the rating; a person rates. Chosen because stars decide everything downstream (home pages, newsletters, announcements), the rule is already written (default three, machines never five), a person's rating always wins, and the model is the cheapest tier. |
| M. Every other responsibility as an agent | PPY-11b33b | 9 | Move each existing automated process onto the standard and add the missing ones: intake and capture, ideation, research, translation, illustration, improvement and copy-edit, fact-check, operations hygiene, the knowledge run. Each task ends with the agent running on one site at the rung its site policy names, with its 11-point definition and generated runbook. |
| N. Newsletters and subscriptions: weekly, daily and every new item | PPY-79c915 | 10 | One system produces a weekly Distinctive Mark email, a weekly and a daily Machines on Machines newsletter, and a message for every new item, all as Announcements and Deliveries sent through Caducus. What differs between them is list data: cadence, time, time zone, rule, working document, rung. |
| O. Announcements learn from a person's edits | PPY-f51641 | 6 | When a person rewrites how something is announced, future announcements change, and never silently. An edit becomes an example only when a person says so; a pattern becomes a proposed guideline file an admin accepts; every draft names the guideline versions and examples it read; every learned thing can be turned off. |
| Announcement and Delivery (existing) | PPY-a36492 | 22 | One Announcement, many Deliveries. Re-parented as a client. |
| The Story checklist that runs itself (existing) | PPY-959e41 | 10 open | Re-parented as the Story lifecycle's client. Its step runner PPY-8a374e moved to epic B. |
| Background automation (existing) | PPY-9ff95b | precursor | Re-parented. PPY-2b4bda closed as superseded by the ladder. |

### 12.5 Every slice

#### Epic A. Wake contract and run outcomes (PPY-865e83)

Every run of every agent has the same shape: a wake comes in with a key, a short run happens, and one of five outcomes is recorded (acted, nothing, asked, failed, unknown). The run record (`ProcedureRun`) is extended; no new table. Done when every run on every site carries a wake key and an outcome, an interrupted run shows as Outcome unknown and is settled without doing the work twice, and run bodies are in S3.

**A1 (PPY-f58445): Outcome vocabulary on every run**  · first week

- *Purpose.* Add `outcome` to `ProcedureRun` with exactly five values: `acted` (it did the work), `nothing` (it looked and there was nothing to do), `asked` (it raised a question for a person and stopped), `failed` (it could not do the work; nothing half-done is left as if done), `unknown` (it started and no result was recorded). Add a short `outcomeReason` code, plus `automationId`, `responsibility`, `subjectKind`, `subjectId`, `subjectVersion` and `rung` (the rung it ran under). `runStatus` keeps the mechanics (`waiting`, `queued`, `started`, `finished`); `outcome` is set only when a run finishes or is settled. The runner writes both. The CLI and console show each outcome as a word with a mark, never colour alone. Delivery attempts use the same words for the same things (`started`, then `sent`, `refused` or `unknown`). Existing runs are not rewritten; a run without an outcome shows "recorded before outcomes".
- *Acceptance.* A finished run always has one of the five outcomes. A run that looked and found nothing records `nothing` with a reason code; it is not a failure. `papyrus automations runs` and the console show the outcome in words with a mark. No existing run is rewritten.
- *Gherkin.* run-outcomes.feature: a run that does its work is `acted`; a run with nothing to do is `nothing` with a reason; a run that raises a review request is `asked`; a procedure error is `failed`; an older run shows 'recorded before outcomes'.
- *Infrastructure as code.* Amplify data schema: new optional fields on `ProcedureRun` (no index in this task). Runner image.
- *Blocked by.* nothing; ready to start
- *Unblocks.* A2 (PPY-70c6e8), A4 (PPY-8b131e), A5 (PPY-577310), D1 (PPY-68abaa), G1 (PPY-fa165c), H1 (PPY-5bcf42), N4 (PPY-1d451f), PPY-a570e8

**A2 (PPY-70c6e8): Wake keys: one run per wake, recorded before the work starts**  · first week

- *Purpose.* Every wake carries a key that says what it is about: `<automationId>|<subjectId>|<subjectVersion>|<what>` for a change, `<automationId>|schedule|<scheduled time>` for a timer, `<automationId>|manual|<request id>` for a person's Run now. The run record's id is derived from the key and created with a condition, so the same wake can never start a second run. The record is created as `started` before the procedure is loaded, so a crash leaves evidence. This replaces the random run id and the claim rows in the monitoring table (those are removed in the migration task). A run started by `papyrus procedures run` gets a manual key.
- *Acceptance.* The same wake delivered twice produces one run record and one run. The run record exists with status `started` before any procedure code runs. A manual run and a scheduled run of the same agent have different keys and both run.
- *Gherkin.* wake-keys.feature: the same change delivered twice runs once; a redelivered timer runs once; two different versions of one Story run once each; a manual run has its own key; the record is `started` before the procedure loads.
- *Infrastructure as code.* None beyond A1 (the id is data). Runner image.
- *Blocked by.* A1 (PPY-f58445)
- *Unblocks.* A3 (PPY-2d2e55), A6 (PPY-c023ab), B1 (PPY-567bf9), L1 (PPY-d85860)

**A3 (PPY-2d2e55): Settle an interrupted run: Outcome unknown is a state, not a guess**

- *Purpose.* A queue message is received at most twice by design: once to run, once to settle. On the second receipt the runner reads the run record. If the record is `started` with no outcome, the first attempt died. If the agent's definition says the procedure is safe to repeat (every write it makes is keyed), the runner runs it once more under the same key. If not, it records `unknown`, raises one flag for a person and deletes the message. No timeout and no retry count decides anything. A third receipt can only mean the settle step itself crashed; the message goes to the dead-letter queue and the alarm fires.
- *Acceptance.* A run that died is never left looking as if it is still running. A procedure not marked safe to repeat is never run twice for one wake. `unknown` shows on Today as 'Outcome unknown' with the run and what it may have written.
- *Gherkin.* run-settle.feature: a crashed safe-to-repeat run is run once more and ends `acted`; a crashed unsafe run ends `unknown` with one flag; a settled run is not run again on a later redelivery; a crash during settling reaches the dead-letter queue.
- *Infrastructure as code.* Queue redrive policy (receive twice, then dead letter) on the wake queue; dead-letter alarm.
- *Blocked by.* A2 (PPY-70c6e8), B1 (PPY-567bf9)
- *Unblocks.* H2 (PPY-b6d5ad), J1 (PPY-45ef76)

**A4 (PPY-8b131e): Run input, output and errors live in S3, not in the catalog**

- *Purpose.* `ProcedureRun.input`, `normalizedInput`, `output` and `error` hold whole JSON bodies in DynamoDB today, against the standing rule that DynamoDB is the catalog and text lives in S3. Move them to one attachment per run (the existing `ModelAttachment` path, owner kind `procedure_run`). The row keeps `resultSummary` and `errorSummary` as short fields and the attachment key. Readers (the console run view, `automations runs`, the Stage Bot engine reading `output.version`) read the attachment. Existing rows are converted once by a command; there is no reader for both shapes afterwards.
- *Acceptance.* A new run row holds no body, only keys and short summaries. The console and CLI show the same output as before. The conversion command run twice changes nothing.
- *Gherkin.* run-bodies-in-s3.feature: a run row holds no output text; the run view shows the output read from S3; converting twice is a no-op; a run whose attachment is missing says so plainly.
- *Infrastructure as code.* Amplify data schema (fields removed after conversion), storage access rule for the new owner kind.
- *Blocked by.* A1 (PPY-f58445)
- *Unblocks.* —

**A5 (PPY-577310): Run indexes: by agent, and 'needs attention'**

- *Purpose.* Two indexes on `ProcedureRun`, added in two releases because a deploy adds one index per table: (1) `automationId` + `requestedAt`, so an agent's runs are one query; (2) a sparse `attentionKey` + `dueAt`, present only while a run is `waiting`, `unknown` or `failed` and unacknowledged, so Today and the overdue check read only what needs a person. Remove the code paths that load every `ProcedureRun` (`procedure-action` `listModelPages` and its full-list path when an index query is missing).
- *Acceptance.* An agent's run history is one indexed query. A run that needs nobody is not in the attention index. No code path lists the whole `ProcedureRun` table.
- *Gherkin.* run-indexes.feature: an agent's runs are listed newest first by index; an acknowledged failure leaves the attention list; the run list never reads the whole table (request meter shows no unbounded list).
- *Infrastructure as code.* Amplify data schema: two GSIs on `ProcedureRun`, one per release.
- *Blocked by.* A1 (PPY-f58445)
- *Unblocks.* C4 (PPY-70cd6a), E6 (PPY-994ff6)

**A6 (PPY-c023ab): Continuation: a unit of work longer than one run**

- *Purpose.* A run is a short wake-up; the runner Lambda has 15 minutes, which is a real limit. Work is cut by record first (one Story, one step, one language). When one unit still cannot finish, the procedure saves its progress on the records it is changing (a new draft version, a step's evidence), ends `acted` with `nextWakeAt`, and the engine sets a follow-up timer whose key ends in `|c<n>`. The next run re-reads the records and continues. Progress never lives in the model's transcript. A procedure that neither finishes nor saves progress is `failed`.
- *Acceptance.* A long unit finishes across several runs with no step done twice. Each continuation is its own run record with its own cost. Nothing depends on a saved model session.
- *Gherkin.* run-continuation.feature: a translation too long for one run finishes in two; the second run starts from saved progress; a run that times out without saving is `failed`, not continued.
- *Infrastructure as code.* None (uses the follow-up timer from C2).
- *Blocked by.* A2 (PPY-70c6e8), C2 (PPY-3ff011)
- *Unblocks.* —

#### Epic B. Inbox: change feeds, the wake queue and one worker (PPY-cd706f)

Changes to records become wakes without anyone calling anything: a change feed per table sends wakes to one FIFO queue per site, and the procedure runner consumes the queue. The queue's message group gives one worker per responsibility and scope. Done when a console board move, a CLI write and an agent's own write all wake the right agents, no code lists the Automation table per change, and the TRIGGER#, STAGE# and MANUAL# row families are deleted.

**B2 (PPY-8a374e, existing, re-used): the Item change feed and dispatcher.** The step runner already planned for the Story checklist is the standard's feed for the Item table. Re-parented here and extended in its own text. Blocked by B1 (PPY-567bf9), D1 (PPY-68abaa). Unblocks: B3 (PPY-9b9e64), B5 (PPY-67e3cd), B6 (PPY-4af216), B7 (PPY-4e7e8b), F2 (PPY-5cf1a8), K2 (PPY-f1c774), K4 (PPY-ce0dd2), L3 (PPY-924693), M6 (PPY-18b582), M7 (PPY-396483), PPY-e3bb2b.

*Built (the feed).* `src/papyrus_content/item_change_feed.py`, `amplify/agents/item-change-feed.ts` and `amplify/functions/item-change-feed/`: the Item stream, a feed function in the `agents` stack, and a listener index (`agent_listeners.py`, written by `papyrus agents listeners` at deploy) that replaces any list of the Automation table per change. The coalescing window (PPY-67e3cd) and the loop guard (PPY-4e7e8b) are built in `src/papyrus_content/wake_gate.py` between the Item feed and the queue (`docs/automations.md`); the other tables' feeds are not gated yet; moving the Stage Bots, which still list the Automation table per stage delivery, is B6 (PPY-4af216).

**B3 built (PPY-9b9e64).** `src/papyrus_content/change_feeds.py` (over the Item feed's change, wake and loop), `change_vocabulary.py` (the changes a definition may listen for), `amplify/functions/change-feed/` and `amplify/agents/change-feeds.ts`: one feed function for the five tables, not one per table (the code is shared and the stream ARN names the table; one function costs 3 resources once and 1 per mapping). Streams are switched on for ReviewRequest and Delivery; `amplify/agents/stream-readers.ts` places each feed (its own mapping where the table has fewer than two readers, behind a reader that stays on the stream where it has two) and `scripts/test-agents-stack.ts` proves no table is given a third. Not built here: moving the Message stream's third reader, the live proof, and the F1/F3/F4 agents that use these changes.

**B1 (PPY-567bf9): Per-site wake queue; the procedure runner consumes it**  · first week

- *Purpose.* Add one FIFO queue per site, `papyrus-<site>-agent-wakes.fifo`, with a dead-letter queue and an alarm. A wake is a small message: the wake key, the agent, the subject and why. The message group id is the agent plus its serial scope (see the one-worker task), and the deduplication id is the wake key. The procedure runner Lambda is the queue's consumer (batch size 1), so it holds the message for the whole run and the queue redelivers it if the run dies. Run now and `papyrus automations run` put a message on the queue instead of invoking the runner; the direct asynchronous invocation is deleted from every caller in the migration task. The runner's role reads queues by the name pattern, one statement for all sites.
- *Acceptance.* A wake put on the queue starts exactly one run. A runner crash redelivers the message; nothing is lost. The dead-letter queue has an alarm and is empty in normal operation. Run now goes through the queue.
- *Gherkin.* wake-queue.feature: a wake starts one run; two wakes for the same group run one after the other; two wakes for different groups run at the same time; a duplicate wake inside the deduplication window is dropped; a message the runner cannot parse reaches the dead-letter queue.
- *Infrastructure as code.* Site backend (Amplify): FIFO queue, dead-letter queue, alarm, event source mapping to the runner. Runner template: role statement for the queue name pattern.
- *Blocked by.* A2 (PPY-70c6e8), I1 (PPY-624dab), I4 (PPY-e06835)
- *Unblocks.* A3 (PPY-2d2e55), B4 (PPY-a200ec), C1 (PPY-2a53cd), C2 (PPY-3ff011), G2 (PPY-9376f8), H3 (PPY-e6f31e), I2 (PPY-8cf5e2), I3 (PPY-04c0d1), J1 (PPY-45ef76), PPY-e3bb2b, PPY-8a374e

**B3 (PPY-9b9e64): Change feeds for Reference, ReviewRequest, Message, LocalizationRequest and Delivery**

- *Purpose.* The Item change feed (PPY-8a374e) turns Item changes into wakes. Do the same for the other tables agents react to, one small function per table with a filter in the event source mapping: a Reference created, accepted, rated or re-captured; a review request answered; a Message posted by a person on a subject; a LocalizationRequest wanted; a Delivery state change. Each feed emits the same normalized change (`table, kind, id, lineage, version, change, actorKind, at`) and looks up which agents listen in the site's cached agent definitions (read by the tenant index, never a table list). A table already at two stream readers gets its feed by moving an existing reader behind the feed, not by adding a third.
- *Acceptance.* Each listed change produces a wake for every agent whose definition listens for it, and for no other. No feed reads a whole table. No table has more than two stream readers.
- *Gherkin.* change-feeds.feature: accepting a Reference wakes the agents that listen for it; answering a review request wakes the agent that asked; a person's Message on a Story wakes the Story's agents; an agent's own write does not wake itself for the same version; a change nobody listens for sends nothing.
- *Infrastructure as code.* Site backend: stream enabled on ReviewRequest and Delivery tables; event source mappings with filters; one feed function. Staged where a table gains a stream.
- *Blocked by.* PPY-8a374e
- *Unblocks.* F1 (PPY-51f96f), F3 (PPY-32b5c1), F4 (PPY-ecf852), K1 (PPY-bea2bf), K3 (PPY-21b8c5), L3 (PPY-924693), M1 (PPY-ad7087), M4 (PPY-98f88e)

**B4 (PPY-a200ec): One worker per responsibility and scope**

- *Purpose.* State the rule once and enforce it with the queue: all wakes of one agent for one serial scope pass through one message group, so they run one at a time, in order. The definition names the scope: `subject` (one Story at a time, many Stories at once), `agent` (the whole agent one at a time, for anything that spends from one budget or posts to one account), or a named key such as the channel account. This replaces `limits.maxConcurrent`, the count of rows in flight, the 120-second grace and the router's deferred retry sweep. The total number of runs at once is the event source's maximum concurrency, set from the model provider's rate limit, a real constraint.
- *Acceptance.* Two wakes in one group never run at the same time. A burst for many subjects runs in parallel up to the provider limit. `maxConcurrent`, the in-flight count and the deferred sweep are deleted.
- *Gherkin.* one-worker.feature: two changes to one Story run in order; changes to two Stories run together; an agent with scope `agent` runs one at a time across all subjects; a slow run delays only its own group.
- *Infrastructure as code.* Event source mapping maximum concurrency as a template parameter.
- *Blocked by.* B1 (PPY-567bf9)
- *Unblocks.* B6 (PPY-4af216)

**B5 (PPY-67e3cd): Coalescing window: wait for quiet before paid work**

- *Purpose.* A burst of edits must not start ten paid runs. For a step marked paid, a change does not wake the agent at once; it sets or replaces one follow-up timer for that subject and step, due when the subject has been quiet for the site's window. The window is site data (Ryan's ruling: 30 minutes to 24 hours, about 5 minutes after a person's own action). Free steps wake at once. The pending wake's key leaves out the version; when it fires, the run takes the version that is current then. One pending timer per subject and step, never a sweep.
- *Acceptance.* Ten quick edits to one Story start one paid run. A person's edit uses the short window. A free check runs at once on every save.
- *Gherkin.* coalescing-window.feature: ten saves in a minute start one fact check; the run uses the last version; a person's edit shortens the wait; a free step runs on each save; changing the window changes only later waits.
- *Infrastructure as code.* None beyond the follow-up timer (C2). The window is a field in the agent policy document.
- *Blocked by.* PPY-8a374e, C2 (PPY-3ff011)
- *Unblocks.* M7 (PPY-396483), PPY-cb3cc9

**B6 (PPY-4af216): Move monitor triggers, Stage Bots and Run now onto the wake path**

- *Purpose.* Three older paths start procedures: the monitoring router's `procedureTriggers` (with `TRIGGER#` rows), Stage Bots (`STAGE#` claim rows, delivered only from the CLI and the runner), and Run now (`MANUAL#` rows). Move each onto the wake queue with wake keys, one at a time, each in its own release: the router puts a wake for a newly created Reference instead of invoking the runner; a stage entry comes from the Item change feed; Run now puts a manual wake. Then delete the three row families, the claim code, `START_AS_BEFORE` (the rule that starts a run when the Automation record cannot be read, which is a fallback), the per-delivery `list_records("Automation")` calls, and the unused `MAX_TRIGGER_PAGES`. Distinctive Mark's TTAB analysis is the test: it must behave the same before and after.
- *Acceptance.* Distinctive's TTAB analysis starts once per new decision through the queue. A console board move starts the stage's agent. No `TRIGGER#`, `STAGE#` or `MANUAL#` row is written; history for old rows stays readable until the conversion command has run once. An unreadable agent definition stops the start and raises a flag; nothing 'starts as before'.
- *Gherkin.* wake-path-migration.feature: a new TTAB decision starts one analysis; a console board move starts the stage agent; Run now appears in the run history with who started it; an unreadable definition starts nothing and raises one flag; the history shows runs from before and after the move.
- *Infrastructure as code.* Monitoring stack: the router's role sends to site wake queues and loses `lambda:InvokeFunction` on the runner. Runner template: remove self-invoke.
- *Blocked by.* PPY-8a374e, B4 (PPY-a200ec), E1 (PPY-51ea61)
- *Unblocks.* E5 (PPY-8e74bb), M1 (PPY-ad7087), M2 (PPY-fb1aef)

**B7 (PPY-4e7e8b): Loop guard per subject**

- *Purpose.* Agents wake each other by changing records, so two agents could pass a Story back and forth. Keep the existing guard and make it general: a counter of agent runs per subject since a person last acted on it. The limit is an owner setting in the agent policy document; at the limit nothing more starts for that subject and one hard-gate review request says so. A person's action resets the count. An agent's own new version wakes free checks, and never the same paid step on its own output.
- *Acceptance.* A ping-pong between two agents stops at the owner's limit with one hard gate. A person's edit resets the count. An agent never re-runs its own paid step on the version it just wrote.
- *Gherkin.* agent-loop-guard.feature: two agents alternating stop at the limit; the hard gate is raised once; a person's action lets work continue; an agent's own version does not re-wake it.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e
- *Unblocks.* —

#### Epic C. Timers: the schedule trigger and follow-ups (PPY-4bc313)

A timer only raises a wake; the run re-reads the records and re-checks everything. Recurring schedules come from agent definitions; one-off follow-ups come from a due time on a record. Done when an agent can run daily or weekly from data alone, review request deadlines fire without anyone opening a page, and anything due and untouched shows as Overdue and raises one flag.

**C1 (PPY-2a53cd): The schedule trigger: an agent runs on a clock from data**  · first week

- *Purpose.* Build the `schedule` trigger kind that is stored today and starts nothing. A definition may carry a schedule (a cron expression and a time zone). A small reconciler, fed by the change feed of the agent definitions, creates, updates or deletes one EventBridge Scheduler entry per scheduled agent, named from the agent id, in the site's schedule group. The entry's only target is the site's wake queue; its message carries the scheduled time, which becomes the wake key, so a redelivered tick runs once. A timer does nothing else: the run re-reads everything. The schedule group, the role the scheduler assumes and the reconciler's role are in the template; no schedule is made by hand. Daylight saving time is handled by the scheduler's time zone support, not by code.
- *Acceptance.* An agent with a daily schedule runs once a day at that local time, across a daylight-saving change. Changing or removing the schedule in the definition changes or removes the entry. A paused agent's tick is consumed and recorded as nothing-started with the reason 'paused'. No schedule exists that a definition does not name.
- *Gherkin.* schedule-trigger.feature: a daily agent runs once per day; a duplicate tick runs once; a changed time takes effect at the next tick; removing the schedule removes the entry; a tick for a paused agent starts nothing and says why; the local time holds across a clock change.
- *Infrastructure as code.* Site backend: EventBridge Scheduler group, scheduler role (send to the wake queue only), reconciler function and role.
- *Blocked by.* B1 (PPY-567bf9)
- *Unblocks.* I2 (PPY-8cf5e2), L1 (PPY-d85860), M2 (PPY-fb1aef), M9 (PPY-d9d78a), N1 (PPY-4d74d9), PPY-1e75aa

**C2 (PPY-3ff011): Follow-up timers: a due time on a record raises one wake**

- *Purpose.* Every wait is a named time on the record that waits (`dueAt`, with `waitingFor`), as the Delivery record already does. One helper turns a due time into a one-shot schedule entry that puts a wake on the queue and deletes itself; setting a new due time replaces the entry; clearing it deletes the entry. It is the same mechanism scheduled publishing uses per Story today, moved into one helper that both use. Nothing polls. The wake key includes the record and the due time.
- *Acceptance.* A record with a due time gets exactly one wake at that time. Moving the time moves the wake; clearing it cancels the wake. Scheduled publishing uses the same helper and behaves as before.
- *Gherkin.* follow-up-timers.feature: a due time raises one wake; a moved time raises one wake at the new time; a cleared time raises none; a wake for a record that no longer waits does nothing; scheduled publishing still publishes on time.
- *Infrastructure as code.* Site backend: one-shot entries in the schedule group; the helper's role may create and delete entries in that group only.
- *Blocked by.* B1 (PPY-567bf9)
- *Unblocks.* A6 (PPY-c023ab), B5 (PPY-67e3cd), C3 (PPY-9b8e59), C4 (PPY-70cd6a), G2 (PPY-9376f8), N6 (PPY-769d1b), PPY-e8ec54

**C3 (PPY-9b8e59): Review request deadlines are timers; open requests are read by index**

- *Purpose.* Today a soft review's deadline is checked only when someone reads the list (`expire_due` runs on every read), and every read lists the whole `ReviewRequest` table, as does every gated publish. Give `ReviewRequest` a sparse `dueAt` and an index on state and time; set a follow-up timer for a soft review's deadline, so 'proceeded without review' happens at the deadline with nobody looking; read open requests by index everywhere (`list_reviews`, the publish gate, recipients). A flag and a hard gate still have no deadline.
- *Acceptance.* A soft review proceeds at its deadline with no page open. The Notification Center and the publish gate read open requests by index. No code path lists the whole `ReviewRequest` table.
- *Gherkin.* review-deadline-timers.feature: a soft review times out at its deadline unattended; an answer before the deadline cancels the timer; a hard gate never times out; the publish gate finds its request by index.
- *Infrastructure as code.* Amplify data schema: one GSI on `ReviewRequest` (its own release).
- *Blocked by.* C2 (PPY-3ff011)
- *Unblocks.* F4 (PPY-ecf852)

**C4 (PPY-70cd6a): Overdue: anything due and untouched is shown and flagged**

- *Purpose.* A lost timer must never be silent. The due indexes (runs, Deliveries, review requests) already list what is waiting. Anything whose due time has passed with no run is 'Overdue': Today shows it, and the operations hygiene agent's daily wake reads the due indexes, re-sends the wake with its original key (so it cannot run twice) and raises one flag per overdue record. This is recovery through the same path, not a second path that does the work.
- *Acceptance.* A record whose timer was lost shows as Overdue on Today. The re-sent wake does the work once. One flag per overdue record, not one per check.
- *Gherkin.* overdue.feature: a due record with no run shows Overdue; the re-sent wake runs once; a record that ran late is no longer overdue; the flag is raised once.
- *Infrastructure as code.* None.
- *Blocked by.* C2 (PPY-3ff011), A5 (PPY-577310)
- *Unblocks.* H2 (PPY-b6d5ad), K1 (PPY-bea2bf), K2 (PPY-f1c774), K3 (PPY-21b8c5), M8 (PPY-50445c)

#### Epic D. Agent definitions, the catalog and generated runbooks (PPY-b05940)

One way to set up an agent: a definition file in Git that fills the 11-point template, validated and applied by the release. Done when every agent on every site comes from a definition file, the inventory page and each runbook are generated from the definitions, and every agent loads the standard context pack plus the site's add-only instructions.

**D1 (PPY-68abaa): The agent definition file and the responsibility catalog**  · first week

- *Purpose.* One file per agent, in Git, validated by a schema. It names: the responsibility (from the engine's catalog), the procedure key, what wakes it (changes and an optional schedule), the serial scope, whether it is paid and whether it is safe to repeat, the operations it uses with the lowest rung each needs, the model tier, and the 11 template lines (trigger, inputs, decision, may write, must never, seen and reversed, records, fails, cost and bound, measured, Gherkin). Core definitions ship in the engine; a site may add its own and may add instructions, never remove a 'must never'. The existing `Automation` record becomes the registered copy of a definition in a site (id, definition version, digest); the fields a person changes live in the agent policy document, not here. A definition that cannot fill a template line fails validation.
- *Acceptance.* A definition missing a template line, naming an unknown operation or an unknown responsibility is refused with the line named. `papyrus agents validate` checks a folder of definitions offline. A site definition can add instructions and cannot delete a 'must never'.
- *Gherkin.* agent-definition.feature: a complete definition validates; a missing 'must never' is refused; an unknown operation is refused; a site addition is accepted; a site removal of a base rule is refused.
- *Infrastructure as code.* None.
- *Blocked by.* A1 (PPY-f58445)
- *Unblocks.* D2 (PPY-df3e74), D3 (PPY-7b05f7), D4 (PPY-dd0653), E2 (PPY-611397), F1 (PPY-51f96f), G4 (PPY-c9c165), H4 (PPY-1dd73a), L1 (PPY-d85860), O4 (PPY-a7174b), PPY-8a374e

**D2 (PPY-df3e74): Definitions are applied by the release**

- *Purpose.* The release registers each definition in the site's backend, as procedures are to be registered on deploy (PPY-1b2edd): an unchanged digest changes nothing; a changed one writes a new registered version; a definition removed from Git is marked retired, its schedule is removed and its history stays. The apply step never touches the agent policy document, so a deploy cannot change a rung or lift a pause. A new agent arrives at rung `off` unless the site's policy already names it.
- *Acceptance.* A release with no definition change writes nothing. A new definition appears at `off` on a site that has no policy line for it. A deploy never changes a rung, a pause or a budget. Each applied definition is the registered copy on its Automation record (id, version, digest and the definition; `agent_definitions/registered.py`, PPY-fba046): the same digest writes nothing and a changed digest writes the next version.
- *Built.* `papyrus agents apply` (`agent_definitions/release.py`), run by the build spec right after the procedure sync: validate, check each procedure is registered, create the automation disabled when missing, `register`, retire what left Git (`definitionRetiredAt`), never the policy document and never adoption.
- *Gherkin.* agent-definitions-on-release.feature: an unchanged definition is a no-op; a changed one becomes a new version (the registered-copy rules are in agent-definition-registered-copy.feature); a removed one is retired and its schedule deleted; a new agent starts `off`; the policy document is untouched.
- *Infrastructure as code.* Site deploy step (the same place procedures are registered).
- *Blocked by.* D1 (PPY-68abaa), PPY-1b2edd
- *Unblocks.* —

**D3 (PPY-7b05f7): Generated runbook per agent and a generated inventory**

- *Purpose.* From a definition, the site policy and the operation table, generate each agent's runbook: what wakes it, its rung on this site and what that allows, what it may write and must never do, how to pause it, how to undo what it did, what 'Outcome unknown' means for it and how to settle one, who it asks. Show it in the newsroom and print it with `papyrus agents runbook --id`. Generate the inventory page from all definitions and replace the hand-written inventory in `docs/automated-processes.md`; a guard test fails when the page and the definitions differ.
- *Acceptance.* Every agent has a runbook that matches its definition and the site's policy. The inventory page is generated; a test fails if it is stale. The runbook is words and marks, readable without the code.
- *Gherkin.* agent-runbook.feature: the runbook names the rung and what it allows; pausing instructions match the operation; a changed definition changes the runbook; the inventory guard fails on a stale page.
- *Infrastructure as code.* None.
- *Blocked by.* D1 (PPY-68abaa), E2 (PPY-611397)
- *Unblocks.* —

**D4 (PPY-dd0653): Every agent loads the standard context pack and the site's add-only instructions**

- *Purpose.* One loader at the start of every run gives the procedure: the section context pack that already exists (recent Stories, top-rated accepted References, core concepts), the guidelines that apply (writing, image, channel), and the site's instructions for this responsibility, which are added on top of the engine's fixed base and stored as a versioned document in S3. The run record names the versions and hashes it loaded. This is the agent's standing memory; nothing else is loaded by default. Works with the Story procedure profile (PPY-7a61ca), which defines add-only instructions for Story steps.
- *Acceptance.* Two agents in one section load the same pack from one code path. A run record names every guideline and instruction version it read. A site's instruction cannot remove a base rule.
- *Gherkin.* agent-context-load.feature: the pack is the same for two agents in a section; the run names the versions it read; a site instruction is added after the base; an attempt to replace the base is refused.
- *Infrastructure as code.* None.
- *Blocked by.* D1 (PPY-68abaa)
- *Unblocks.* —

#### Epic E. Authorization: the autonomy ladder as configuration (PPY-077760)

How far an agent may go is site data, not code: seven rungs (off, observe, propose, draft, prepare, publish with soft review, publish automatically), set per site and responsibility with narrower overrides, in one versioned policy document. One gate at the operation table answers allowed, blocked or human_required. Hard floors hold at every rung. Done when the publish gate, autoAccept, languages.auto and announcementReview are all rungs in the one document and no agent can reach a write except through the gate.

**E1 (PPY-51ea61): The agent policy document: rung, overrides and pause, per site**  · first week

- *Purpose.* One versioned document per site (a `SiteDocument` of kind `agents`, body in S3, admin-only, with who, when and why on every version). For each responsibility it holds the rung: `off`, `observe` (reads and records what it would do), `propose` (files suggestions), `draft` (writes drafts and candidates nobody outside sees), `prepare` (takes work to the door and asks a person), `publish_soft` (goes unless a person stops it in time), `publish_auto` (goes; shown in the digest). Optional overrides narrow it by section, Story type, channel, Announcement kind or list; the narrowest wins. It also holds `paused` per agent and for the whole site, the quiet window, the loop limit, the budget and the model tier (used by later tasks). A new site starts with every agent at `off` or `observe`. Each run records the policy version and rung it ran under. Only an admin may change it; an agent is blocked.
- *Acceptance.* A rung change is a new version with who, when and why. The narrowest matching override decides. A paused agent starts nothing and records why. Every run names the policy version it ran under.
- *Gherkin.* agent-policy.feature: a new site starts quiet; an admin raises a rung with a reason; an editor and an agent cannot; a section override beats the site rung; pausing stops new runs; resuming does not replay skipped ticks; a run records its policy version.
- *Infrastructure as code.* Amplify data: new `SiteDocument` kind (no new table).
- *Blocked by.* nothing; ready to start
- *Unblocks.* B6 (PPY-4af216), E2 (PPY-611397), E6 (PPY-994ff6), G2 (PPY-9376f8), G4 (PPY-c9c165), H3 (PPY-e6f31e), I2 (PPY-8cf5e2), J2 (PPY-3f68f4), L1 (PPY-d85860), PPY-97c0f2, PPY-7a61ca

**E2 (PPY-611397): One gate: each operation names the rung it needs**

- *Purpose.* The operation table (one table behind the CLI, MCP and newsroom) gains, for an agent actor, the lowest rung that allows each operation, and for each a plain rule for doubt. One gate, on the server, receives the operation, the agent and the run, reads the policy once, and answers `allowed`, `blocked` (never for an agent) or `human_required` (a person must do or approve it). On `human_required` the engine raises the review request and the run ends `asked`. The gate is the only way an agent reaches a write. A person's own action is never gated by an agent's rung.
- *Acceptance.* An agent at `propose` asking to write a draft gets `human_required` or `blocked` as the table says, and the write does not happen. Raising the rung allows the same call with no code change. Every gate answer is on the run record.
- *Gherkin.* operation-gate.feature: the same call is refused at a low rung and allowed at a higher one; a blocked operation is blocked at every rung; `human_required` raises one review request and ends the run `asked`; a person's action is not gated; the answer is recorded.
- *Infrastructure as code.* The gate is served by the operation function that already exists, not a new Lambda-backed field (each unshared field costs six resources in the data API function stack, limit 500); operation table data.
- *Blocked by.* E1 (PPY-51ea61), D1 (PPY-68abaa), I4 (PPY-e06835)
- *Unblocks.* D3 (PPY-7b05f7), E3 (PPY-eece43), E4 (PPY-36e7c9), E5 (PPY-8e74bb), H4 (PPY-1dd73a), J3 (PPY-e0c85a), J4 (PPY-33e126), L2 (PPY-e61642), M5 (PPY-77148a), M6 (PPY-18b582), O4 (PPY-a7174b), PPY-97c0f2

**E3 (PPY-eece43): The runner's role reaches only gated operations**

- *Purpose.* The runner's role may call every Query and Mutation field of a site's API today. Narrow it to the gated operation mutations and the reads agents need, so that even a faulty tool cannot write around the gate. The model key stays in SSM, read by the runner process and never given to the model; channel secrets stay write-only as today.
- *Acceptance.* A direct model mutation from the runner's role is refused by IAM. Every agent still works through the gate. No secret appears in a run record or a prompt.
- *Gherkin.* runner-least-privilege.feature: a raw update from the runner role is refused; the gated operation succeeds; a run record contains no key material.
- *Infrastructure as code.* Runner template: IAM policy narrowed (a pipeline-roles change: needs approval after merge).
- *Blocked by.* E2 (PPY-611397)
- *Unblocks.* —

**E4 (PPY-36e7c9): Hard floors hold at every rung**

- *Purpose.* One spec suite that runs every floor against every rung, including `publish_auto`: a machine never sets five stars and lists candidates for a person instead; nothing under three stars, unrated or only predicted reaches a public page or a notification; no 'Approved by' credit is ever written; third-party images are credited; a quotation hold or a translation hold stops that item; doubt (an error-level finding, a contradicted claim, a legal hit, the loop limit) stops automatic publishing and raises a hard gate; a machine never changes an existing concept, never resets a Reference a person decided, never overwrites a block a person pinned; no Message is written by a machine; spend stops at the budget.
- *Acceptance.* Every floor has a scenario at `publish_auto` that fails if the floor is lowered. The floors are in the gate, not in each agent.
- *Gherkin.* hard-floors.feature: one scenario per floor at the highest rung; a five from an agent is refused and listed as a candidate; an unrated item is not announced; doubt raises a hard gate on a fully automatic site.
- *Infrastructure as code.* None.
- *Blocked by.* E2 (PPY-611397)
- *Unblocks.* J5 (PPY-21a2e6), L3 (PPY-924693)

**E5 (PPY-8e74bb): Fold the existing switches into the ladder**

- *Purpose.* Four settings say how automatic something is, each in its own place: the publish gate (`EditorialCheckSettings` `publish-gate`), `autoAccept` in the router config, `languages.auto` for translation, and `publishRequiresRating` (which stays a floor, not a rung). Make the first three rungs in the policy document: publish gate `required` is `prepare`, publish-then-review is `publish_soft`, `not_required` with steps is `publish_auto`; auto-accept on is the intake agent at `publish_auto` for acceptance; `languages.auto` is the translation agent's rung. Convert each site once by a command, in its own release per switch, and delete the old setting and its reader. The announcement review policy joins the same way in PPY-97c0f2.
- *Acceptance.* Each site behaves the same the day after conversion as the day before. The old settings and their readers are gone. One place shows how automatic every responsibility is.
- *Gherkin.* ladder-conversion.feature: a site with the publish gate required converts to `prepare`; a site with auto-accept on keeps accepting; a site with languages.auto keeps translating on publish; converting twice changes nothing.
- *Infrastructure as code.* Router config schema (autoAccept removed), editorial-checks schema (publish-gate removed).
- *Blocked by.* E2 (PPY-611397), B6 (PPY-4af216)
- *Unblocks.* M4 (PPY-98f88e)

**E6 (PPY-994ff6): Promotion evidence: what a person sees before raising a rung**

- *Purpose.* A site starts quiet and is promoted by a person, on evidence. For each agent, `papyrus agents evidence --id` and the agent's page show, from its runs at the current rung: how often people accepted, changed or rejected what it proposed or drafted, with the interval, read by index. The system may say 'ready to promote' when the lower bound of agreement meets the site's target, the same way automatic acceptance learns its threshold; it never promotes by itself. A demotion is one operation and takes effect at the next wake.
- *Acceptance.* The evidence is computed from recorded decisions, not from a fixed count. The system never changes a rung. Demotion takes effect at the next wake.
- *Gherkin.* promotion-evidence.feature: proposals people accepted raise agreement; rejected ones lower it; too little evidence says so; a demotion applies to the next run.
- *Infrastructure as code.* None.
- *Blocked by.* E1 (PPY-51ea61), A5 (PPY-577310)
- *Unblocks.* L4 (PPY-89f253)

#### Epic F. Work items and handoffs between agents and people (PPY-928a91)

Agents talk through durable records, never chat: a checklist step, an Assignment (a request for work), a review request (a question for a person). A person's comment or answer enters the same way. No mailbox object. Done when one agent can ask another for work, hand a step back with a reason, ask a person once and continue from the answer, and a person can take a step over.

**F1 (PPY-51f96f): Assignment is the request between agents**

- *Purpose.* When one agent needs another's work (the fact-checker needs a source found, the copy editor needs a figure), it creates an `Assignment` for that responsibility on the subject, through the gate. `Assignment` already exists with claim, release, complete, cancel, reopen and events; make its kind any responsibility from the catalog. Its creation wakes the responsible agent; the wake key is the claim; completion writes the result on the subject and closes the Assignment, which wakes the asker. A person creates the same record from the newsroom. An Assignment is never a Message.
- *Acceptance.* An agent's request appears on the subject as an Assignment with who asked and why. The responsible agent runs once for it. Completion wakes the asker; a failure is recorded on the Assignment and raises one flag.
- *Gherkin.* assignment-handoff.feature: the fact-checker asks for a source and research runs once; the result returns to the Story; a person files the same request; a failed assignment is not retried by itself.
- *Infrastructure as code.* None.
- *Blocked by.* B3 (PPY-9b9e64), D1 (PPY-68abaa)
- *Unblocks.* K4 (PPY-ce0dd2), M3 (PPY-1e703e)

**F1 built (PPY-51f96f).** `src/papyrus_content/agent_assignments.py` (the operation `handoffs_request`, `begin` and `finish`), `handoff_records.py`, the `Assignment` feed in `change_feeds.py` (`created`, `reopened`, `completed`), and the runner's claim and close in `procedure_runner.py`. See `docs/agent-handoffs.md`. Not built: a newsroom button for a person's request (the same operation is `papyrus handoffs request`), a subject other than a Story, and the agent definitions that listen (K4 and M3).

**F2 (PPY-5cf1a8): Hand a step back with a reason; a person takes a step over**

- *Purpose.* Two record changes cover hand-back and take-over. An agent that finds a problem in an earlier step reopens that checklist step with a reason; the change wakes the step's agent. A person takes a step over by assigning it to themselves; agents then stand down on that step until it is released or closed. Both use the existing checklist sub-task Items, and both are recorded with actor and reason.
- *Acceptance.* A reopened step runs its agent again with the reason in its input. An agent never works a step a person has taken. Releasing the step lets the agent resume.
- *Gherkin.* step-handback.feature: the copy editor reopens fact-check with a reason; the fact-checker runs with that reason; a person takes a step and the agent stands down; release resumes it.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e
- *Unblocks.* —

**F3 (PPY-32b5c1): A person's message steers an agent; the reply is a run card**

- *Purpose.* A person writes a Message on a Story, Reference or Delivery thread. The Message change feed wakes the agents responsible for that subject, with the Message as steering input, inside their rung. The agent's result is the record change it makes; the thread shows a run card (what the agent did, with a link) read from the run record by subject. No Message is written by the machine, in line with the rule that Messages come only from people. The Message's response fields record that it was picked up and by which run.
- *Acceptance.* A person's comment on a Story reaches that Story's agents once. The thread shows what was done without a machine Message. A comment that asks for something above the rung ends `asked`.
- *Gherkin.* message-steering.feature: a comment wakes the Story's agents; the run card appears in the thread; no machine Message exists; a request above the rung raises a review request.
- *Infrastructure as code.* None.
- *Blocked by.* B3 (PPY-9b9e64)
- *Unblocks.* —

**F4 (PPY-ecf852): An answer to a review request wakes the agent that asked**

- *Purpose.* When a run ends `asked`, the review request names the run and the agent. A person's answer (approve, reject, feedback) is a change that wakes that agent with the answer; the run re-reads the records and continues or stops. The request's `appliedIn` names the run that used the answer. Nothing holds a session open while waiting, and a person who never answers blocks only that one item.
- *Acceptance.* An approval continues the work once. Feedback reaches the next run as input. An unanswered request blocks nothing else.
- *Gherkin.* ask-and-answer.feature: an approval wakes the asker and the work completes; a rejection ends it with the reason; feedback is in the next run's input; another Story proceeds while one waits.
- *Built (PPY-ecf852).* `src/papyrus_content/agent_gate/review_answers.py`, read by the runner before a woken run starts: an approval allows, for that run only, the operations the asking run's gate recorded as `human_required` (`GateRun(approvals=...)`, each answer carrying `approvedIn`); a rejection runs nothing and ends `nothing` (`review_rejected`); feedback is the run's `review` input. `appliedIn` names the run that used the answer. What an allowed operation then does is still the gate's E3 slice.
- *Infrastructure as code.* None.
- *Blocked by.* B3 (PPY-9b9e64), C3 (PPY-9b8e59)
- *Unblocks.* F5 (PPY-8d11af)

**F5 (PPY-8d11af): Ask once: agents read what was already said**

- *Purpose.* Before raising a question, the gate looks for an open request on the same subject for the same reason and adds to it instead of opening another. Before drafting, an agent reads what was already said to the audience it is writing for (for announcements, the account's recent sent Deliveries by index). Review requests about one subject are grouped in the newsroom. The aim is a quiet system: few, grouped questions.
- *Acceptance.* The same problem on the same subject raises one request, however many runs meet it. Requests are grouped by subject in the newsroom.
- *Gherkin.* ask-once.feature: two runs with the same doubt raise one request; a different doubt raises a second; an answered request is not reopened by the same finding on the same version.
- *Infrastructure as code.* None.
- *Blocked by.* F4 (PPY-ecf852)
- *Unblocks.* —

#### Epic G. Spend, budgets and model tiers (PPY-6505b3)

Money is a real constraint and the only cap on agent work. One ledger counts spend per site and budget cycle; at the budget, paid work waits for the next cycle and one flag is raised. Which model does which work is configuration. Done when every paid run is counted, a site at its budget stops paid work and says so, and no fixed dollar constant remains in code.

**G1 (PPY-fa165c): One spend ledger**

- *Purpose.* Generalise `AnnouncementSpend` into one ledger: a counter per scope and budget cycle (`ai:<site>`, `ai:<site>:<responsibility>`, `x:<account>`), added to atomically when a run or an attempt finishes. Per-run cost stays on the run record. An unpriced model is named and counted as unknown, never as free. The ledger holds numbers only.
- *Acceptance.* Every paid run adds its cost to the site's cycle once. The X counter keeps working through the same ledger. A run with an unpriced model marks the cycle total as partial.
- *Gherkin.* spend-ledger.feature: a finished run adds its cost once; a redelivered wake does not add twice; an unpriced model marks the total partial; the X account's cycle total is unchanged by the move.
- *Infrastructure as code.* Amplify data: the ledger model (generalised from `AnnouncementSpend`), in a deferred model group so the first-deploy budget is unchanged.
- *Blocked by.* A1 (PPY-f58445), I4 (PPY-e06835)
- *Unblocks.* G2 (PPY-9376f8), G3 (PPY-eef85d), I3 (PPY-04c0d1)

**G2 (PPY-9376f8): At the budget, paid work waits and says so**

- *Purpose.* Before a paid run starts, the gate reads the cycle total. At or over the site's budget the wake is not run: its record becomes `waiting` with `waitingFor: budget cycle` and a due time at the next cycle start, and one flag per cycle tells the admins. Free work continues. Reading, editing and serving are never stopped. Raising the budget is an admin operation and releases the waiting wakes.
- *Acceptance.* A site at its budget starts no paid run and loses none. One flag per cycle. Waiting wakes run when the cycle turns or the budget is raised.
- *Gherkin.* spend-stop.feature: at the budget a paid wake waits; a free check still runs; the flag is raised once; the next cycle runs the waiting wakes in order; raising the budget releases them.
- *Built* (PPY-9376f8): `spend_stop.py` with the spend brake (`spend_brake.py`): the waiting run record keeps its wake (`waitingFor`, `dueAt`, `wake` on ProcedureRun), one cycle timer per site, the flag `rr-budget-<period>-<start>`, release read from the run status index, and `papyrus agents set-budget`. See [procedure runner](../procedure-runner.md#at-the-budget-paid-work-waits-ppy-9376f8-slice-g2). A site with no budget gets $10 a month (Ryan, 2026-11-22), which settles decision 9: a small default rather than none.
- *Infrastructure as code.* None.
- *Blocked by.* G1 (PPY-fa165c), B1 (PPY-567bf9), C2 (PPY-3ff011), E1 (PPY-51ea61)
- *Unblocks.* —

**G3 (PPY-eef85d): Unusual cost is flagged from the agent's own history**

- *Purpose.* Ryan's ruling: an unusually costly Story flags a person and never stops. 'Unusual' is learned: a run or a Story whose cost is far outside the distribution of that agent's own past runs raises one flag with the numbers. Remove the fixed 0.50 dollar guard in `monitoring_stories.py` and make `budgetUsdPerRun` an owner setting that also only flags.
- *Acceptance.* A run far above the agent's history raises one flag and is not stopped. No fixed dollar constant remains in agent code.
- *Gherkin.* unusual-cost.feature: a run within history raises nothing; a far outlier raises one flag with the figures; an agent with little history says so instead of guessing.
- *Built* (PPY-eef85d): `unusual_cost.py`. **The statistic**: the history is the agent's fully priced runs, kept in the spend ledger as three running sums of the log cost (count, sum, sum of squares; numbers only, added in the run's ledger transaction). A run is unusual when its log cost is above the one-sided 99.9% prediction bound for one more run, `mean + t(0.999, n-1) * sd * sqrt(1 + 1/n)`. Why: a run's cost is a product of factors, so it is right-skewed and its logarithm is close to normal; a prediction bound asks the question we mean ("would this agent produce this run?") rather than a confidence bound on the mean; Student's t widens it for a short history, so a young agent is not flagged for ordinary variation; one in a thousand is the meaning of "far". With fewer than two earlier priced runs (no spread can be estimated) the run is not judged and says so. `agents.<responsibility>.budgetUsdPerRun` moved from the Automation record to the agent policy, set by an admin who is a person (`papyrus agents set-budget --agent R --per-run USD`), and also only flags. One flag a run (`rr-run-cost-<digest>`). The 0.50 dollar guards that `monitoring_stories.py` and `ideas/story_plan.py` kept as interim backstops (Ryan, 2026-11-23) are gone (PPY-45c2ef): the monitor-stories job asks the same spend brake before its plan and each step, adds each run to the ledger with the same `watch_run`, and is judged by the same flag (`monitor_stories_spend.py`; agents `monitor_stories` and `monitor_stories_index`). Not covered yet: a Story's cost summed over its runs.
- *Infrastructure as code.* None.
- *Blocked by.* G1 (PPY-fa165c)
- *Unblocks.* —

**G4 (PPY-c9c165): Model tier is configuration**

- *Purpose.* A definition names a tier, not a model: `editorial` (writing and rewriting that readers see), `work` (structured tasks and checks), `bulk` (rating and bookkeeping), `decision` (the trained decision model). The site policy maps each tier to a model id, with the engine's defaults; the price table stays data. Changing a model is a policy change with a version, and each run records the model it used.
- *Acceptance.* Changing a tier's model changes the next run with no deploy. Each run records its tier and model. A model missing from the price table is named, not treated as free.
- *Gherkin.* model-tiers.feature: an agent uses the model its tier maps to; a policy change switches it; the run records both; an unknown model id is refused when saved.
- *Infrastructure as code.* None.
- *Blocked by.* D1 (PPY-68abaa), E1 (PPY-51ea61)
- *Unblocks.* M6 (PPY-18b582)

#### Epic H. Human surface: Today, poke-in operations and explanations (PPY-767813)

One page answers 'what is the system doing today?': waiting for you, overdue, outcome unknown, failed, what ran, what it decided to do nothing about, what it cost. Every poke-in (pause, change a rung, answer, redirect, undo, wake now) is one operation with the same name in the newsroom and the CLI. Done when Ryan can read the day and steer any agent from that page or from `papyrus today` and `papyrus agents`.

**H1 (PPY-5bcf42): Today v1: what ran, what it decided and what it cost**  · first week

- *Purpose.* Add a Today section to the newsroom home (the Notification Center) and a `papyrus today` command, read by index from the run records for the site's day: per agent, how many runs ended acted, nothing, asked, failed and unknown, the cost, and for 'nothing' the reason codes. Each line opens the runs. Words and marks, never colour alone. No subscription; it refreshes on focus and every five minutes.
- *Acceptance.* Ryan can answer 'what did the system do today' from one page. 'Nothing to do' is visible with its reason, not hidden. Every read is an index; the page works on a phone.
- *Gherkin.* today-view.feature: a day with runs shows counts per agent and outcome; a 'nothing' run shows its reason; an agent that did not run shows 'did not run' and why; cost is the sum of the runs; no colour-only status.
- *Infrastructure as code.* None.
- *Blocked by.* A1 (PPY-f58445)
- *Unblocks.* H2 (PPY-b6d5ad), H5 (PPY-ec54ea), N8 (PPY-b53c09)

**H2 (PPY-b6d5ad): Today v2: waiting for you, overdue, outcome unknown, due today**

- *Purpose.* Put first the things that need a person: open hard gates and questions, Overdue records, runs with Outcome unknown, failures not yet acknowledged, and invariant alerts. Then what is due today (schedules, releases, lock times). Read from the attention and due indexes. Each item has its one action beside it (answer, settle, acknowledge, wake now).
- *Acceptance.* The top of Today is the list of things only a person can move. Acknowledging a failure removes it. Due times show in the site's time zone.
- *Gherkin.* today-attention.feature: a hard gate shows under Waiting for you; an overdue Delivery shows Overdue; an unknown run shows with a Settle action; acknowledging clears a failure; due items are in local time.
- *Infrastructure as code.* None.
- *Blocked by.* H1 (PPY-5bcf42), C4 (PPY-70cd6a), A3 (PPY-2d2e55)
- *Unblocks.* J6 (PPY-9922b2)

**H3 (PPY-e6f31e): Poke-in operations: pause, resume, set rung, wake now, redirect, undo**

- *Purpose.* Each is one operation in the operation table, so the newsroom and the CLI have the same names: `agents pause` and `resume` (one agent or the whole site, with a reason), `agents set-rung` (admin, with a reason and optional scope), `agents wake` (run now for a subject), `agents redirect` (give an instruction for a subject; it reaches the next run as steering), and `agents undo --run` (reverses what one run wrote, using the versions and decisions it recorded; anything that cannot be undone, such as a sent email, is listed and not attempted). Each is recorded with who and why.
- *Acceptance.* Every poke-in works the same in the newsroom and the CLI. Undo restores the records a run changed and lists what it cannot reverse. A pause takes effect before the next run starts.
- *Gherkin.* poke-in.feature: pausing stops the next run; set-rung needs an admin; wake now runs once; a redirect appears in the next run's input; undo restores the previous version and names what was already sent.
- *Infrastructure as code.* None.
- *Blocked by.* E1 (PPY-51ea61), B1 (PPY-567bf9)
- *Unblocks.* H5 (PPY-ec54ea), J2 (PPY-3f68f4)

**H4 (PPY-1dd73a): Explain: why did nothing happen?**

- *Purpose.* `papyrus agents explain --subject X [--agent Y]` and a link on each subject answer on demand: which agents listen for this, what each run did, and for anything that did not run, the first rule that stopped it (paused, rung too low, floor not met, budget, waiting for a person, not yet due). It reads the definitions, the policy and the records; no row is written for things that did not happen.
- *Acceptance.* The answer names the rule and where to change it. Nothing is stored to make the answer possible.
- *Gherkin.* agent-explain.feature: an unrated Story explains 'not announced: not rated'; a paused agent explains 'paused by <who>'; a rung too low names the rung needed.
- *Infrastructure as code.* None.
- *Blocked by.* D1 (PPY-68abaa), E2 (PPY-611397)
- *Unblocks.* —

**H5 (PPY-ec54ea): `papyrus today` and `papyrus agents` are generated from the operation table**

- *Purpose.* Generate the `agents` and `today` command groups and the MCP tools from the same operation table the newsroom uses, so there is one definition per operation and the three surfaces cannot drift. `--help` on each is real help, and every write accepts `--dry-run`.
- *Acceptance.* Adding an operation to the table adds it to the CLI, MCP and newsroom. Every write has a dry run.
- *Gherkin.* agents-cli-parity.feature: each operation exists on all three surfaces; a dry run writes nothing; help text comes from the table.
- *Infrastructure as code.* None.
- *Blocked by.* H1 (PPY-5bcf42), H3 (PPY-e6f31e)
- *Unblocks.* —

#### Epic I. Infrastructure as code and the shared tier (PPY-33e622)

Everything the standard needs is in templates applied by the release: queues, dead-letter queues, alarms, the schedule group and its role, change feed mappings, indexes. Nothing is created by hand, including the procedure runner, which today is updated with a hand-run change set. Done when a new site gets working agents from its deploy alone and the shared tier runs the same design with the tenant in every key.

**I1 (PPY-624dab): The procedure runner deploys through the release pipeline**  · first week

- *Purpose.* The `papyrus-procedure-runner` stack is updated today by a hand-run change set, against the rule that nothing is created by hand. Add it to the release pipeline's stack list (`infra/pipeline/stacks.json`) with its allowed-changes entry, so a release builds the image, makes the change set, checks it and executes it, as it does for the monitoring stack. Any role change it needs follows the pipeline-roles approval path.
- *Acceptance.* A release that changes the runner updates the stack with no hand step. A pull request touching it prints the dry run.
- *Gherkin.* (infrastructure; covered by the pipeline's own checks) pipeline dry run lists the runner stack; a Remove or Replace not on the allowed list stops the run.
- *Infrastructure as code.* `infra/pipeline/stacks.json`, `infra/pipeline/allowed-changes.json`, `infra/procedures/papyrus-procedure-runner.yaml`. Pipeline-roles change needs approval after merge.
- *Blocked by.* nothing; ready to start
- *Unblocks.* B1 (PPY-567bf9)

**I2 (PPY-8cf5e2): The shared tier runs the same design with the tenant in every key**

- *Purpose.* On the shared tier (in the existing production account; no new AWS account), one wake queue and one schedule group serve many tenants. The tenant id is part of every message group, wake key, schedule name, ledger scope and policy lookup. Add cases to the cross-tenant isolation suite: a wake for one tenant can never read, write, spend from or be delayed by another's records, budget or pause.
- *Acceptance.* One tenant's burst does not delay another's wakes beyond the shared provider limit. No cross-tenant read or write is possible through a wake. Pausing one tenant pauses only that tenant.
- *Gherkin.* tenant-isolation-agents.feature (added to the adversarial suite): a wake carrying another tenant's subject is refused; budgets are per tenant; a pause is per tenant; a schedule name cannot collide.
- *Infrastructure as code.* Shared-tier foundation stack: queue, schedule group, alarms (held in the stack list until Ryan says go).
- *Blocked by.* B1 (PPY-567bf9), C1 (PPY-2a53cd), E1 (PPY-51ea61)
- *Unblocks.* —

**I3 (PPY-04c0d1): Cost model and tags for agent resources**

- *Purpose.* Tag every agent resource with site and responsibility. Document the unit costs (a queue message, a schedule tick, a run's Lambda time, model spend from the ledger) and show a site's monthly agent cost on its Agents page from the ledger and the tags. An idle agent must cost close to nothing: no polling, no schedule that walks a table.
- *Acceptance.* A site's agent cost is visible by responsibility. An agent with nothing to do makes no model call.
- *Gherkin.* agent-cost.feature: an idle day shows no model spend; cost by responsibility sums to the ledger total.
- *Infrastructure as code.* Tags on queue, schedules, functions; cost attribution config.
- *Blocked by.* B1 (PPY-567bf9), G1 (PPY-fa165c)
- *Unblocks.* —

**I4 (PPY-e06835): Agent resources fit the first-deploy resource budget: one deferred stack, measured**  · first week

- *Purpose.* A brand-new site's first deploy must stay under CloudFormation's limit of 2,500 resources in one stack operation; `scripts/test-bootstrap-stage.ts` holds the first stage under 2,000, and after the Announcement and Delivery models it stands at 1,972, so about 28 are left. The standard adds no core model (its fields and indexes are on models already in deferred groups: procedures, review, tenancy, and the new announcement group), but it adds per-site resources that are not models: the wake queue, its dead-letter queue and alarm, the event source mapping, the schedule group and role, the reconciler, the change feed functions and their mappings, by estimate 30 to 45 resources in all. Put every agent resource in one nested stack, `agents`, that the bootstrap stage leaves out exactly as it leaves out the optional model groups, and that the second deploy adds as an ordinary update. Extend the bootstrap test to assert the agents stack is absent in the first stage, and add a test that prints each agent piece's resource count so the cost of every later slice is known before it merges. Keep new GraphQL fields behind functions that already exist where possible: an unshared Lambda-backed field costs six resources in the data API's function stack, which has its own limit of 500. The budget constant is not raised and no stack is split in this task.
- *Acceptance.* The first-stage count does not rise when agent resources are added. A test reports the resource count of the agents stack and fails if the first stage includes it. The data API function stack stays under its limit with the gate and the agent operations added.
- *Gherkin.* (infrastructure; `scripts/test-bootstrap-stage.ts` and `scripts/test-function-directive-stack.ts` extended) the first stage excludes the agents stack; the second deploy adds it; the per-piece counts are printed.
- *Infrastructure as code.* Site backend: a nested `agents` stack; `PAPYRUS_BOOTSTRAP_STAGE` handling; the two resource-count tests.
- *Blocked by.* nothing; ready to start
- *Unblocks.* B1 (PPY-567bf9), E2 (PPY-611397), G1 (PPY-fa165c)

#### Epic J. Observability, safety and release readiness (PPY-b7039f)

Prove what an agent did and did not do; stop anything fast; turn things on in a safe order. Done when every refusal is on the run record, each kill switch is tested, the invariant checks show on Today, and the release readiness checklist is complete for the first site.

**J1 (PPY-45ef76): Alarms: dead letters, stuck unknowns, change feed lag, budget**

- *Purpose.* One alarm each, defined in the templates and read by the operator listener: a message in any agent dead-letter queue; a run that stays `unknown` and unacknowledged; a change feed whose iterator age grows; the site budget reached. Each alarm names the runbook line that says what to do.
- *Acceptance.* Each condition raises its alarm in a test. Each alarm links to a runbook line.
- *Gherkin.* agent-alarms.feature: a dead-lettered wake alarms; an old unknown alarms; a lagging feed alarms; the budget flag raises once per cycle.
- *Infrastructure as code.* Alarms in the site backend and the shared stack.
- *Blocked by.* B1 (PPY-567bf9), A3 (PPY-2d2e55)
- *Unblocks.* M8 (PPY-50445c)

**J2 (PPY-3f68f4): Kill switches, tested**

- *Purpose.* Three switches, each one operation and each with a test that proves it stops work before the next run or send: pause one agent; pause every agent on a site; pause sending on one channel account (the existing announcement pause). A pause is checked by the runner at the start of a run and by the sender at the start of an attempt. Resuming never replays skipped ticks; waiting records keep their due times. For an agent woken only by changes, resume sends one wake per subject that changed during the pause, found by index from the subject's own updated time, never by walking a table; the wake keys make repeats harmless.
- *Acceptance.* Each switch stops the next run or attempt. A paused send is recorded as waiting, not failed. Resuming does not flood, and work that arrived during the pause is picked up once.
- *Gherkin.* kill-switches.feature: pausing an agent stops its next run; pausing the site stops all; pausing a channel stops the next attempt; resume runs only what is still due.
- *Infrastructure as code.* None.
- *Blocked by.* E1 (PPY-51ea61), H3 (PPY-e6f31e)
- *Unblocks.* J5 (PPY-21a2e6)

**J3 (PPY-e0c85a): Proof of conduct: the run record lists every operation asked, allowed and refused**

- *Purpose.* To prove an agent did nothing wrong, the run record holds the list of operations it asked for, the gate's answer to each, the versions it read and the versions it wrote (names and ids, never text). Together with immutable versions this answers 'what exactly did it do, and under which policy'.
- *Acceptance.* A run's writes can be listed and matched to record versions. A refused operation is visible on the run.
- *Gherkin.* proof-of-conduct.feature: a run lists its allowed and refused operations; each write names the version it created; a run at `observe` lists zero writes.
- *Infrastructure as code.* None.
- *Blocked by.* E2 (PPY-611397)
- *Unblocks.* —

**J4 (PPY-33e126): Observe is the dry run**

- *Purpose.* At rung `observe` an agent runs its real procedure with write operations answered by the gate as 'would do', and records what it would have written. This is the one dry-run mechanism for agents; per-feature dry-run flags are not added.
- *Acceptance.* An agent at `observe` changes no record except its own run. The run shows what it would have done.
- *Gherkin.* observe-rung.feature: an observing agent writes nothing; the run lists the intended writes; raising the rung makes the same procedure write.
- *Infrastructure as code.* None.
- *Blocked by.* E2 (PPY-611397)
- *Unblocks.* —

**J5 (PPY-21a2e6): Release readiness checklist and turn-on order**

- *Purpose.* Write and keep in the repository the checklist that must be true before each thing is turned on in production, and the order: records and outcomes first (no behaviour change); the first agent at `observe` on one site; then `propose`; email in dry run with a test send before a live send; one site before the next; X last, with a watched first post. The checklist is in the architecture document (section 18); this task makes each line a named check or spec and records the evidence on the task.
- *Acceptance.* Each checklist line names the spec or check that proves it. Nothing is turned on without its lines recorded as passed.
- *Gherkin.* (checklist; each line points at an existing feature file)
- *Infrastructure as code.* None.
- *Blocked by.* J2 (PPY-3f68f4), J6 (PPY-9922b2), E4 (PPY-36e7c9)
- *Unblocks.* —

**J6 (PPY-9922b2): Invariant checks on Today for Announcements and Deliveries**

- *Purpose.* Corrections are three ordered conditional writes that a retry finishes, because AppSync has no transaction across writes. Add checks, read by index for one Announcement at a time and run whenever the announce agent wakes for it: a successor Delivery whose predecessor is not marked superseded (finish it); a superseded Delivery still in the due index (clear it); two generations of one channel and account that are both not superseded (never open an attempt on the lower one); a Delivery row whose text file is missing or does not match its hash (do not send; flag); a missing `supersedes` relation (write it). Anything the wake cannot finish shows on Today as 'needs attention' with the two Delivery ids.
- *Acceptance.* A half-finished correction is completed on the next wake without a second post. No attempt opens on a Delivery that is not the highest generation. An inconsistency a wake cannot fix is on Today.
- *Gherkin.* delivery-invariants.feature: a crash after the successor is created is finished on the next wake; the old Delivery leaves the due index; the lower generation is never sent; a row with no text file is not sent and is flagged.
- *Infrastructure as code.* None.
- *Blocked by.* H2 (PPY-b6d5ad), PPY-a570e8
- *Unblocks.* J5 (PPY-21a2e6)

#### Epic K. Lifecycles that run themselves: Reference, Idea, Translation, Illustration (PPY-462d6e)

For each record type: its stages, which agent moves each stage, which stage needs a person by policy, and what happens when nobody acts. (Story is PPY-959e41; Announcement, Delivery and newsletter issues are PPY-a36492 and the newsletters epic.) Done when each lifecycle is written down as data the agents read, a stuck record shows as Overdue with one flag, and no lifecycle step depends on a person running a command.

**K1 (PPY-bea2bf): The Reference lifecycle runs itself**

- *Purpose.* Write the Reference lifecycle as data the agents read: collected, delivered (pending), captured and summarised, predicted, accepted or rejected (by a person, or automatically at the intake agent's rung), rated, grouped. Name the agent that moves each stage and the stage that needs a person. A pending Reference nobody decides is not an error; it stays pending and is counted on Today. A capture that failed for a transient reason has a due time and is retried once by its timer; a final failure waits for a person and shows `capture_failed`.
- *Acceptance.* Each stage names its mover. A Reference stuck between stages shows on Today with its reason. No stage depends on a person running a command.
- *Gherkin.* reference-lifecycle.feature: a new Reference is captured, summarised and predicted without a person; a transient capture failure is retried at its due time; a final failure waits and is visible.
- *Infrastructure as code.* None.
- *Blocked by.* B3 (PPY-9b9e64), C4 (PPY-70cd6a)
- *Unblocks.* —

**K2 (PPY-f1c774): The Idea lifecycle runs itself**

- *Purpose.* Ideas are Items at the `idea` stage. Lifecycle: generated, selected (by an editor, or by the selecting agent at its rung, which must be picky), assigned for research, or spiked with a reason. An idea nobody selects stays an idea; ideas are never auto-spiked for age. The selecting agent compares ideas with the section's mission and recent Stories and takes at most what the site's policy allows.
- *Acceptance.* An idea moves forward only by a person or an agent whose rung allows selection. An unselected idea stays and is counted, never silently removed.
- *Gherkin.* idea-lifecycle.feature: at `propose` the agent recommends ideas and selects none; at a higher rung it selects and assigns research; a spiked idea records why.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e, C4 (PPY-70cd6a)
- *Unblocks.* —

**K3 (PPY-21b8c5): The Translation lifecycle runs itself**

- *Purpose.* A published Story in a site with other languages needs a translation per language: wanted, translating, held (a quotation or a check needs a person), ready, published, stale (the source changed). A new source version marks affected blocks stale and wakes the translator for those blocks only; blocks a person corrected are pinned and never overwritten. A held translation raises one flag and waits; the others proceed.
- *Acceptance.* Every published Story has, per language, exactly one state. A source edit re-translates only what changed. A hold blocks one translation, never the queue.
- *Gherkin.* translation-lifecycle.feature: a publish wants one translation per language; an edit marks only changed blocks stale; a pinned block survives; a hold flags once and others proceed.
- *Infrastructure as code.* None.
- *Blocked by.* B3 (PPY-9b9e64), C4 (PPY-70cd6a)
- *Unblocks.* M4 (PPY-98f88e)

**K4 (PPY-ce0dd2): The Illustration lifecycle runs itself**

- *Purpose.* A Story's Illustration step: needed, candidates made, chosen, placed, with alt text and credit rules checked. When unattended the agent makes one image; when a person is choosing it may make several. A generated image carries no credit; a third-party image is always credited. A request for a figure from another agent is an Assignment.
- *Acceptance.* A Story that needs an image gets candidates without a person asking. The step cannot close with missing alt text or a missing third-party credit.
- *Gherkin.* illustration-lifecycle.feature: a Story entering illustration gets one candidate unattended; a missing alt text keeps the step open; a third-party image without credit keeps it open.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e, F1 (PPY-51f96f)
- *Unblocks.* M5 (PPY-77148a)

#### Epic L. First agent: rating and curation on one site (PPY-24b2ac)

The first real daily agent, end to end, at the lowest rung. It suggests stars for what is unrated (three or four, or five as a candidate) beside the rating; a person rates. Chosen because stars decide everything downstream (home pages, newsletters, announcements), the rule is already written (default three, machines never five), a person's rating always wins, and the model is the cheapest tier. Done when it runs daily on Machines on Machines, was promoted rung by rung on evidence, and its agreement with people is reported.

**L1 (PPY-d85860): Rating agent at observe on Machines on Machines**  · first week

- *Purpose.* The first agent. Definition: responsibility `rate`, tier `bulk`, a daily schedule and no change triggers yet, serial scope `agent`, safe to repeat. Each day it reads, by index, published Stories and accepted References with no rating, and for each decides three stars (the default), four (clearly better), or 'five-star candidate' (never a rating). At `observe` it writes nothing but its run record, which lists what it would rate and why. Machines on Machines is the site because the rating policy was decided for it and it has a backlog of unrated published Stories.
- *Acceptance.* It runs once a day by its schedule and ends `acted` or `nothing`. At `observe` no rating changes. It never proposes five as a rating.
- *Gherkin.* rating-agent.feature: the daily run lists unrated items with a proposed three or four; a strong item is listed as a five-star candidate; a day with nothing unrated ends `nothing`; no rating is written at `observe`.
- *Infrastructure as code.* None beyond the standard.
- *Blocked by.* A2 (PPY-70c6e8), C1 (PPY-2a53cd), D1 (PPY-68abaa), E1 (PPY-51ea61)
- *Unblocks.* L2 (PPY-e61642)

**L2 (PPY-e61642): Rating agent at propose: suggested stars a person confirms**

- *Purpose.* At `propose` the agent stores its suggestion beside the record as a machine suggestion (never in the rating field) and raises one grouped soft review per day: 'N ratings suggested, M five-star candidates'. A person confirms, changes or ignores; a person's rating always wins and is never overwritten.
- *Acceptance.* Suggestions are visible and separate from ratings. One grouped request per day. A person's rating is never changed by the agent.
- *Gherkin.* rating-suggestions.feature: a suggestion appears beside the item; confirming makes it the person's rating; an item a person rated is skipped; candidates are listed, not rated.
- *Infrastructure as code.* None.
- *Blocked by.* L1 (PPY-d85860), E2 (PPY-611397)
- *Unblocks.* L3 (PPY-924693), L4 (PPY-89f253)

**L3 (PPY-924693): Rating agent suggests when a Story is published or a Reference accepted**

- *Owner decision (Ryan, 2026-11-22).* Suggestions only: a machine never writes a rating, at any rung (L2, PPY-e61642). L3 keeps the change triggers.
- *Purpose.* Besides its daily schedule, the rating agent wakes when a Story is published and when a Reference is accepted, and writes its suggestion (`ratings_suggest`, rung `propose`) beside the rating within the quiet window, adding the Story to the day's one review.
- *Acceptance.* A newly published Story gets a suggestion within the quiet window at `propose`. A Story a person rated before the wake gets none. The day's review gains the Story instead of a second review being raised.
- *Gherkin.* rating-suggestion-triggers.feature: a publish wakes the agent and the Story gets a suggestion; a rated Story is skipped; the day's review gains it.
- *Built.* `rate.yaml` (version 3) listens for Item `stage_entered` with `stage=published` (paid, so the wake gate holds it for the quiet window) and for Reference `accepted` (sent at once). A Story's wake rates that Story; a Reference's wake rates the Stories whose `uses_evidence` links name it, read by the relation index (`semanticRelationsByObjectState`): suggestions live beside a Story's rating, and a Reference has no suggestion fields, so the Reference itself is not rated. Each Story is re-read when the run starts; one a person rated, one with a suggestion waiting, one not published now and a translation are skipped and listed in the run record (`rating_agent.py`).
- *Infrastructure as code.* None: the change feeds already wake agents.

**L4 (PPY-89f253): Measure the rating agent against people**

- *Purpose.* Report, from recorded decisions, how often a person kept the agent's suggestion, raised it, lowered it or made a candidate a five, by section. This is the evidence for promotion and the check that the classifier's 'three or better' question is being answered well.
- *Acceptance.* Agreement is reported with its interval. The report reads indexes only.
- *Gherkin.* rating-agreement.feature: kept suggestions count as agreement; changes are broken down by direction; little evidence is reported as such.
- *Infrastructure as code.* None.
- *Blocked by.* L2 (PPY-e61642), E6 (PPY-994ff6)
- *Unblocks.* —

#### Epic M. Every other responsibility as an agent (PPY-11b33b)

Move each existing automated process onto the standard and add the missing ones: intake and capture, ideation, research, translation, illustration, improvement and copy-edit, fact-check, operations hygiene, the knowledge run. Each task ends with the agent running on one site at the rung its site policy names, with its 11-point definition and generated runbook. Done when the hand-written inventory in docs/automated-processes.md is replaced by the generated one and nothing in it runs outside the standard.

**M1 (PPY-ad7087): Intake and capture as an agent**

- *Purpose.* Reference capture, summary and (for papers) citation extraction run today as a procedure the router starts per new Reference. Give it a definition; wake it from the Reference change feed; keep its rules (never change curation status, never overwrite a person's text). Automatic acceptance becomes this responsibility's highest rung, with its learned threshold unchanged.
- *Acceptance.* A new Reference is captured and summarised once. Acceptance happens only at the rung that allows it. Behaviour on Distinctive and the Hacker News sites is unchanged.
- *Gherkin.* intake-agent.feature: a new pending Reference is captured once; a person's pasted text is kept; at a low rung nothing is accepted; at the top rung acceptance follows the learned threshold.
- *Infrastructure as code.* Monitoring stack: router sends wakes.
- *Blocked by.* B3 (PPY-9b9e64), B6 (PPY-4af216)
- *Unblocks.* —

**M2 (PPY-fb1aef): Ideation as an agent**

- *Purpose.* The daily monitor-stories plan runs at 07:30 UTC from a schedule in the monitoring template, and trend stories from the weekly knowledge run. Give ideation a definition with a schedule from data per site; keep plan-then-queue (the plan only plans; one message drafts one candidate) on the wake queue; keep the point check. Remove the fixed schedule from the template once every site's definition carries its own.
- *Acceptance.* Each site's ideation time is site data. Ideas are filed once per candidate. The template no longer holds per-site idea schedules.
- *Gherkin.* ideation-agent.feature: the daily plan runs at the site's time; each candidate is drafted once; a draft that only restates its source is not filed; an empty day ends `nothing`.
- *Infrastructure as code.* Monitoring template: per-publication monitor-stories schedules removed after migration.
- *Blocked by.* C1 (PPY-2a53cd), B6 (PPY-4af216)
- *Unblocks.* —

**M3 (PPY-1e703e): Research as an agent**

- *Purpose.* The research worker polls every five minutes for open assignments. Replace the poll with a wake when a research Assignment is created or reopened. Keep its rules: a failed assignment is not retried by itself, proposed sources go through the Reference identity gate. Remove the five-minute schedule.
- *Acceptance.* A new research Assignment starts research without a poll. An idle site makes no requests for research. A failure is recorded and waits for a person.
- *Gherkin.* research-agent.feature: creating an Assignment starts one run; nothing runs when there are none; a failed run is not retried; a reopened Assignment runs again.
- *Infrastructure as code.* Monitoring template: research-assignments schedule removed.
- *Blocked by.* F1 (PPY-51f96f)
- *Unblocks.* —

**M4 (PPY-98f88e): Translation as an agent**

- *Purpose.* Translation on publish runs from a stream on `LocalizationRequest` into a dispatcher that invokes the runner. Give it a definition; wake it from the feed; its rung replaces `languages.auto`. Whole-site translation becomes many wakes, one per Story and language, never one long run. Holds stay holds.
- *Acceptance.* A publish translates into each configured language once. Whole-site translation is cut per Story and language. The dispatcher's direct invocation is deleted.
- *Gherkin.* translation-agent.feature: a publish wants and starts one run per language; a held translation flags once; whole-site translation queues one wake per Story and language.
- *Infrastructure as code.* Site backend: localization dispatcher replaced by the feed.
- *Blocked by.* B3 (PPY-9b9e64), E5 (PPY-8e74bb), K3 (PPY-21b8c5)
- *Unblocks.* —

**M5 (PPY-77148a): Illustration as an agent**

- *Purpose.* Definition for `illustrate`: woken when a Story's Illustration step becomes ready or an illustration Assignment is created; reads the site's image style profile; makes one image unattended; never places a third-party image without credit; cost on the ledger.
- *Acceptance.* A ready Illustration step gets a candidate without a person. Rules on alt text and credit are enforced by the gate.
- *Gherkin.* illustration-agent.feature: a ready step produces one candidate; at `prepare` a person chooses; at `publish_auto` the candidate is placed if every check passes.
- *Infrastructure as code.* None.
- *Blocked by.* K4 (PPY-ce0dd2), E2 (PPY-611397)
- *Unblocks.* —

**M6 (PPY-18b582): Improvement and copy-edit as an agent**

- *Purpose.* Definition for `improve`: copy editing against the site's policies on a draft (woken by the checklist step), and improvement passes on published Stories (woken by a person's request or a redirect, never by a schedule that walks the archive). Editorial rewriting uses the `editorial` tier; rule checks are free. Every change is a new version with a reason. Articles are never locked: a new event may be folded into any article where it fits, as an Assignment.
- *Acceptance.* A draft's copy-edit step runs when ready. A published Story is improved only on a request or a relevant new event. Every change is a new version a person can revert.
- *Gherkin.* improve-agent.feature: the copy-edit step runs once per version; an improvement request produces a new version; nothing walks the archive on a timer; revert restores the earlier version.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e, E2 (PPY-611397), G4 (PPY-c9c165)
- *Unblocks.* —

**M7 (PPY-396483): Fact-check as an agent**

- *Purpose.* Definition for `fact_check`: woken when the step is ready (after the free sources step), paid, behind the quiet window. A claim that is not verified is held with its reason and raises doubt; doubt stops automatic publishing at every rung. Builds on the paid fact check on drafts (PPY-e4f8c2).
- *Acceptance.* A contradicted claim stops automatic publishing and raises a hard gate. The check runs once per changed claim, after the quiet window.
- *Gherkin.* fact-check-agent.feature: verified claims close the step; a contradicted claim raises a hard gate; an edit re-checks only changed claims.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-8a374e, PPY-e4f8c2, B5 (PPY-67e3cd)
- *Unblocks.* —

**M8 (PPY-50445c): Operations hygiene as an agent**

- *Purpose.* One daily agent, tier `work` with most of its work in code: reads the due indexes for anything Overdue and re-sends the wake; checks the dead-letter queues; reports failed deploys by reading the job log (never retrying); lists runs still `unknown`; reports spend against budget. It writes flags and nothing else. It never retries a deploy, never purges a cache, never touches AWS resources.
- *Acceptance.* Each morning's Today has a hygiene line: clean, or what needs a person. It changes nothing but flags and re-sent wakes.
- *Gherkin.* ops-hygiene-agent.feature: a clean day ends `nothing`; an overdue record is re-woken once and flagged; a dead-lettered wake is reported; it never retries a deploy.
- *Infrastructure as code.* Read access to queue depths and the deploy job log.
- *Blocked by.* C4 (PPY-70cd6a), J1 (PPY-45ef76)
- *Unblocks.* —

**M9 (PPY-d9d78a): The knowledge run as a scheduled agent on the container executor**

- *Purpose.* The weekly knowledge run is compute-heavy and is not a short wake-up. Keep its Step Functions and Fargate executor, and start it through the standard: a definition with a schedule, a wake, a run record with an outcome, the site's pause and budget. The executor is a field of the definition (`lambda` by default, `container` for this). This is the container half of the one run contract (PPY-433383).
- *Acceptance.* The knowledge run starts from a wake and records one run with an outcome. Pausing the agent stops the next run. The projection lease and the stale-checkout guard are unchanged.
- *Gherkin.* knowledge-run-agent.feature: the weekly tick starts one execution; a paused agent starts none; a failed stage ends `failed` before projection.
- *Infrastructure as code.* Knowledge-run stack: started by the wake instead of its own schedule.
- *Blocked by.* C1 (PPY-2a53cd), PPY-433383
- *Unblocks.* —

#### Epic N. Newsletters and subscriptions: weekly, daily and every new item (PPY-79c915)

One system produces a weekly Distinctive Mark email, a weekly and a daily Machines on Machines newsletter, and a message for every new item, all as Announcements and Deliveries sent through Caducus. What differs between them is list data: cadence, time, time zone, rule, working document, rung. Done when all four run in production from settings alone, a reader never gets the same item twice from the daily and every-item lists, and an empty period sends nothing and says so.

**N1 (PPY-4d74d9): A list carries its cadence, time, time zone and rule as data**

- *Purpose.* Every subscription list (a Caducus public-audience list) gets settings in the site's data: `cadence` (`each`: a message for every new item; `daily`; `weekly`), `sendAt` and `timeZone` for the periodic ones, the rule (sections, types, tags, a minimum star rating never under three), `requireReviewedSource`, the working document (`story`, an issue Story that is published to the archive, or `delivery`, no archive page), the template, and optionally its own rung. A periodic list is a scheduled agent wake (the schedule trigger); an every-item list is woken by the page-is-live and rating-changed changes. All of them create an Announcement (model `AnnouncementDecision`) and an email Delivery. Nothing about a cadence is in code.
- *Acceptance.* A new list with a cadence and time needs no code or deploy. A list's minimum rating cannot be set under three. Each cadence produces Announcements and Deliveries of the same shape.
- *Gherkin.* list-cadence.feature: a weekly list wakes at its local time; a daily list wakes daily; an every-item list reacts to a publish; a rule under three stars is refused; changing the time changes the next send only.
- *Infrastructure as code.* Schedule entries come from the list settings through the schedule reconciler.
- *Blocked by.* PPY-3792dd, C1 (PPY-2a53cd)
- *Unblocks.* N2 (PPY-a19b9d), N3 (PPY-b71153), N4 (PPY-1d451f), N5 (PPY-3b928d), N10 (PPY-2c29e5), PPY-cb3cc9, PPY-1e75aa, PPY-58d962

**N2 (PPY-a19b9d): Cadence families: a reader picks one cadence, so nobody gets an item twice**

- *Purpose.* Lists that carry the same items at different cadences (every item, daily summary) form a family. A reader holds at most one list of a family at a time; choosing another moves them. A membership records `since`. A periodic Delivery goes to readers who were members at the period's start; an every-item Delivery goes to members at the moment it is sent. A switch takes effect at the next period start, so an item published after a noon switch and before then still reaches the reader through the list they were on, and their first summary of the new list covers the period that starts then: every item reaches them by exactly one route. A curated weekly newsletter is its own family and may repeat items by design. Enforced in Caducus's preference write (Caducus 0.4.0).
- *Acceptance.* A reader cannot hold two lists of one family. After switching cadence a reader gets no item twice. The weekly newsletter is unaffected by a reader's daily or every-item choice.
- *Gherkin.* cadence-family.feature: choosing daily removes every-item; a noon switch gets no duplicate; a reader on weekly and daily gets both; the rule holds through the one-click unsubscribe path.
- *Infrastructure as code.* Caducus: public-audience preference rule (released through the Caducus release path).
- *Blocked by.* N1 (PPY-4d74d9), PPY-824c14
- *Unblocks.* N7 (PPY-2f9b22)

**N3 (PPY-b71153): Period keys in the list's time zone; what was not sent carries forward**

- *Purpose.* The once-only key of a periodic Announcement uses the list's local date: `roundup:<list>:<yyyy-ww>` for weekly, `roundup:<list>:<yyyy-mm-dd>` for daily, from the scheduled local time and not from UTC or from when the run happened. An item is eligible for a list's next issue if it qualified since the list's last sent Delivery, not 'this calendar period'. So a week that was never released is not lost: when the next period's Announcement is created, the unreleased one is cancelled with the reason 'not released before the next period; items carried forward' and its items are eligible again.
- *Acceptance.* A send delayed past midnight still belongs to its scheduled period. A skipped period's items appear in the next issue. Two ticks for one period make one Announcement.
- *Gherkin.* period-keys.feature: a late run keeps its period key; a clock change does not make two issues or none; an unreleased weekly issue is cancelled when the next begins and its items carry forward.
- *Infrastructure as code.* None.
- *Blocked by.* N1 (PPY-4d74d9)
- *Unblocks.* N5 (PPY-3b928d), PPY-1e75aa

**N4 (PPY-1d451f): An empty period sends nothing and says so**

- *Purpose.* When a periodic list has no qualifying item and no content a person wrote, nothing is sent: the run ends `nothing` with the reason 'no items reached the list's bar', and Today shows it. A list may instead be set to `emptyPeriod: draft_only`, which creates the draft for a person to fill and sends only if a person adds content and the rung allows. No placeholder issue is ever sent.
- *Acceptance.* An empty period produces no email. The reason is visible on Today. A person's own content makes a period non-empty.
- *Gherkin.* empty-period.feature: no qualifying items sends nothing and records why; `draft_only` creates a draft and sends nothing by itself; a person's note makes the issue sendable.
- *Infrastructure as code.* None.
- *Blocked by.* N1 (PPY-4d74d9), A1 (PPY-f58445)
- *Unblocks.* N5 (PPY-3b928d)

**N5 (PPY-3b928d): The daily summary list**

- *Purpose.* A `daily` list for a site, first on Machines on Machines: each day at the list's time the assembler fills the day's slots from items that qualified since the last sent summary (three stars or better, reviewed sources where the list requires it), best first, in a Delivery-only working document. The rung decides the rest: at `publish_soft` it locks and sends at the send time unless a person stops or edits it; at `prepare` a person releases it. Uses the same assembly, lock, attempt and fan-out as the weekly issue.
- *Acceptance.* A day with items produces one summary to the daily family's members. A day with none sends nothing. The same code path as the weekly issue, different list data.
- *Gherkin.* daily-summary.feature: items since the last summary appear once, best first; an item already in a sent summary is not repeated; soft review silence sends at the send time; a stop holds it.
- *Infrastructure as code.* None beyond N1.
- *Blocked by.* N1 (PPY-4d74d9), N3 (PPY-b71153), N4 (PPY-1d451f), PPY-cb3cc9
- *Unblocks.* N9 (PPY-00817a)

**N6 (PPY-769d1b): Every-item lists: quiet hours and spacing**

- *Purpose.* An `each` list may set `quietHours` in its time zone. A Delivery that becomes ready inside them waits (`waitingFor: quiet hours`) and is released when they end, in order, with the channel's spacing setting between messages. Both settings are empty by default. Combining held items into one message is not built: a reader who wants fewer messages chooses the daily summary.
- *Acceptance.* Nothing is sent to an every-item list inside its quiet hours. Held messages go out in order when quiet hours end. With no setting, messages go at once.
- *Gherkin.* quiet-hours.feature: a night-time publish waits until morning; three held items are sent in order with spacing; no quiet hours means immediate send; a clock change keeps the local hours.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-58d962, C2 (PPY-3ff011)
- *Unblocks.* N9 (PPY-00817a)

**N7 (PPY-2f9b22): Preferences: choose a cadence; consent is never assumed**

- *Purpose.* The reader's preferences page shows each family as one choice (every new item, daily summary, off) and each newsletter as a tick. Changing cadence inside a family the reader already consented to needs no new confirmation; joining a new family or newsletter does. A reader is never enrolled in a list by a migration or a new feature: a new list starts empty. Consent evidence (wording, time, form) is stored per family.
- *Acceptance.* A new list has no members until readers choose it. Switching cadence keeps consent; a new family asks for it. Unsubscribe from one message removes that list only; 'unsubscribe from everything' removes all.
- *Gherkin.* subscription-preferences.feature: a new daily list starts empty; a weekly subscriber is not added to it; switching every-item to daily needs no new opt-in; joining a new family sends a confirmation; one-click unsubscribe is honoured before the next send.
- *Infrastructure as code.* Caducus and the notifications plugin pages.
- *Blocked by.* N2 (PPY-a19b9d)
- *Unblocks.* N9 (PPY-00817a)

**N8 (PPY-b53c09): Counts and suppression on the Delivery; one Today line per send**

- *Purpose.* Caducus keeps the per-reader record. The email Delivery holds counts only (queued, sent, failed, suppressed, skipped, delivered, bounced, complained), updated from Caducus, and its outcome. Today shows one line per send: list, items, counts, cost. A suppressed or unconfirmed reader is counted and never mailed; a reader on two matching lists of one Delivery gets one message.
- *Acceptance.* The Delivery's counts match Caducus's records. A suppressed reader is counted as suppressed and not mailed. Today shows each send with its counts.
- *Gherkin.* delivery-counts.feature: counts match the transport's records; a suppressed address is not mailed; a reader on two lists gets one message; a complaint suppresses the reader for later sends.
- *Infrastructure as code.* None.
- *Blocked by.* PPY-a570e8, H1 (PPY-5bcf42)
- *Unblocks.* N9 (PPY-00817a)

**N9 (PPY-00817a): Five end-to-end walkthrough specs**

- *Purpose.* One narrative feature file per use case, run against the real records with fakes only at the provider edge: the weekly Distinctive Mark email; the weekly Machines on Machines newsletter (hard review, reviewed sources); the daily Machines on Machines summary; the every-new-item subscription; and 'announced right away, then massaged' (the learning loop). Each follows the walkthrough in the architecture document, from the timer or change to the Today line, including nobody acting, a correction and a duplicate trigger.
- *Acceptance.* All five pass using the same records and agent standard, with only list and policy data differing. Each includes the nobody-acts path.
- *Gherkin.* walkthrough-weekly-distinctive.feature; walkthrough-weekly-mom.feature; walkthrough-daily-mom.feature; walkthrough-every-item.feature; walkthrough-announce-then-massage.feature.
- *Infrastructure as code.* None.
- *Blocked by.* N5 (PPY-3b928d), N6 (PPY-769d1b), N7 (PPY-2f9b22), N8 (PPY-b53c09), O3 (PPY-d99bd0)
- *Unblocks.* PPY-e7eaa3

**N10 (PPY-2c29e5): One working document per list**

- *Purpose.* The assembler and editors work on one document per issue. For a list set to `story`, it is the issue Story on the board all period (Ryan's living issue), and the email Delivery renders an approved version of it; after the send it is published to the archive. For a list set to `delivery`, it is the Delivery's own text versions and there is no archive page. Slots, pins and removed-item records use the same block marks in both, so one assembler serves weekly and daily.
- *Acceptance.* A weekly issue is a Story on the board during the week. A daily summary makes no Story and no archive page. Pins and removals behave the same in both.
- *Gherkin.* list-working-document.feature: a `story` list creates one issue Story per period; a `delivery` list creates none; a pinned slot survives a refill in both; a removed item is never re-added in both.
- *Infrastructure as code.* None.
- *Blocked by.* N1 (PPY-4d74d9), PPY-e8ec54
- *Unblocks.* PPY-cb3cc9

#### Epic O. Announcements learn from a person's edits (PPY-f51641)

When a person rewrites how something is announced, future announcements change, and never silently. An edit becomes an example only when a person says so; a pattern becomes a proposed guideline file an admin accepts; every draft names the guideline versions and examples it read; every learned thing can be turned off. Done when Ryan can edit one announcement, choose its scope, see the next draft follow it, and undo it.

**O1 (PPY-627bbc): Capture what a person changed in an announcement, and how far it should reach**

- *Purpose.* When a Delivery is sent (or a preferred version is saved) with a person's changes, record on the Delivery, once: the machine draft version, the final version, and the person's choice of scope, asked in one tap when they save: 'just this one', 'this channel', 'this kind on this channel', or 'the whole publication', with an optional one-line reason (stored with the text version in S3). No choice means 'not decided': the edit is kept as a candidate and changes nothing. The difference between the two versions is computed from the stored versions when needed, not stored again.
- *Acceptance.* An edited Delivery records which version was the machine's and which was sent. With no scope chosen, nothing about future drafts changes. The reason text is not in the catalog row.
- *Gherkin.* delivery-edit-capture.feature: an edit with scope 'this channel' is recorded as an example for that channel; an edit with no scope is a candidate; an unedited send records nothing; the reason is stored in S3.
- *Infrastructure as code.* Amplify data: short fields on `Delivery` (`exampleScope`, `exampleState`, `machineVersion`); one sparse index for active examples, in its own release.
- *Blocked by.* PPY-e8ec54
- *Unblocks.* O2 (PPY-75a314), O3 (PPY-d99bd0)

**O2 (PPY-75a314): Preferred version: teach without sending again**

- *Purpose.* After a Delivery is sent, a person may save how it should have read, as a 'preferred version' that is never sent. This is how 'announced right away, then massaged' works when the message is already out: an email cannot be recalled and a new post costs money and attention. The person chooses separately whether to also correct the public post (a superseding Delivery, where the channel can delete) or only to teach.
- *Acceptance.* Saving a preferred version sends nothing and changes no public text. It can be used as an example exactly like an edit made before sending. Correcting and teaching are separate choices.
- *Gherkin.* delivery-preferred-version.feature: a preferred version on a sent email sends nothing; it becomes an example when given a scope; choosing 'correct' on X makes a superseding Delivery and deletes the old post.
- *Infrastructure as code.* None.
- *Blocked by.* O1 (PPY-627bbc)
- *Unblocks.* —

**O3 (PPY-d99bd0): Examples reach the drafter, and every draft names what it read**

- *Purpose.* The drafter loads, for the channel, kind and publication it is writing for: the guideline files that apply, and the active examples for that scope, newest first, within the context pack's budget. Each Delivery records the guideline ids, versions and hashes and the example ids it was drafted under. `papyrus announcements explain --delivery X` prints them. An example that an accepted guideline was derived from is marked absorbed and is no longer loaded by itself.
- *Acceptance.* A draft after an example with matching scope follows it; a draft outside the scope does not load it. Every draft is explainable by listing what it read. Absorbed examples are not loaded.
- *Gherkin.* drafter-examples.feature: an example for channel X is loaded for X and not for email; the Delivery lists the examples it read; an absorbed example is skipped; turning an example off removes it from the next draft.
- *Infrastructure as code.* None.
- *Blocked by.* O1 (PPY-627bbc), PPY-9c6b89
- *Unblocks.* N9 (PPY-00817a), O4 (PPY-a7174b)

**O4 (PPY-a7174b): The learner proposes guideline changes, tested against history**

- *Purpose.* A learner agent wakes once per sent Delivery that has a person's changes with a scope wider than 'just this one'. It may propose a guideline file (in the guideline file standard, scope `channel/<name>` or publication) in two cases: the person gave a reason with a wide scope, or the same kind of change has now been made on more than one Delivery. Before proposing, it tests the rule against the account's past Deliveries that people sent unchanged: a rule that would have flagged what people approved is contradicted and is not proposed, or is shown with the conflicts. A proposal is a Proposal of kind `guideline_change` with the file diff; an admin accepts it (a new guideline version, `learnedFrom` naming the Deliveries) or rejects it (remembered, not proposed again without new evidence). A learned rule starts as `guidance` or `warn`, never `error`, and can never loosen a floor. Nothing changes the drafter's rules without an admin's acceptance.
- *Acceptance.* One edit with no stated reason proposes no rule. A proposed rule shows the evidence for it and any evidence against it. Accepting writes a new guideline version; rejecting is remembered.
- *Gherkin.* learned-guidelines.feature: a single unexplained edit proposes nothing; a stated reason with channel scope proposes a rule; a repeated change proposes a rule; a rule contradicted by approved history is not proposed; acceptance creates a guideline version; rejection is not repeated.
- *Infrastructure as code.* None.
- *Blocked by.* O3 (PPY-d99bd0), PPY-1d5c43, D1 (PPY-68abaa), E2 (PPY-611397)
- *Unblocks.* O5 (PPY-e705a8), O6 (PPY-c1cbf1)

**O5 (PPY-e705a8): Undo and health for what was learned**

- *Purpose.* A page and commands list everything the drafter has learned for a publication: active examples and learned guidelines, each with who, when, where it came from and how it is doing (of the drafts written under it, how many were sent unedited and how many were changed, read by the account index). One action turns an example off or retires a learned guideline (a new guideline version without it). Both take effect at the next draft and are recorded.
- *Acceptance.* Ryan can see every learned item and switch any one off. Retiring a rule changes the next draft and is recorded with who and why. Health is computed on demand from stored Deliveries.
- *Gherkin.* learned-undo.feature: turning an example off removes it from the next draft; retiring a rule makes a new guideline version; health shows edited versus unedited drafts under a rule.
- *Infrastructure as code.* None.
- *Blocked by.* O4 (PPY-a7174b)
- *Unblocks.* —

**O6 (PPY-c1cbf1): A later edit against a learned rule proposes narrowing it**

- *Purpose.* When a person's edit undoes what a learned rule made the drafter do, the learner proposes narrowing or retiring that rule, with the edit as evidence. This is the guard against drift: learned rules are held to the same evidence that created them, and the proposal again waits for an admin.
- *Acceptance.* An edit that contradicts a learned rule raises one proposal to narrow or retire it. Nothing is narrowed without acceptance.
- *Gherkin.* learned-contradiction.feature: an edit against a learned rule proposes narrowing; repeated contradiction strengthens the proposal instead of opening another; acceptance changes the next draft.
- *Infrastructure as code.* None.
- *Blocked by.* O4 (PPY-a7174b)
- *Unblocks.* —


---

## 13. Open decisions for Ryan

Each has a default. Silence means the default.

| # | Decision | Default |
|---|---|---|
| 1 | The first agent | **Rating, on Machines on Machines**, starting at `observe`. Stars decide everything downstream, the rule is settled, a person's rating always wins, and it is the cheapest model. |
| 2 | The outcome word for "it did the work" | `acted`, shown as "Did it". A Delivery attempt keeps `sent`. |
| 3 | Where the rung lives | One versioned policy document per site. Not on each Automation record. |
| 4 | May a deploy ever change a rung? | No. A new agent arrives `off`. |
| 5 | May an agent reply in a thread when a person addressed it? | No Message. The thread shows a run card. |
| 6 | A mailbox object for agents | No. Records are the mailbox. |
| 7 | An interrupted run that is not safe to repeat | Mark it Outcome unknown and flag once. Never run it again by itself. |
| 8 | The loop limit per Story | Keep today's default of 5 as the starting owner setting; at the limit a hard gate. It is a safety guard, set by the owner, not by code. |
| 9 | The site's AI budget and cycle | **Decided (Ryan, 2026-11-22):** monthly, per site, set by the owner; a site with no budget gets $10 a month. At the budget, paid work waits (PPY-9376f8). |
| 9a | System wakes with no adopted agent | **Decided (Ryan, 2026-11-22):** the engine's own follow-up wakes (`review-deadline`, `deliver`) run with no adopted Automation, on an explicit engine list only (`engine_follow_ups.py`); a paused site still stops them. |
| 9b | Machine ratings | **Decided (Ryan, 2026-11-22):** a machine never writes a rating; the rating agent suggests and a person rates. |
| 9c | Human review on Machines on Machines | **Decided (Ryan, 2026-11-22):** not required, for posts or translations (the procedure document makes `review_people` and `rated` optional). Configurable per site. When a person does review, they join the byline. |
| 9d | Announcement schedule | **Decided (Ryan, 2026-11-22):** an announcement is drafted and scheduled automatically and posts on schedule unless a person steps in (review `soft`, edit window per kind and channel); Machines on Machines: 60 minutes, locked 5 before. Sites that need approval keep `hard`. |
| 10 | Which model each tier uses | `work`: GPT-6 Luna (today's default). `bulk`: the cheapest available. `editorial`: Ryan chooses; it needs an API key and budget of its own. `decision`: Jev. |
| 11 | Machines on Machines daily summary: time and rung | 6:00 AM Eastern; `publish_soft` (every source is already reviewed and three stars or better; silence sends it). |
| 12 | Every-item email on Machines on Machines: floor and rung | Three stars, reviewed source required, `publish_auto` (this is "announced right away"). X stays five stars and off. |
| 13 | May a reader hold both "every item" and "daily"? | No. One cadence per family. That is how nobody gets an item twice. |
| 14 | Quiet hours for every-item lists | None by default. An owner may set them. |
| 15 | An empty period | Send nothing and say so on Today. |
| 16 | A weekly issue nobody released | Cancel it when the next period begins; its items carry forward. |
| 17 | The scope question when a person edits an announcement | Asked in one tap on save. No answer means "not decided": kept as a candidate, changes nothing. |
| 18 | When the learner may propose a rule | When a person gave a reason with a wide scope, or the same change has been made on more than one Delivery, and the rule does not contradict what people approved before. |
| 19 | Rename `AnnouncementDecision` to `Announcement` after the old X model is deleted? | **No.** A rename is a new table and a data move for no gain. The model is `AnnouncementDecision`; people see "Announcement". |
| 20 | Local pods and unattended agents | None. A pod is manual. |
| 21 | Email nudges before Caducus milestone 3 | Wait. Today is the surface until then. |
| 22 | Order of production turn-on | Section 18. |

---

## 14. What I could not verify

- **The article's exact words.** The fetch tool returns an outline written by a small model. The structure matches the brief's summary. I quote nothing.
- **SQS FIFO as the single-worker mechanism with Lambda.** I rely on documented behaviour (one in-flight batch per message group; maximum concurrency on the mapping). Not tested here. Slice B1's specs test it.
- **EventBridge Scheduler targeting a FIFO queue with the scheduled time as the deduplication id.** Documented behaviour; not tested here. If the context attribute cannot be used that way, the key is still made from the scheduled time inside the message body and the run record's condition still makes it once-only.
- **That all seven sites share one AWS account with the runner.** Memory notes say four sites moved to the production account in October; Humorus is elsewhere. Slice I1 checks.
- **The two-reader guidance for DynamoDB streams** as it applies to Lambda event source mappings at this volume.
- **Whether Tactus can suspend and resume a procedure.** I designed so it does not need to.
- **Whether anything stops an agent setting five stars today.** I did not find a refusal in the files I read. Slice E4 makes it a test either way.
- **Live data.** I made no AWS calls. "No live X rows", "sent issues exist on Shipped and Distinctive" and subscriber counts come from documents and memory notes.
- **Caducus's code.** I read Papyrus's documents about it, not the Caducus repository. The cadence-family rule (slice N2), the attempt id shape and the reconcile step are requests to Caducus.
- **The epic's task count.** The brief says 20. The board shows 21 under PPY-a36492, because the pod base task PPY-4834f3 was added.
- **PPY-24fdf4.** The brief calls it the automated-processes standard. On the board it is "De-duplicate and group References". The inventory page names it as its epic. I relate it to the intake agent and do not re-parent it.
- **`process_story` in the announcements engine** has no call site in this worktree [V by search]. The X path is not wired to publishing here, which agrees with "X is off".

---

## 15. Five use cases, one system

All five are the same records: an **Announcement** (model `AnnouncementDecision`) with an email **Delivery**, sent through Caducus, drafted and released by the announce and newsletter agents under the standard. What differs is data.

### 15.1 The settings that differ

| | Weekly Distinctive Mark | Weekly MoM | Daily MoM | Every new item (MoM) |
|---|---|---|---|---|
| List `cadence` | `weekly` | `weekly` | `daily` | `each` |
| Wake | Schedule: the list's time | Schedule: Monday 4:00 AM Eastern | Schedule: 6:00 AM Eastern [default] | Change: page is live; rating changed |
| Once-only key | `roundup:<list>:<yyyy-ww>` | same | `roundup:<list>:<yyyy-mm-dd>` | `story-published:<lineage>` |
| Working document | `story` (the issue Story) | `story` | `delivery` (no archive page) | `delivery` |
| Rule | Site's sections; three stars or better | Three stars or better; reviewed sources | Same | Same |
| `requireReviewedSource` | Off | On | On | On |
| Rung | `prepare` (today's behaviour: an admin approves) | `prepare` | `publish_soft` | `publish_auto` |
| Family | Its own | Its own | "New stories" | "New stories" |
| Edit window | The week | The week | From the first slot to the lock time | None by default |
| Empty period | Send nothing | Send nothing | Send nothing | (does not apply) |

### 15.2 Weekly Distinctive Mark email

1. **Through the week.** The newsletter agent is woken by each Story that qualifies (the page is live, three stars or better). It adds a slot to the week's issue Story, best first, with a blurb. Bursts are folded: ten Stories in a minute refill once.
2. **People.** Editors reorder, rewrite, pin, remove. A pinned slot survives every refill. A removed item is never re-added.
3. **The tick.** At the list's time the schedule puts one wake on the queue. Key: the list and the local week. A second tick for the same week finds the same Announcement.
4. **Rung `prepare`.** The agent makes sure the Announcement and its email Delivery exist and are `ready`, and raises one hard gate: "This week's issue is ready." It shows under Waiting for you.
5. **A person approves** a version and a send time. The lock time arrives: the approved version is locked. An edit after that needs an unlock.
6. **Send.** At the release time the engine opens attempt 1, written as `started` before the call. Caducus fans out page by page over the list's confirmed readers. A suppressed or unconfirmed reader is counted and not mailed. Each reader's send is claimed before the provider call, so a reader is mailed once.
7. **Result.** Counts land on the Delivery. The attempt closes `sent`. The issue Story is published to the archive; that page's address is the Delivery's result address.
8. **Nobody acts.** Nothing is sent. The gate stays open and shows as Overdue after the intended time, with one flag. When next week's issue begins, this one is cancelled with a reason and its items carry forward.
9. **Correction.** Email cannot be recalled. A factual error gets a short correction Delivery that says it is a correction; it supersedes the first.
10. **Today.** "Weekly newsletter · sent 7:02 AM · 6 items · 412 delivered, 3 suppressed, 1 bounced."

Distinctive has sent issues in the old rows. They are converted once, with sends frozen for that window (PPY-1e75aa).

### 15.3 Weekly Machines on Machines newsletter

The same ten steps. Three settings differ:

- The tick is **Monday 4:00 AM Eastern** (Ryan, 2026-11-12).
- **`requireReviewedSource` is on.** A Story no person has reviewed gets no slot. A Story edited after review loses its stamp and its slot waits until it is reviewed again.
- It is a **living issue**: a Story on the board all week, getting updates from the agent and from people (Ryan, 2026-11-12).

When nobody acts, nothing goes out. That is the point of `prepare` on this site.

### 15.4 Daily Machines on Machines summary

1. **Through the day** the agent fills the day's slots in a Delivery-only working document from items that qualified since the last sent summary.
2. **The tick** at 6:00 AM Eastern. Key: the list and the local date.
3. **No items**: the run ends `nothing`, reason "no items reached the list's bar". Today shows it. Nothing is sent. No placeholder.
4. **Items, rung `publish_soft`.** The Delivery is `ready` with a short edit window that ends at the lock time. A person may edit or stop it. Silence means the current version is approved by policy at the lock time, recorded as such, then locked and sent.
5. **Send, counts, Today**: as the weekly.
6. **Members.** A daily Delivery goes to readers who were members when the period began.

### 15.5 A message for every new item

1. **A Story's page goes live** (or its rating reaches the bar later). The change feed wakes the announce agent. Key: the Story's lineage. A republish finds the same Announcement.
2. **Eligibility.** Three stars or better, rated by a person or by the rating agent at a rung that writes; reviewed source where the list asks for it. Not eligible: no row, and `papyrus agents explain` says which rule.
3. **One Announcement, one Delivery per channel.** The email Delivery's audience is every `each` list whose rule matches. A reader on two of them gets one message. If X is on and the Story has five stars, an X Delivery joins the same Announcement.
4. **Rung `publish_auto`.** Approved by policy at creation, released at once. This is "announced right away".
5. **Quiet hours**, if the list has them: the Delivery waits with a reason and is released when they end, in order.
6. **Consent and suppression** are Caducus's: confirmed readers only, one-click unsubscribe, a bounce or complaint suppresses.
7. **No item twice.** A reader holds one cadence in the "New stories" family: every item or the daily summary (slice N2).
8. **Today.** "Announce · 'Agents that lie' · email sent to 212 · X: not eligible (four stars)."

### 15.6 Announced right away, then massaged

This is the fifth use case. Its mechanics are section 16. The walkthrough:

1. Ryan publishes an item. It qualifies. It is announced at once (15.5).
2. He opens the sent Delivery and does not like the hook. He rewrites it as a **preferred version**. Nothing is sent again.
3. On save he is asked one thing: how far should this reach? He taps "this channel" and types "lead with the finding, not the paper's title".
4. Because he gave a reason with a wide scope, the learner proposes one guideline file for that channel, shows the evidence, and waits. He accepts it.
5. The next item's draft loads that guideline and his example. The Delivery records that it did.
6. If the first post was actually wrong, not merely dull, he also chooses **Correct**: on X the old post is deleted and a superseding Delivery is posted; by email a correction notice goes out.
7. Later he edits a draft the other way. The learner proposes narrowing the rule. He decides.
8. At any time he opens "What the drafter has learned", sees each rule and example with how it is doing, and turns any of them off.

### 15.7 What these use cases needed that the designs lacked

Each is now in the plan.

| Need | Added as |
|---|---|
| A list's cadence, time and time zone as data; `daily` as a cadence | N1 |
| One cadence per reader per family, and membership `since`, so nobody gets an item twice | N2 |
| Period keys in local time; carry forward what was not sent | N3 |
| Empty period: send nothing, say so; optional draft-only | N4 |
| A working document that is either an issue Story or the Delivery itself | N10 |
| Quiet hours and spacing for every-item lists | N6 |
| Consent per family; never enrol silently | N7 |
| Counts on the Delivery; one Today line per send | N8 |
| List as the narrowest scope for a rung | E1, PPY-97c0f2 |
| A preferred version on a sent Delivery | O2 |
| Scope and reason on an edit; examples; a learner; undo | O1, O3, O4, O5, O6 |
| System approval at the lock time under soft review | PPY-e8ec54 (added to its text) |
| Per-reader time zones | Not built. The list has one time zone. A reader's zone is personal data we do not hold. |
| Combining held every-item messages into one | Not built. The daily summary is that product. |

---

## 16. How an edit changes future announcements

The rule: **never silent self-modification.** Three layers, each visible and each reversible.

### 16.1 What is captured

When a Delivery is sent with a person's changes, or a preferred version is saved (slices O1, O2):

| Captured | Where |
|---|---|
| The machine's draft version and the final version | Already stored as text versions in S3. The row names which is which. |
| The scope the person chose | A short field: `this one`, `this channel`, `this kind on this channel`, `publication`, or not decided. |
| The reason, if given | With the text version in S3. |
| Who and when | On the version. |

The difference between draft and final is computed from the two versions when needed. It is not stored a second time.

### 16.2 How it becomes durable guidance

| Layer | What it is | How it starts | Effect on the drafter |
|---|---|---|---|
| **Candidate** | An edit with no scope chosen | Automatically | None. Listed for an admin. |
| **Example** | An edit a person gave a scope wider than "this one" | The person's tap | Loaded as an example for that scope, newest first, within the context budget. |
| **Guideline** | A `GUIDELINE.md` file scoped to a channel or the publication, with `learnedFrom` naming the Deliveries | Proposed by the learner; accepted by an admin | Read by the drafter and the checker like any guideline. |

A person choosing a scope is an explicit instruction, so an example is not silent. A guideline needs an admin's acceptance.

### 16.3 How the drafter reads it

For the channel, kind and publication it is writing for (slice O3): the guideline files that apply, then the active examples for that scope. The Delivery records every guideline id, version and hash and every example id. `papyrus announcements explain --delivery` prints them. So "why did it write this?" always has an answer.

### 16.4 Avoiding overfitting to one edit

- One edit with no reason proposes **no rule** (slice O4). It can be an example if the person says so; it is not a rule.
- A rule is proposed when the person **stated** one (a reason with a wide scope), or when the **same kind of change** has been made on more than one Delivery.
- Before proposing, the learner **tests the rule against history**: the account's past Deliveries that people sent unchanged. If the rule would have flagged what people approved, it is contradicted. It is not proposed, or it is shown with those conflicts.
- A learned rule starts at `guidance` or `warn`. Never `error`. Only an admin raises it.
- A learned rule can never loosen a floor, and a section rule never loosens a publication rule (the existing layering).
- An example is **absorbed** when a guideline is made from it and is no longer loaded by itself, so the set of active examples stays small.

### 16.5 Undo

- Turn an example off: one action; the next draft does not load it (slice O5).
- Retire a learned guideline: a new guideline version without it; recorded with who and why.
- Reject a proposal: remembered; not proposed again without new evidence.
- Every draft says what it read, so the effect of an undo is checkable on the next draft.

### 16.6 Drift

- Each learned item shows its health: of the drafts written under it, how many were sent unedited and how many were changed (slice O5).
- An edit that undoes what a rule made the drafter do proposes narrowing or retiring the rule (slice O6).
- Nothing runs on a schedule to "tidy" what was learned. The learner wakes once per edited, sent Delivery.

### 16.7 Already-sent Deliveries, the edit window and the lock

| Situation | What a person can do | What happens |
|---|---|---|
| Before the lock time | Edit the draft | A new text version. Their blocks are pinned. A machine redraft never overwrites a pinned block. A save names the version it replaces; a stale save is refused. |
| After the lock, before the send | Unlock, then edit | The lock is a fact on the row. Unlock is a person's action and returns it to `ready`. |
| While an attempt is open | Nothing changes that attempt | The edit is saved as a preferred version. |
| After an X post | Teach only, or Correct | Correct: a superseding Delivery; the old post is deleted; the cost is recorded. |
| After an email | Teach only, or send a correction notice | An email cannot be recalled. |

"Announced right away" (`publish_auto`, no edit window) and "massaged" meet in the preferred version: the lesson is captured without touching what was sent. A site that wants a moment to look first sets `publish_soft` with a short window; that is data.

---

## 17. Adversarial review

### 17.1 What could go wrong

| # | Risk | Mitigation | Where |
|---|---|---|---|
| R1 | **Double send**: the same publish triggers twice | The Announcement's once-only key; one live Delivery per channel and account; the attempt written before the call; Caducus dedupes on the attempt id; each reader's send is claimed before the provider call | PPY-3792dd, PPY-a570e8, PPY-824c14 |
| R2 | **Double send**: two schedule ticks for one period, or a clock change | The period key is the list's local scheduled date | N3, C1 |
| R3 | **Double send**: a reader on every-item and daily | One cadence per family; membership `since` | N2 |
| R4 | **Double send**: a half-finished correction leaves two generations sendable | The attempt opens only on the highest generation; a superseded or lower Delivery is never sent; unsent Deliveries are edited, not superseded | PPY-a570e8, PPY-3e0a8a, J6 |
| R5 | **Missed send**: the publish event is lost | Durable trigger from the change stream; the best-effort call is deleted | PPY-e3bb2b, PPY-8a374e |
| R6 | **Missed send**: a timer is lost | The due index; Overdue on Today; re-woken once with its key; one flag | C4, M8 |
| R7 | **Missed send**: a hard-gated issue nobody approves | Overdue and flagged; cancelled with a reason at the next period; items carry forward | N3 |
| R8 | **Race**: a person edits while the machine redrafts | Every save names the version it replaces; pinned blocks; the row's revision condition | PPY-e8ec54 |
| R9 | **Race**: an edit at the moment of lock or send | Lock and save are conditional writes on one row; one wins. The sender reads only the locked version. An edit during an open attempt is a preferred version. | PPY-e8ec54, O2 |
| R10 | **Race**: a correction while the old Delivery is still sending | A Delivery with an open attempt cannot be superseded; closing an attempt never moves a superseded Delivery back | PPY-3e0a8a, PPY-a570e8 |
| R11 | **Race**: two different corrections at once | The second gets a conflict when its text does not match the successor's hash; it is not treated as a retry | PPY-3e0a8a |
| R12 | **Learned-rule drift** | Proposals only; tested against approved history; health; contradiction proposals; one-action undo; every draft names what it read | O3 to O6 |
| R13 | **Spend runaway**: a loop between agents | The loop guard; one run per subject version and step; the budget stop | B7, A2, G2 |
| R14 | **Spend runaway**: a burst of edits | The quiet window | B5 |
| R15 | **Spend runaway**: a retry storm | A wake is delivered twice at most; a failed run is not retried by itself | A3 |
| R16 | **Consent mistake**: a migration or a new list enrols readers | A new list starts empty; consent per family; conversion carries consent evidence and suppression exactly; parity counts before sends resume | N7, PPY-824c14, PPY-1e75aa |
| R17 | **Consent mistake**: an unsubscribe races a send | Suppression and membership are checked per reader at send time, by Caducus | PPY-824c14, N8 |
| R18 | **A fully automatic site publishes something bad** | Doubt stops automatic publishing at every rung; hard floors; pause in one action; withdraw and retire; a correction; the site starts quiet and was promoted on evidence | E4, J2, E6 |
| R19 | **Migration** of sent newsletter issues loses history or re-sends | Convert once by a command with sends frozen; idempotent; converted issues are `sent` with their dates and counts; kept alert keys still prevent a second alert | PPY-1e75aa, PPY-58d962 |
| R20 | **Tenant isolation** on the shared tier | The tenant in every key; per-tenant budget and pause; adversarial suite cases; nothing ships there before the suite and the security review | I2 |
| R21 | **An agent writes around the gate** | The runner's role reaches only gated operations | E3 |
| R22 | **A deploy changes behaviour** | A deploy never touches the policy document; a new agent arrives `off` | D2 |
| R23 | **A paused agent floods on resume** | Skipped ticks are not replayed; only still-due work runs | J2 |
| R24 | **The change feed falls behind or drops records** | Iterator-age alarm; a wake only says "look"; the overdue check finds missed work | J1, C4 |
| R25 | **A stream gains a third reader and throttles** | A feed replaces a reader; never adds a third | B3 |
| R26 | **An index is added twice in one release** and the deploy fails | The plan stages one index per table per release | A5, C3, O1 |
| R27 | **An agent acts on text inside a source** (injection from a captured page or an email) | Captured text is data; agents act only through gated operations at their rung; public writes carry the link rule (no link, mention or tag absent from the Story) | E2, PPY-efd06c, PPY-cb3cc9 |
| R29 | **A resource ceiling fails a deploy**: the first-deploy budget (about 28 left) or the 500-resource function stack | All agent resources in one deferred `agents` stack; tests count each piece; the gate shares an existing function | I4 |
| R28 | **Wrong name in code**: `Announcement` is the old X model | New model is `AnnouncementDecision`; issues say so; the old model is deleted in PPY-efd06c; no rename | PPY-efd06c |

### 17.2 The correction path in PR #1618, checked in code

I read `src/papyrus_content/announcements/deliveries.py` on the branch [V].

How it works: a Delivery's id carries a generation. `supersede` does three ordered conditional writes: create the next generation (conditional on its id); mark the old one `superseded` (conditional on its revision); write the `supersedes` relation. The live Delivery is the highest generation.

| Case | What the code does | Verdict |
|---|---|---|
| Two retries of the same correction | The second finds the successor naming the old Delivery and finishes steps 2 and 3 | Sound |
| Crash after step 1, old Delivery already `sent` | Old row is still `sent`, successor exists. Readers that use "highest generation" see one. A retry finishes. | Sound, **if something retries**. Nothing does by itself. |
| Crash after step 1, old Delivery **not yet sent** | `supersede` does not check the old state. The old row keeps its due time and stays in the due index. `releasable` looks only at the row's own state. Both generations can be sent. | **Hole.** Double send. |
| Crash after step 2, before step 3 | A retry that passes a fresh copy of the old row hits `if old.get("supersededBy"): raise AlreadySuperseded` at the top and never reaches the relation write. A retry with a stale copy does finish. | **Hole.** The relation can stay missing. |
| Two **different** corrections at once | The loser finds a successor with `supersedes == old.id`, treats it as its own retry and returns it. Its text is silently dropped. If the winner crashed before its file was written, `ensure_text` writes the loser's text under the winner's row and hash. | **Hole.** Silent loss, and a possible text and hash mismatch. |
| Correction while the old Delivery is sending | Step 2 and the attempt's close both write the row conditionally; one gets a conflict. Nothing says what the loser does. | **Gap** for the attempt task. |
| Row created before its file | `create` writes the row, then the file. A `ready` row can exist for a moment with no file. | **Gap.** The sender must check. |
| Soft review, silence | `releasable` returns true at the lock time. `lock` raises when there is no approved version. | **Gap.** Something must approve as the policy at the lock time. |

**Does it need a reconciler or an invariant check?** Both, small, and neither is a new system:

1. **Guards at the source** (PPY-3e0a8a): refuse to supersede a Delivery that is not sent, or that has an open attempt (edit it instead). When a successor exists, compare the content hash; a different text is a conflict, not a retry. When the old row already points at the expected successor, finish the relation and do not raise.
2. **A guard at the send** (PPY-a570e8): an attempt opens only if the Delivery is the highest generation for its channel and account, is not superseded, and its text file matches the row's hash. Closing an attempt never changes a superseded Delivery's state.
3. **Finish on wake** (slice J6): whenever the announce agent wakes for an Announcement it reads that Announcement's Deliveries (one indexed read) and finishes any half-done correction. That is "re-check on every wake" and it is the reconciler.
4. **An invariant line on Today** (slice J6): anything the wake could not finish shows as "needs attention" with the two ids.
5. **Soft silence** (PPY-e8ec54): at the lock time under `soft` with no person's approval, the engine approves the current version as the policy, then locks, in one conditional write.

### 17.3 What is irreversible

| Irreversible | Guard |
|---|---|
| An email that was sent | Review rung; lock; dry run and test send first; a correction notice afterwards |
| An X post that people saw | The five-star floor; the budget; a watched first post; delete is possible but not unseeing |
| Money spent on models or posts | The budget stop; the unusual-cost flag |
| Erasing a subscriber | Already a deliberate, separate action; not touched by this design |
| Deleting old row families after conversion | A conversion command that is idempotent; delete only after counts match |
| A published Story that was read | Doubt path; hard floors; withdraw and correct |

### 17.4 What must have a kill switch

Pause one agent. Pause every agent on a site. Pause sending on one channel account. Each is one operation, each is tested, and each is checked at the start of a run or an attempt (slice J2). Lowering a rung is the fourth, slower, switch.

### 17.5 What this review changed in the plan

1. **Corrections are hardened at three places**, from reading PR #1618: refuse to correct an unsent or still-sending Delivery, treat a different correction as a conflict, and let a retry finish the relation (PPY-3e0a8a); open an attempt only on the highest generation with a matching text file (PPY-a570e8); finish half-done corrections on every wake and show the rest on Today (J6).
2. **Soft review with silence had no approver.** The engine now approves the current version as the policy at the lock time (PPY-e8ec54).
3. **Readers cannot get an item twice**: one cadence per family and a membership start time, instead of a per-reader ledger in Papyrus (N2).
4. **A skipped period is not lost and not silent**: eligibility is "since the last sent issue"; an unreleased issue is cancelled with a reason when the next begins (N3). An empty period sends nothing (N4).
5. **Teaching is separated from re-sending**: the preferred version on a sent Delivery (O2). Learning needs a person's scope or an admin's acceptance at every layer (O1, O4).
6. **The model name is settled**: `AnnouncementDecision` stays; no rename (PPY-efd06c, PPY-a36492).
7. **The resource ceilings became a first-week task**: every agent resource in one deferred stack, counted in tests (I4), because the first-deploy budget has about 28 left.
8. **Resume after a pause no longer loses change wakes**, and consent is never assumed for a new list (J2, N7). A model key that expires by hand is named as a go or no-go condition (section 19).

---

## 18. Release readiness and the order to turn things on

### 18.1 Checklist

Before anything is turned on in production, each line is true and recorded on slice J5:

- [ ] Every run has a wake key and an outcome (A1, A2).
- [ ] A duplicate wake runs once, proven by a spec against the real queue (B1).
- [ ] An interrupted run settles as designed (A3).
- [ ] Every hard floor passes at the top rung (E4).
- [ ] Each kill switch is tested (J2).
- [ ] The dead-letter, unknown, feed-lag and budget alarms fire in a test (J1).
- [ ] The site has a budget set, or runs no paid agent above `observe` (G2).
- [ ] The agent's runbook is generated and read by a person (D3).
- [ ] For email: a dry-run Delivery is built and a test send reaches the operator allow-list; counts match the transport (N8).
- [ ] For email: a new list starts empty; nobody is enrolled by a migration (N7).
- [ ] For a conversion: counts before and after match, and running it twice changes nothing.
- [ ] For corrections: the guards in section 17.2 pass, including a crash between writes (J6).
- [ ] For the shared tier: the isolation suite and the security review pass (I2).
- [ ] The first-deploy resource count and the function stack count are under their limits with the change (I4).
- [ ] Nothing was created by hand.

### 18.2 The order

1. **Records and outcomes.** A1, A2, I1, I4. No behaviour changes.
2. **The queue and the schedule trigger.** B1, C1. Run now goes through the queue. Still no new agent.
3. **The first agent at `observe`**, one site: rating on Machines on Machines (L1). Today v1 (H1).
4. **`propose`**, same agent, same site (L2). Then `draft` (L3), on evidence.
5. **The Item change feed** (PPY-8a374e) and the migration of the three old start paths, one per release, with Distinctive's TTAB analysis as the test (B6).
6. **The gate and the ladder** (E2, E3), then fold the switches (E5).
7. **Announcements, records only**: PPY-3792dd (built), PPY-a570e8, PPY-e3bb2b. X off.
8. **Machines on Machines weekly newsletter in dry run** for two periods, with test sends. Then live at `prepare`.
9. **Machines on Machines daily summary** in dry run, then `publish_soft`.
10. **Every-item email** on Machines on Machines in dry run, then `publish_auto`.
11. **Distinctive conversion** in a frozen window; then its weekly at `prepare`, as today. Then Shipped.
12. **The learner** at `propose` only (it never has a higher rung: an admin accepts).
13. **Other agents**, one at a time, each from `observe`.
14. **X**, last: a dry-run build of the exact post, then one watched live post with the pause ready.
15. **The shared tier**, after its suite and review.

Each step is one site first, lowest rung first, then wider.

---

## 19. Ready to build?

One page. Written last, after the filing and the adversarial review.

### 19.1 Go or no-go

**Go, for week one and the announcement tracks that need no agent.** Nothing in them changes what any site publishes or sends.

**No-go, for now, on three things**, and what turns each into a go:

| No-go | Becomes a go when |
|---|---|
| Any agent above `observe` in production | The release readiness lines in section 18.1 are recorded as passed (J5 (PPY-21a2e6)), and the site has a budget set. |
| Any newsletter or every-item send on the new records | The Caducus move (PPY-824c14) is done, a dry run and a test send pass, and no reader was enrolled by a migration (N7 (PPY-2f9b22)). |
| Any paid agent after 1 December | The model key no longer expires by hand: PPY-6af46b (rotation or federation, with a 401 alarm) is live. The current key lasts until about 1 December. |

### 19.2 The ground as of 2026-11-16 (checked on the board and GitHub)

- **Merged to develop, not released:** guideline files and the offline check (PR #1617, PPY-9c2ea0, now closed on the board); the pod base (PR #1619, PPY-4834f3, closed).
- **In CI, open:** the Announcement and Delivery records (PR #1618, PPY-3792dd). The decision model is `AnnouncementDecision`. Both new models are in a deferred model group; the first-deploy count is 1,972 of 2,000.
- **Filed today:** initiative PPY-a3fceb with 15 new epics and 83 new tasks; three existing epics re-parented under it; one follow-up task for pod check (PPY-58f931).
- **Not started:** everything in the standard.

### 19.3 Kickoff

**Start today, in parallel. None has a blocker.**

| Task | What | Model tier for the agent |
|---|---|---|
| A1 (PPY-f58445) | Outcome vocabulary on every run | Sonnet |
| E1 (PPY-51ea61) | The agent policy document | Sonnet |
| I1 (PPY-624dab) | The runner deploys through the pipeline | Sonnet |
| I4 (PPY-e06835) | Agent resources in one deferred stack, counted | Sonnet |
| PPY-58f931 | `pod check` validates guideline files | Haiku |
| PPY-1d5c43 | Guideline files in the cloud (schema version 2) | Sonnet |
| PPY-e4fd0c | Lifecycle keys in the pod profile | Sonnet |
| PPY-3792dd | Finish PR #1618: get CI green; fold the review findings into PPY-3e0a8a and PPY-a570e8, not into this PR | Sonnet (already running) |

Day two, as their blockers close: A2 (PPY-70c6e8), D1 (PPY-68abaa), PPY-a570e8. Then B1 (PPY-567bf9), C1 (PPY-2a53cd), then L1 (PPY-d85860) and H1 (PPY-5bcf42).

The strongest model is for design questions only. None of these tasks needs it.

**Every agent's brief must include:**

1. The task id, and "the issue text is the specification; do not invent behaviour beyond it".
2. Work in a new worktree from `origin/develop`. Never the shared checkout. Never `git stash`.
3. Gherkin first, narrative and complete; watch it fail; then code.
4. The standing rules, word for word: no fallbacks, no workarounds, no shims, no interim systems, no arbitrary caps; no text in DynamoDB; indexes over scans; no AppSync subscriptions; nothing created by hand in AWS; no real email addresses; Papyrus CLI over AWS CLI.
5. One new index per table per release. Say in the pull request which index it adds.
6. Run `scripts/test-bootstrap-stage.ts` and `scripts/test-function-directive-stack.ts`, and report the two counts in the pull request.
7. Verify on the local dev server. Do not deploy to find out.
8. Report "merged to develop" or "released" precisely. Record the branch, the PR and the verification on the issue.

**Who merges and what is released.** The product-owner session merges each pull request to `develop` when CI is green. Releases stay at once or twice a day, batched. The first release carries A1 (PPY-f58445), E1 (PPY-51ea61) and I4 (PPY-e06835): fields, one document kind and a stack boundary, with no behaviour change. I1 (PPY-624dab) changes pipeline roles, so it needs its approval step after merge. Each later index goes in its own release.

**The order things are turned on in production** is section 18.2. In short: records and outcomes; the queue and the clock; the rating agent at `observe` on Machines on Machines; then `propose`; then the change feed and the old start paths one per release, with Distinctive's ruling analysis as the test; then the ladder; then announcements with X off; then the Machines on Machines weekly newsletter in dry run, then live at `prepare`; the daily summary; every-item email; Distinctive's conversion in a frozen window; X last.

### 19.4 The three things most likely to go wrong in the first two weeks

| # | Risk | Early-warning sign |
|---|---|---|
| 1 | **A resource ceiling fails a deploy.** The first-deploy budget has about 28 resources left and the data API's function stack is capped at 500. Every queue, function and field counts. | Either count rises in a pull request, or `test-bootstrap-stage` goes red. Watch the two numbers in every PR from day one (I4 (PPY-e06835)). |
| 2 | **Changing how runs start breaks something that works.** The runner becomes a queue consumer; Distinctive's ruling analysis and translation on publish use it today. | A message in the wake dead-letter queue; Distinctive's run count for a day drops; a run stuck at `started`. Move Run now first, then one old path per release (B6 (PPY-4af216)). |
| 3 | **The model key expires or is missing and every agent stops at once.** The key lasts until about 1 December; one site's key was reported expired on 14 November. | A 401 in a run's error; the rating agent's first run ends `failed`. PPY-6af46b must be live before the date. |

Close behind: two parallel tasks adding an index to the same table in one release (the brief's rule 5 prevents it), and the plan sprawling (if the rating agent is not running at `observe` by the end of week one, stop adding and finish that).

### 19.5 What Ryan must decide or provide before building

Only what truly blocks:

1. **A working model key for Machines on Machines**, and a go on PPY-6af46b before 1 December. Without a key the first agent cannot run.
2. **The AI budget for Machines on Machines.** Decided 2026-11-22: monthly; with no budget set a site gets $10 a month. (At `observe` the rating agent costs cents a day on the cheapest tier.)
3. **The approval for the pipeline-roles change** that I1 (PPY-624dab) needs, when its run asks.
4. **A yes or no on the first agent and site**: rating on Machines on Machines. Silence means yes.

Everything else has a default in section 13 and does not block: the outcome word, where the rung lives, the daily summary's time, cadence families, the scope question, no rename of `AnnouncementDecision`.

Not needed yet: an X developer account, a second model provider's key for the editorial tier, the DMARC mailbox, any Caducus change. Each is named on its own task.

### 19.6 What I would cut or defer to keep it small

Set to low priority on the board today. None is deleted.

| Defer | Until |
|---|---|
| O4 (PPY-a7174b), O5 (PPY-e705a8), O6 (PPY-c1cbf1) the learner and its upkeep | Announcements are live on one site and there are real edits to learn from. O1 (PPY-627bbc) and O2 (PPY-75a314) (capture and the preferred version) are cheap and stay, so nothing is lost meanwhile. |
| I2 (PPY-8cf5e2) the shared tier | The multi-tenant milestones reach it. |
| M9 (PPY-d9d78a) the knowledge run as an agent | It works today. Move it last. |
| A6 (PPY-c023ab) continuation | A real unit of work is seen not to fit in one run. |
| N6 (PPY-769d1b) quiet hours | Someone asks. The daily summary is the answer for most readers. |
| G3 (PPY-eef85d) unusual cost, E6 (PPY-994ff6) promotion evidence, H4 (PPY-1dd73a) explain | The first agent has a few weeks of runs. Until then a person reads the runs. |
| F3 (PPY-32b5c1) a person's message steers an agent | Stage 2 of "Messages come only from people" (PPY-781d26). |

I would also hold epic K (the written lifecycles) until the agents that move those records exist; each is a small task and is better written against a running agent.

What I would not cut: the wake key, the outcome, the queue, the policy document, the gate, the hard-floor suite, the kill switches, the resource-count task. Those are the standard. Building an agent without them is building the interim system the canon forbids.


---

## Appendix: slice codes and board ids

| Code | Board id | Title |
|---|---|---|
| Initiative | PPY-a3fceb | Always-on agents: one standard for every standing responsibility |
| Epic A | PPY-865e83 | Wake contract and run outcomes |
| A1 | PPY-f58445 | Outcome vocabulary on every run |
| A2 | PPY-70c6e8 | Wake keys: one run per wake, recorded before the work starts |
| A3 | PPY-2d2e55 | Settle an interrupted run: Outcome unknown is a state, not a guess |
| A4 | PPY-8b131e | Run input, output and errors live in S3, not in the catalog |
| A5 | PPY-577310 | Run indexes: by agent, and 'needs attention' |
| A6 | PPY-c023ab | Continuation: a unit of work longer than one run |
| Epic B | PPY-cd706f | Inbox: change feeds, the wake queue and one worker |
| B2 | PPY-8a374e | Step runner: Item stream, per-site FIFO queue, dispatcher, coalescing window (existing, re-used) |
| B1 | PPY-567bf9 | Per-site wake queue; the procedure runner consumes it |
| B3 | PPY-9b9e64 | Change feeds for Reference, ReviewRequest, Message, LocalizationRequest and Delivery |
| B4 | PPY-a200ec | One worker per responsibility and scope |
| B5 | PPY-67e3cd | Coalescing window: wait for quiet before paid work |
| B6 | PPY-4af216 | Move monitor triggers, Stage Bots and Run now onto the wake path |
| B7 | PPY-4e7e8b | Loop guard per subject |
| Epic C | PPY-4bc313 | Timers: the schedule trigger and follow-ups |
| C1 | PPY-2a53cd | The schedule trigger: an agent runs on a clock from data |
| C2 | PPY-3ff011 | Follow-up timers: a due time on a record raises one wake |
| C3 | PPY-9b8e59 | Review request deadlines are timers; open requests are read by index |
| C4 | PPY-70cd6a | Overdue: anything due and untouched is shown and flagged |
| Epic D | PPY-b05940 | Agent definitions, the catalog and generated runbooks |
| D1 | PPY-68abaa | The agent definition file and the responsibility catalog |
| D2 | PPY-df3e74 | Definitions are applied by the release |
| D3 | PPY-7b05f7 | Generated runbook per agent and a generated inventory |
| D4 | PPY-dd0653 | Every agent loads the standard context pack and the site's add-only instructions |
| Epic E | PPY-077760 | Authorization: the autonomy ladder as configuration |
| E1 | PPY-51ea61 | The agent policy document: rung, overrides and pause, per site |
| E2 | PPY-611397 | One gate: each operation names the rung it needs |
| E3 | PPY-eece43 | The runner's role reaches only gated operations |
| E4 | PPY-36e7c9 | Hard floors hold at every rung |
| E5 | PPY-8e74bb | Fold the existing switches into the ladder |
| E6 | PPY-994ff6 | Promotion evidence: what a person sees before raising a rung |
| Epic F | PPY-928a91 | Work items and handoffs between agents and people |
| F1 | PPY-51f96f | Assignment is the request between agents |
| F2 | PPY-5cf1a8 | Hand a step back with a reason; a person takes a step over |
| F3 | PPY-32b5c1 | A person's message steers an agent; the reply is a run card |
| F4 | PPY-ecf852 | An answer to a review request wakes the agent that asked |
| F5 | PPY-8d11af | Ask once: agents read what was already said |
| Epic G | PPY-6505b3 | Spend, budgets and model tiers |
| G1 | PPY-fa165c | One spend ledger |
| G2 | PPY-9376f8 | At the budget, paid work waits and says so |
| G3 | PPY-eef85d | Unusual cost is flagged from the agent's own history |
| G4 | PPY-c9c165 | Model tier is configuration |
| Epic H | PPY-767813 | Human surface: Today, poke-in operations and explanations |
| H1 | PPY-5bcf42 | Today v1: what ran, what it decided and what it cost |
| H2 | PPY-b6d5ad | Today v2: waiting for you, overdue, outcome unknown, due today |
| H3 | PPY-e6f31e | Poke-in operations: pause, resume, set rung, wake now, redirect, undo |
| H4 | PPY-1dd73a | Explain: why did nothing happen? |
| H5 | PPY-ec54ea | `papyrus today` and `papyrus agents` are generated from the operation table |
| Epic I | PPY-33e622 | Infrastructure as code and the shared tier |
| I1 | PPY-624dab | The procedure runner deploys through the release pipeline |
| I2 | PPY-8cf5e2 | The shared tier runs the same design with the tenant in every key |
| I3 | PPY-04c0d1 | Cost model and tags for agent resources |
| I4 | PPY-e06835 | Agent resources fit the first-deploy resource budget: one deferred stack, measured |
| Epic J | PPY-b7039f | Observability, safety and release readiness |
| J1 | PPY-45ef76 | Alarms: dead letters, stuck unknowns, change feed lag, budget |
| J2 | PPY-3f68f4 | Kill switches, tested |
| J3 | PPY-e0c85a | Proof of conduct: the run record lists every operation asked, allowed and refused |
| J4 | PPY-33e126 | Observe is the dry run |
| J5 | PPY-21a2e6 | Release readiness checklist and turn-on order |
| J6 | PPY-9922b2 | Invariant checks on Today for Announcements and Deliveries |
| Epic K | PPY-462d6e | Lifecycles that run themselves: Reference, Idea, Translation, Illustration |
| K1 | PPY-bea2bf | The Reference lifecycle runs itself |
| K2 | PPY-f1c774 | The Idea lifecycle runs itself |
| K3 | PPY-21b8c5 | The Translation lifecycle runs itself |
| K4 | PPY-ce0dd2 | The Illustration lifecycle runs itself |
| Epic L | PPY-24b2ac | First agent: rating and curation on one site |
| L1 | PPY-d85860 | Rating agent at observe on Machines on Machines |
| L2 | PPY-e61642 | Rating agent at propose: suggested stars a person confirms |
| L3 | PPY-924693 | Rating agent writes three or four when promoted, and reacts to changes |
| L4 | PPY-89f253 | Measure the rating agent against people |
| Epic M | PPY-11b33b | Every other responsibility as an agent |
| M1 | PPY-ad7087 | Intake and capture as an agent |
| M2 | PPY-fb1aef | Ideation as an agent |
| M3 | PPY-1e703e | Research as an agent |
| M4 | PPY-98f88e | Translation as an agent |
| M5 | PPY-77148a | Illustration as an agent |
| M6 | PPY-18b582 | Improvement and copy-edit as an agent |
| M7 | PPY-396483 | Fact-check as an agent |
| M8 | PPY-50445c | Operations hygiene as an agent |
| M9 | PPY-d9d78a | The knowledge run as a scheduled agent on the container executor |
| Epic N | PPY-79c915 | Newsletters and subscriptions: weekly, daily and every new item |
| N1 | PPY-4d74d9 | A list carries its cadence, time, time zone and rule as data |
| N2 | PPY-a19b9d | Cadence families: a reader picks one cadence, so nobody gets an item twice |
| N3 | PPY-b71153 | Period keys in the list's time zone; what was not sent carries forward |
| N4 | PPY-1d451f | An empty period sends nothing and says so |
| N5 | PPY-3b928d | The daily summary list |
| N6 | PPY-769d1b | Every-item lists: quiet hours and spacing |
| N7 | PPY-2f9b22 | Preferences: choose a cadence; consent is never assumed |
| N8 | PPY-b53c09 | Counts and suppression on the Delivery; one Today line per send |
| N9 | PPY-00817a | Five end-to-end walkthrough specs |
| N10 | PPY-2c29e5 | One working document per list |
| Epic O | PPY-f51641 | Announcements learn from a person's edits |
| O1 | PPY-627bbc | Capture what a person changed in an announcement, and how far it should reach |
| O2 | PPY-75a314 | Preferred version: teach without sending again |
| O3 | PPY-d99bd0 | Examples reach the drafter, and every draft names what it read |
| O4 | PPY-a7174b | The learner proposes guideline changes, tested against history |
| O5 | PPY-e705a8 | Undo and health for what was learned |
| O6 | PPY-c1cbf1 | A later edit against a learned rule proposes narrowing it |
| (announcement follow-up) | PPY-58f931 | `papyrus pod check` validates guideline files |
