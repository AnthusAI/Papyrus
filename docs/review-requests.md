# Review requests: flags, soft reviews and hard gates

> **Review Requests** are how automation asks a person to look (a flag, a soft review with a timeout, or a hard gate) without making review a story state. They are listed in the Notification Center. See [feature-names.md](feature-names.md#review-requests-and-the-notification-center).

A step in a site's automation (a procedure, an automation, an AI step) can ask a person to look at an item without making review a story
state. This is PPY-ab6a50; the console page that lists the requests is the [Notification Center](notification-center.md).

## Modes

| Mode | Waits? | At the deadline |
|---|---|---|
| `flag` | Nothing waits. | None. Stays open until acknowledged or withdrawn. |
| `soft_review` | No expiry by default: the request stays open until someone handles it. A caller may pass an explicit deadline (`deadline` or `deadline_days`); then the process waits until it. | Without a deadline, never: it is not timed out and stays in the Notification Center. With an explicit deadline, if nobody answered the request becomes `timed_out` and records "proceeded without review"; the process continues. |
| `hard_gate` | Never proceeds without an explicit answer. No deadline. | Never. |

An answer is `approve`, `acknowledge` (a flag only: nothing was approved, the editor saw it; it counts like the old flag `approve` everywhere downstream, including the `approved` outcome), `reject` or `feedback`, with optional feedback text and an optional steer (`adjust` or `not_this_kind`).

## The model (`ReviewRequest`, in every site's data API)

| Field | Meaning |
|---|---|
| `id` | `rr-<hex>`, or one the caller chooses (raising the same id twice returns the first: idempotent). |
| `subject` | `{type, id}`: `story`, `proposal`, `reference`, `automation_run`, `cyclotron_decision` or `batch`. |
| `mode`, `reason`, `ask` | The mode, why (the headline), and what is asked. |
| `raisedBy`, `raisedAt` | The automation, procedure or AI step, and when. |
| `deadline` | Soft reviews only, and only when the caller passes one. Empty means no expiry. |
| `state` | `open`, `answered`, `timed_out`, `withdrawn`. |
| `answer` | `{decision, feedback, steer, by, at}`. |
| `links` | Items in the request (for a batch, each proposal) or URLs. |
| `history` | The audit trail of this request: raised, answered, timed_out ("proceeded without review"), applied, withdrawn. |
| `appliedIn` | `{runId, by, at}`: the run that used the steering. |

Also `ReviewReadMark` (per-user read state, id `<userSub>#<requestId>`) and `ReviewRecipientRule` (who is told). Editors read, create and
update requests; admins also delete. Neither is readable by guests or the identity pool. Operators use the same lane as the other models
(`PAPYRUS_GRAPHQL_AUTH=iam`); automations and procedures raise through their managed IAM roles or the operator CLI.

The audit trail lives on the request. A line on the *item's* own trail (the story's history) is a follow-up.

An answer's note (and a draft's Why, kept on its link and in the answer's `drafts`) can be changed after the answer without reopening the request: the console writes it with the condition that the request is still in the state it read, and adds a `reason_edited` history entry. See [the reason, in any order](notification-center.md#the-reason-in-any-order).

## The deadline mechanism: checked on read

v0 has no scheduled function. `expire_due` marks every open soft review that has a deadline and whose deadline has passed as `timed_out`. It runs whenever the
requests are read: the Python `list_reviews`, `get_review`, `answer_review` and `wait_for_review`, and the console when the page loads. The
raising process learns the outcome by waiting or reading; nothing else has to happen at the deadline. Writes carry the condition
`state = open` in the console, so an answer racing the deadline cannot both win. (The Python client reads then writes; the window is small and
the backend authorization is unchanged.) A scheduled sweep is only needed for something that must happen at the deadline with no one looking,
such as an email, and comes with that.

## Python library (`papyrus_content.review_requests`)

```python
from papyrus_content import review_requests as rr
client = create_authoring_client()[0]

request = rr.raise_review(client, subject={"type": "story", "id": story_id}, mode="soft_review",
                          reason="Check the headline", raised_by="procedure:copy-editor", deadline_days=3)
result = rr.wait_for_review(client, request["id"], poll_seconds=60)      # blocks as the mode says
result["outcome"]   # approved | rejected | feedback | proceeded_without_review | withdrawn | waiting (a flag)
```

* `review_gate(client, ..., wait=True)` raises and waits in one call.
* `wait_for_review`: a flag returns at once; a soft review returns at the answer or at the deadline with `proceeded_without_review`; a hard
  gate returns only on an answer or a withdrawal. `max_wait_seconds` on a hard gate raises `ReviewStillOpen` and leaves it open. A
  CLI-run process polls; full resumable gates in the run contract come later.
* `answer_review`, `withdraw_review`, `list_reviews`, `get_review`, `expire_due`.

### Steering read-back (generic)

Whatever raised a request reads what editors said, and records that it used it:

```python
for note in rr.steering_for(client, raised_by="idea-pipeline"):    # answered with feedback, a steer, or a reject; not yet applied
    use(note["feedback"], note["steer"], note["subject"])
    rr.mark_applied(client, note["requestId"], run_id=this_run_id, by="idea-pipeline")
```

`mark_applied` is what the console shows as "You steered X, applied in run Y".

### The idea pipeline hook

Synthesis raises ONE soft review per run:

```python
rr.raise_batch_review(client, raised_by="idea-pipeline", batch_id=run_id, proposal_ids=[p["id"] for p in proposals])
# reason: "3 new story ideas to review"; subject {type: batch, id: run_id}; each proposal is a link;
# no deadline unless deadline_days=... is passed; idempotent per batch_id.
```

At the start of the next synthesis (and digest) run, call `steering_for(client, raised_by="idea-pipeline")` and feed the feedback in as input,
then `mark_applied`. A rejected batch comes back as a steering entry with `decision: "reject"`.

## CLI

```
papyrus reviews list [--state open] [--mode hard_gate] [--raised-by NAME] [--json]
papyrus reviews show --id ID
papyrus reviews raise --subject-type T --subject-id ID --mode flag|soft_review|hard_gate --reason TEXT [--ask TEXT]
                      [--raised-by NAME] [--deadline ISO | --deadline-days N] [--links JSON] [--id ID] [--wait [--max-wait-seconds N]]
papyrus reviews answer --id ID --decision approve|acknowledge|reject|feedback [--feedback TEXT] [--steer adjust|not_this_kind]
papyrus reviews withdraw --id ID [--note TEXT]
papyrus reviews wait --id ID [--poll-seconds N] [--max-wait-seconds N]
papyrus reviews steering [--raised-by NAME] [--all]        # unapplied steering, for a step to read
papyrus reviews applied --id ID --run RUN_ID
papyrus reviews recipients [--mode M] [--automation A]     # who would be told
papyrus reviews recipients --set --scope default|mode|automation [--key K] [--roles editor,admin] [--emails a@x,b@y]
```

## The publish gate

A site that sets its [publish approval](how-a-publish-flows.md#a-site-can-require-a-persons-approval-to-publish) to `required` uses `hard_gate` requests as its publish gate (PPY-8c5438). `publish_item` refuses unless the call carries a signed-in person (`approved_by`: the console's Publish and live Save, through the content-actions function's Cognito identity) or a person already approved a request for that version. Otherwise it raises one request and stops:

| Field | Value |
|---|---|
| `id` | `rr-publish-<hash of the item record id and its content hash>`; a later request about the same version, after one was withdrawn, adds `-2`, `-3`. |
| `subject` | `{type: story, id: <lineage id>}`; the item record is a link. |
| `mode`, `raisedBy` | `hard_gate`, `publish-gate`. |

Approve it and the caller's next publish goes through (nothing publishes at the moment of approval). Reject it, or answer with feedback, and the version stays unpublished with the code `approval-rejected` until its text changes. A person\'s own publish settles an open request as approved, recorded as `approver: person`. Under `required` only a person\'s approval counts: an answer whose `by` starts with `agent:` is read as an agent\'s and does not open the gate. The setting is an enum that can grow (delegated approval, where an editor agent may approve after a person\'s first refusal lapses, is a separate task), and each approval records its approver kind. The code is `src/papyrus_content/publish_gate.py`; the setting is read and set with `papyrus ops content publish-gate show|set`.

## Recipients (site configuration, no code change)

`ReviewRecipientRule` rows, resolved most specific first: the automation's rule, then the mode's, then the `default` rule, then the site
owner (`PAPYRUS_SITE_OWNER_EMAIL`), and if that is not set, the site's admins. A rule lists roles (`editor`, `admin`, resolved to the active
holders in the site's user list) and optional extra emails. Change them with `papyrus reviews recipients --set`. Addresses live in the
site's data, never in the repository.

## Email

**Not in v0.** The site's SES setup is the newsletter plugin's: it sends from the newsletter sender with subscriber unsubscribe handling and
an IAM policy limited to that identity, so it is not a staff transactional path. Sending "one email per new hard gate" needs a staff mail
sender (and, for the deadline, the scheduled sweep). The recipient resolution above is ready for it.

## What a site must deploy or configure

* Deploy the data API (the three new models). No other infrastructure.
* Optionally set recipient rules and `PAPYRUS_SITE_OWNER_EMAIL` (only used when email is added).
* Editors and admins already in the user list can answer; no new groups.
