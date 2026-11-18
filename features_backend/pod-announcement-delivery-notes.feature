@pod
Feature: Announcement and Delivery notes in a pod
  A pod keeps what was said, and where, as notes. An Announcement note is the decision to say something about one or more Stories. A Delivery note is one channel's
  version of it: the words, exactly as posted, are the body of the note, and the front matter has the field names of the newsroom's Delivery record (the channel, the
  account, the mode, the state, the address of the result, the attempts). `announces` links an Announcement to the Stories it is about, `announcement` links a Delivery to
  its Announcement, and `supersedes` links a Delivery to the Delivery it corrects; the first and last are relation types, so they are typed links like any other.

  The words are outside the graph and these two kinds of note are never built into a page. A pod records what happened, so a note's state is a final one (sent, failed,
  withdrawn or superseded), and a pod delivers in manual mode only: a person sent it. Automatic sending needs a connected account, a budget guard and Caducus, which a
  newsroom has and a pod does not. The attempts are a log that only grows. Each is one line, and `papyrus pod check` fails when an earlier line differs from the last
  commit, the same way it guards an id.

  When a pod is loaded into a newsroom, these notes become the same records the newsroom writes, as history. A load never sends anything: it has no channel, the loaded
  Delivery waits for nothing, and a pod's approval is a claim, never a newsroom approval. These specs use no network and no real address or account.

  Background:
    Given a started pod
    And the pod file "articles/slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0101
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water is the practice of keeping rain on the land a little longer.
      """
    And the pod file "announcements/slow-water-published.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0102
      type: papyrus:Announcement
      kind: story-published
      state: released
      releaseAt: 2026-11-16T14:00Z
      announces: "[[slow-water]]"
      ---
      The decision to say something about Slow water.
      """
    And the pod file "deliveries/slow-water-x.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0103
      type: papyrus:Delivery
      announcement: "[[slow-water-published]]"
      channel: x
      account: "@example"
      mode: manual
      state: sent
      resultUrl: https://example.org/status/123
      attempts:
        - "1 2026-11-16T14:01Z sent by ryan"
      ---
      Rain kept on the land a little longer. Slow water, new this week. #water
      """

  # ---- the notes are valid notes ---------------------------------------------------------------------------------------------------

  Scenario: An Announcement note and its Delivery note are a valid pod
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "level: 1 (3 of 3 notes typed)"
    And the pod report says "ok: no problems"

  Scenario: The words are the body and are outside the graph
    Given the pod file "deliveries/slow-water-x.md" has "Slow water, new this week." replaced by "Slow water, new this week. See [[a note that does not exist]]."
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: A Delivery with no words is refused
    Given the pod file "deliveries/slow-water-x.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0103
      type: papyrus:Delivery
      announcement: "[[slow-water-published]]"
      channel: x
      account: "@example"
      mode: manual
      state: sent
      ---
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has no words" for the note "deliveries/slow-water-x.md"

  Scenario: A Delivery that leaves out a field the record needs is refused
    Given the pod file "deliveries/slow-water-x.md" loses the text "channel: x\n"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "has no channel" for the note "deliveries/slow-water-x.md"

  Scenario: An Announcement that announces no Story is refused
    Given the pod file "announcements/slow-water-published.md" loses the text "announces: \"[[slow-water]]\"\n"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "announces no Story" for the note "announcements/slow-water-published.md"

  Scenario: A Delivery belongs to an Announcement note, not to any note
    Given the pod file "deliveries/slow-water-x.md" has "[[slow-water-published]]" replaced by "[[slow-water]]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'announcement' names articles/slow-water.md, which is not an Announcement note" for the note "deliveries/slow-water-x.md"

  # ---- a pod delivers in manual mode only, and records what happened -------------------------------------------------------------------

  Scenario: A pod delivers in manual mode only
    Given the pod file "deliveries/slow-water-x.md" has "mode: manual" replaced by "mode: automatic"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "a pod delivers in manual mode only" for the note "deliveries/slow-water-x.md"

  Scenario: A pod records what happened, so a Delivery that is still waiting to go is refused
    Given the pod file "deliveries/slow-water-x.md" has "state: sent" replaced by "state: ready"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "key 'state' is 'ready'; a state is one of sent, failed, withdrawn, superseded" for the note "deliveries/slow-water-x.md"

  Scenario: A sent Delivery says so in its last attempt
    Given the pod file "deliveries/slow-water-x.md" has "1 2026-11-16T14:01Z sent by ryan" replaced by "1 2026-11-16T14:01Z refused rate limit"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "is sent and its last attempt did not end sent" for the note "deliveries/slow-water-x.md"

  Scenario Outline: An attempt line that is not an attempt is refused
    Given the pod file "deliveries/slow-water-x.md" has "1 2026-11-16T14:01Z sent by ryan" replaced by "<line>"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "<problem>" for the note "deliveries/slow-water-x.md"

    Examples:
      | line                              | problem                                      |
      | posted it by hand                 | attempt 1 is not an attempt line             |
      | 2 2026-11-16T14:01Z sent by ryan  | attempt 1 is numbered 2                      |
      | 1 2026-11-16T14:01Z started       | attempt 1 ended 'started'                    |
      | 1 2026-13-45T14:01Z sent by ryan  | attempt 1 has the time 2026-13-45T14:01Z     |

  # ---- the attempts only grow --------------------------------------------------------------------------------------------------------

  Scenario: An earlier attempt line that changed since the last commit fails the check
    Given the pod is a git repository with everything committed
    And the pod file "deliveries/slow-water-x.md" has "1 2026-11-16T14:01Z sent by ryan" replaced by "1 2026-11-16T15:30Z sent by ryan"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "attempt line 1 changed since the last commit" for the note "deliveries/slow-water-x.md"
    And the pod report says "the attempt lines of Delivery notes"

  Scenario: An earlier attempt line that was removed fails the check
    Given the pod is a git repository with everything committed
    And the pod file "deliveries/slow-water-x.md" has "attempts:\n  - \"1 2026-11-16T14:01Z sent by ryan\"" replaced by "attempts: []"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "attempt line 1 changed since the last commit" for the note "deliveries/slow-water-x.md"

  Scenario: A new attempt line added after the earlier ones passes
    Given the pod file "deliveries/slow-water-x.md" has "state: sent" replaced by "state: failed"
    And the pod file "deliveries/slow-water-x.md" has "1 2026-11-16T14:01Z sent by ryan" replaced by "1 2026-11-16T14:01Z refused rate limit"
    And the pod is a git repository with everything committed
    And the pod file "deliveries/slow-water-x.md" has "  - \"1 2026-11-16T14:01Z refused rate limit\"" replaced by "  - \"1 2026-11-16T14:01Z refused rate limit\"\n  - \"2 2026-11-16T15:00Z refused budget reached\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: A Delivery that was never committed is not compared with history
    Given the pod is a git repository with everything committed
    And the pod file "deliveries/slow-water-linkedin.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0104
      type: papyrus:Delivery
      announcement: "[[slow-water-published]]"
      channel: linkedin
      account: example-page
      mode: manual
      state: sent
      attempts:
        - "1 2026-11-16T14:05Z sent by ryan"
      ---
      Slow water is the practice of keeping rain on the land a little longer.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0

  # ---- corrections ---------------------------------------------------------------------------------------------------------------------

  Scenario: A correction supersedes the Delivery it replaces
    Given a corrected Delivery note
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: A Delivery that was corrected says it was superseded
    Given a corrected Delivery note
    And the pod file "deliveries/slow-water-x.md" has "state: superseded" replaced by "state: sent"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "its state is not superseded" for the note "deliveries/slow-water-x.md"

  Scenario: A second live Delivery for one channel and account is a correction and must say so
    Given the pod file "deliveries/slow-water-x-again.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0104
      type: papyrus:Delivery
      announcement: "[[slow-water-published]]"
      channel: x
      account: "@example"
      mode: manual
      state: sent
      attempts:
        - "1 2026-11-16T16:00Z sent by ryan"
      ---
      The same post, again.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "one live Delivery for each Announcement, channel and account" for the note "deliveries/slow-water-x-again.md"

  Scenario: A correction is for the same channel and account
    Given a corrected Delivery note
    And the pod file "deliveries/slow-water-x-corrected.md" has "channel: x" replaced by "channel: linkedin"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "for another Announcement, channel or account" for the note "deliveries/slow-water-x-corrected.md"

  Scenario: Only a Delivery supersedes a Delivery
    Given the pod file "deliveries/slow-water-x.md" has "mode: manual" replaced by "mode: manual\nsupersedes: \"[[slow-water]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "'supersedes' cannot link a Delivery to an Article" for the note "deliveries/slow-water-x.md"

  Scenario: An Announcement announces a Story, not a source
    Given a copy of the fixture pod
    And the pod file "announcements/about-the-report.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0110
      type: papyrus:Announcement
      kind: story-published
      state: released
      announces: "[[acme-report]]"
      ---
      The decision to say something about the report.
      """
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "'announces' cannot link an Announcement to a Reference" for the note "announcements/about-the-report.md"

  # ---- never a page ----------------------------------------------------------------------------------------------------------------

  Scenario: Neither type is ever a page
    When the pages of the pod are listed
    Then the pages are "articles/slow-water.md"

  Scenario: Neither type is a page even when it says it is published
    Given the pod file "deliveries/slow-water-x.md" has "mode: manual" replaced by "mode: manual\nstage: published"
    And the pod file "announcements/slow-water-published.md" has "state: released" replaced by "state: released\ndraft: false"
    When the pages of the pod are listed
    Then the pages are "articles/slow-water.md"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "a Delivery is never a page, so it has no 'stage'" for the note "deliveries/slow-water-x.md"
    And the pod report names the problem "an Announcement is never a page, so it has no 'draft'" for the note "announcements/slow-water-published.md"

  # ---- a Story can cite and have an author -------------------------------------------------------------------------------------------

  Scenario: A Story cites a source and names its author with plain keys
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "see_also: [\"[[acme-report]]\"]" replaced by "cites: [\"[[acme-report]]\"]\nauthored_by: \"[[ada-example]]\""
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 0
    And the pod report says "ok: no problems"

  Scenario: A Story cannot cite a note that is not a source
    Given a copy of the fixture pod
    And the pod file "articles/slow-water.md" has "see_also: [\"[[acme-report]]\"]" replaced by "cites: [\"[[irrigation]]\"]"
    When I run the pod command "papyrus pod check POD"
    Then the pod command exits with status 1
    And the pod report names the problem "'cites' cannot link an Article to a Concept" for the note "articles/slow-water.md"

  # ---- load: history, and nothing is sent -------------------------------------------------------------------------------------------------

  Scenario: A load writes the Announcement and the Delivery as history
    Given the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    When the pod's Announcement notes are loaded into an empty newsroom
    Then the newsroom has 1 Announcement that is released, decided by the pod load for the key "pod:https://example.org/id/sample-0102"
    And the Announcement announces the Story "slow-water" at version 3
    And the newsroom has 1 Delivery for "x" "@example" that is sent, in manual mode, at generation 1
    And the Delivery has the words "Rain kept on the land a little longer. Slow water, new this week. #water" exactly
    And the Delivery has the result address "https://example.org/status/123"
    And the Delivery has 1 attempt, number 1, sent at "2026-11-16T14:01:00Z" by "ryan"
    And the Delivery carries no approved version and says its approval was recorded in a pod

  Scenario: A load sends nothing
    Given the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    When the pod's Announcement notes are loaded into an empty newsroom
    Then no Delivery is due
    And no Delivery is waiting for a time
    When the worker for "x" "@example" is asked to send each loaded Delivery
    Then the worker sends none of them
    And the channel received no event

  Scenario: Loading the same notes again writes nothing new
    Given the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    And the pod's Announcement notes are loaded into an empty newsroom
    When the pod's Announcement notes are loaded again
    Then the newsroom has 1 Announcement
    And the newsroom has 1 Delivery for "x" "@example" that is sent, in manual mode, at generation 1
    And the second load wrote nothing

  Scenario: A record the newsroom has changed is not overwritten by a later load
    Given the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    And the pod's Announcement notes are loaded into an empty newsroom
    And the newsroom withdraws the loaded Delivery for "x" "@example"
    When the pod's Announcement notes are loaded again
    Then the newsroom has 1 Delivery for "x" "@example" that is withdrawn, in manual mode, at generation 1

  Scenario: A correction loads as the next generation
    Given a corrected Delivery note
    And the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    When the pod's Announcement notes are loaded into an empty newsroom
    Then the newsroom has 2 Deliveries for "x" "@example"
    And generation 1 is superseded and points forward to generation 2
    And generation 2 is sent and supersedes generation 1
    And the newsroom has a supersedes link from generation 2 to generation 1
    And no Delivery is due

  Scenario: A load refuses a pod that does not pass the check
    Given the newsroom has the Story note "https://example.org/id/sample-0101" as the lineage "slow-water" at version 3
    And the pod file "deliveries/slow-water-x.md" has "mode: manual" replaced by "mode: automatic"
    When the pod's Announcement notes are loaded into an empty newsroom
    Then the load is refused with "does not pass `papyrus pod check`"
    And the newsroom holds no record

  Scenario: A load refuses an Announcement about a Story the newsroom does not have yet
    When the pod's Announcement notes are loaded into an empty newsroom
    Then the load is refused with "has not been loaded as a Story"
    And the newsroom holds no record
