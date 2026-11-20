Feature: A run ends "nothing to do" or "asked" only through the real paths that decide it
  Every finished run says what came of it, and two of the words had no real source. "Nothing to do" is now produced by a shipped procedure
  that looks and finds nothing needing doing: the Reference curation procedure ends it with the reason "already_curated". "Asked" is never a
  procedure's own word. A procedure that needs a person's leave names the operations it wants and does none of them; the runner asks the
  one gate about each, and when the site's policy says a person must do or approve one, the review-request code files the one review request and
  the run ends "asked" with the reason "human_required". Every answer the gate gave is stored on the run record with the policy version, and the
  record names the responsibility and the rung whatever the outcome was. All of it is driven through the runner's own entry point, with the
  site's real policy and run records.

  Background:
    Given a site backend with the published procedure "papyrus.reference.curate"
    And the automation "curation" runs that procedure

  Scenario: The shipped curation procedure ends nothing to do when the Reference is already curated
    Given the automation is adopted as "curate"
    And the policy sets "curate" to "draft"
    And the procedure is the shipped Reference curation procedure
    And the Reference is already curated
    When the runner takes a wake for the automation
    Then the run record is completed with the outcome "nothing" and the reason "already_curated"
    And the run list shows "– Nothing to do (already_curated)"
    And the run record names the responsibility "curate", policy version 1 and the rung "draft"

  Scenario: The same procedure ends did it when the Reference still needs curating
    Given the automation is adopted as "curate"
    And the policy sets "curate" to "draft"
    And the procedure is the shipped Reference curation procedure
    And the Reference needs curating
    When the runner takes a wake for the automation
    Then the run list shows "✓ Did it"
    And the run record names the responsibility "curate", policy version 1 and the rung "draft"

  Scenario: A run that needs a person to approve an operation files one review request and ends asked
    Given the automation is adopted as "illustrate"
    And the policy sets "illustrate" to "propose"
    And the procedure asks the gate for "image_apply"
    When the runner takes a wake for the automation
    Then the run list shows "? Asked (human_required)"
    And one review request is filed on the run, raised by "agent:illustrate", that a person must answer
    And the run record stores the gate's answer "human_required" for "image_apply" under policy version 1
    And the run record names the responsibility "illustrate", policy version 1 and the rung "propose"

  Scenario: The procedure cannot say asked for itself, and cannot hide that a person was needed
    Given the automation is adopted as "illustrate"
    And the policy sets "illustrate" to "propose"
    And the procedure asks the gate for "image_apply" and says it did its work
    When the runner takes a wake for the automation
    Then the run list shows "? Asked (human_required)"

  Scenario: The same call at a higher rung is allowed, so no review request is filed
    Given the automation is adopted as "illustrate"
    And the policy sets "illustrate" to "draft"
    And the procedure asks the gate for "image_apply"
    When the runner takes a wake for the automation
    Then the run list shows "✓ Did it"
    And no review request is filed
    And the run record stores the gate's answer "allowed" for "image_apply" under policy version 1

  Scenario: A run that asks for what no agent may do fails and says so
    Given the automation is adopted as "illustrate"
    And the policy sets "illustrate" to "publish_auto"
    And the procedure asks the gate for "announcements_settings_set"
    When the runner takes a wake for the automation
    Then the run list shows "✗ Failed (gate_blocked)"
    And no review request is filed
    And the run record stores the gate's answer "blocked" for "announcements_settings_set" under policy version 1

  Scenario: A person's own run asks no gate
    Given the procedure asks the gate for "image_apply"
    When a person starts that procedure from their own session
    Then the run list shows "✓ Did it"
    And no review request is filed
    And the run record names no responsibility and no rung
