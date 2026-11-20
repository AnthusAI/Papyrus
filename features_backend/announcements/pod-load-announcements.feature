@pod @checklist-gate
Feature: A pod's Announcement and Delivery notes load as history and send nothing
  When a pod is loaded into a newsroom, its Announcement and Delivery notes become the same two records the newsroom writes: an Announcement for the decision to say something
  and a Delivery for each channel, so a Story's drawer shows a pod Delivery beside any other. They are history. Each Delivery loads in the final state its note says, in manual mode,
  with its attempts as the person wrote them, and its words are the body of the note. A load sends nothing: it has no channel, the loaded Delivery waits for nothing and a pod's
  approval is a claim, never a newsroom approval. Neither kind of note ever becomes a page. Loading again finds what the first load wrote. These specs use no network and no real
  address or account.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod file "articles/slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0201
      type: papyrus:Article
      title: Slow water
      stage: published
      ---
      Slow water is the practice of keeping rain on the land a little longer.
      """
    And the pod file "announcements/slow-water-published.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0202
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
      id: https://example.org/id/sample-0203
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
    And the pod is a git repository with everything committed

  Scenario: The notes become an Announcement and a Delivery, as history
    When I load the pod with "papyrus pod load POD"
    Then the pod command exits with status 0
    And the newsroom has 1 Announcement and 1 Delivery
    And the loaded Delivery for "x" is "sent" in manual mode with the words "Rain kept on the land a little longer. Slow water, new this week. #water"
    And the loaded Delivery for "x" has 1 attempt, number 1, "sent" by "ryan"
    And the loaded Delivery for "x" records its approval as a claim, with no approved version
    And the pod report says "1 Announcement, 1 Delivery note(s) loaded as the newsroom's own records"

  Scenario: A load sends nothing and the loaded Delivery waits for nothing
    When I load the pod with "papyrus pod load POD"
    Then the loaded Delivery for "x" is in no sparse index of work to do
    And the load opened no attempt beyond the one the note records

  Scenario: Neither note is ever a page
    When I load the pod with "papyrus pod load POD"
    Then the newsroom has 1 story, the Article, and no story for the Announcement or the Delivery note

  Scenario: A dry run says what would be loaded and writes nothing
    When I load the pod with "papyrus pod load POD --dry-run"
    Then the pod command exits with status 0
    And the pod report says "history: 1 Announcement, 1 Delivery note(s) would be loaded"
    And the newsroom has 0 Announcements and 0 Deliveries

  Scenario: Loading again finds what the first load wrote
    Given the pod is loaded
    When I load the pod again with "papyrus pod load POD"
    Then the newsroom has 1 Announcement and 1 Delivery
    And the pod report says "0 announcement(s) written, 1 already there)"
