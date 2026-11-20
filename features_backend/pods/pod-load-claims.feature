@pod @checklist-gate
Feature: A review stamp in a pod stays a claim after the load
  A pod is a folder of files, and a review stamp in a note (`reviewedBy`, `reviewedOn`, `reviewedHash`) or a `rating` is a line of text anyone can type.
  Loaded, it is recorded and shown as a claim: "Recorded in the pod by <name>, not verified". It never satisfies a hard gate (a site that needs a person's
  approval to publish), a required checklist step, `publishRequiresRating` or a five-star rule, because those read the newsroom's own records, a signed-in
  person's rating and a review request a person answered. A person confirms once in the newsroom, and that is the real stamp. The load makes no checklist
  and closes no step.

  Background:
    Given a signed-in newsroom with no stories
    And a started pod
    And the pod file "slow-water.md" has this text:
      """
      ---
      id: https://example.org/id/sample-0041
      type: papyrus:Article
      title: Slow water
      stage: copywriting
      rating: 4
      reviewedBy: Ada Example
      reviewedOn: 2026-11-12
      ---
      Slow water keeps rain on the land a little longer.
      """
    And the pod note "slow-water.md" is stamped with the hash of its body
    And the pod is a git repository with everything committed

  Scenario: The newsroom shows the stamp as a claim that is not verified
    Given the pod is loaded
    When I run "papyrus stories show" for the note "slow-water.md"
    Then the load output says "Recorded in the pod by Ada Example on 2026-11-12, not verified"
    And the load output says "Rated 4 in the pod, not verified"

  Scenario: A claimed rating is not an editor's star rating
    Given the pod is loaded
    Then the story for the note "slow-water.md" has no star rating in the newsroom

  Scenario: A claimed rating does not satisfy a site that requires a rating before publishing
    Given the pod is loaded
    And the site requires a rating before publishing
    Then the rating step is still open for the story for the note "slow-water.md"
    When a person closes every required step of the story for the note "slow-water.md" except the rating
    And an editor publishes the story for the note "slow-water.md"
    Then the publish was refused with the code "checklist-open"
    And the publish was refused saying "Rate the Story (rated)"

  Scenario: A claimed review does not close a required step
    Given the pod is loaded
    When an editor publishes the story for the note "slow-water.md"
    Then the publish was refused with the code "checklist-open"

  Scenario: A claimed review does not pass a site that needs a person's approval
    Given the pod is loaded
    And a person closes every required step of the story for the note "slow-water.md" except the rating
    And the newsroom requires a person's approval before anything publishes
    When a person without the site's approval publishes the story for the note "slow-water.md"
    Then the publish was refused with the code "approval-required"
    And no story is published

  Scenario: A claim is carried again by the next load without becoming more
    Given the pod is loaded
    And the pod file "slow-water.md" has "title: Slow water" replaced by "title: Slow water, slowly"
    And the pod's changes are committed
    When I load the pod again with "papyrus pod load POD"
    Then the story for the note "slow-water.md" has 2 versions
    And the story for the note "slow-water.md" carries the pod key "reviewedBy" with the value "Ada Example"
    And the story for the note "slow-water.md" has no star rating in the newsroom

  Scenario: The load report says the review is a claim
    When I load the pod with "papyrus pod load POD"
    Then the pod report says "slow-water.md: review recorded as a claim, not verified; a person confirms it in the newsroom"
