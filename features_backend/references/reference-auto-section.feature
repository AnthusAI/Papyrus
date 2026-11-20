Feature: An accepted Reference gets its Section automatically when the site cyclotron is sure enough, and never against a person
  The Videos and Findings pages group References by newsroom Section, and only References that carry a Section can be grouped. Tagging used to
  be optional and by hand. Now, when a Reference is accepted, the site cyclotron's section selector (the Jev decision model, taught only from the
  Sections editors chose, its Sections and rubrics taken from the site's own NewsroomSection records) proposes one Section. It is set only when the
  selector is at least as sure as a threshold learned from held-out editor choices: the approved Section proof cross-validates the selector, and
  the threshold is the smallest confidence whose held-out decisions agree with editors with a 95% lower bound at or above the target precision.
  Below it nothing is set, never a guess. A Section a person set, and a person's clear, are never changed. The machine's tag says it is the
  machine's (auto:cyclotron, actor kind cyclotron), names the selector decision it acted on and the evidence, and an editor changes or clears it
  like any other. The site sweep does this for each Reference accepted since its last pass; `papyrus references auto-section` is the same pass on
  its own, for the backfill. Everything here is synthetic: an in-memory data client and a scripted model, with no live model call.

  Background:
    Given a Machines on Machines style site whose Sections are Security, Music and Art under prefixed ids

  Scenario: An accepted video gets the Section the selector is sure of, recorded as the machine's
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted video "video-a" titled "Clearly a security exploit walkthrough" with no section
    When the automatic Section pass runs
    Then "video-a" is in the section "machines-on-machines#security"
    And the section of "video-a" was set by the machine, naming the selector decision, the model version and the learned threshold

  Scenario: A Reference the selector is unsure about keeps no Section
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted Reference "video-b" titled "A music performance by a robot" with no section
    When the automatic Section pass runs
    Then "video-b" has no section
    And the result says "video-b" was left without a section because it is below the learned threshold

  Scenario: A Section a person set is never overwritten
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted Reference "video-c" titled "Clearly a security talk" that a person put in "machines-on-machines#art"
    When the automatic Section pass runs
    Then "video-c" is in the section "machines-on-machines#art"
    And "video-c" was not a candidate because a person set or cleared its section

  Scenario: A person's clear sticks
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted Reference "video-d" titled "Clearly a security talk" whose section a person cleared
    When the automatic Section pass runs
    Then "video-d" has no section
    And "video-d" was not a candidate because a person set or cleared its section

  Scenario: Without held-out evidence nothing is set and no model is asked
    Given the site has no approved Section proof
    And an accepted video "video-e" titled "Clearly a security exploit walkthrough" with no section
    When the automatic Section pass runs
    Then "video-e" has no section
    And the result says no Section is set until there is a learned threshold
    And no section model was asked and nothing was decided

  Scenario: Running again decides nothing new and writes nothing new
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted video "video-f" titled "Clearly a security exploit walkthrough" with no section
    And an accepted Reference "video-g" titled "A music performance by a robot" with no section
    When the automatic Section pass runs
    And the automatic Section pass runs again over every accepted Reference
    Then no new section decision or write is made
    And "video-f" is in the section "machines-on-machines#security"

  Scenario: The backfill's dry run shows what it would set and writes nothing
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted video "video-h" titled "Clearly an art installation made by a model" with no section
    When the automatic Section backfill runs as a dry run
    Then the dry run lists "video-h" for "machines-on-machines#art" with the model's confidence and the evidence
    And the dry run wrote nothing to the site and kept no cyclotron store
    And "video-h" has no section

  Scenario: The site sweep tags the References accepted since its last pass
    Given an approved Section proof whose held-out selector decisions agree with editors when the selector is sure
    And an accepted video "video-i" titled "Clearly a music video generated end to end" with no section
    When the site sweep with automatic Sections runs
    Then "video-i" is in the section "machines-on-machines#music"
    And the sweep reports the automatic Section of "video-i"
