Feature: The runner reads the site's agent policy before it starts a run
  The procedure runner is the one place every wake of an automation arrives. Before it loads anything it asks the site's agent policy
  whether the run may start. A run that may not start is not hidden: it has a run record that says "nothing to do", with a reason
  code (not_adopted, rung_off or paused) and the words, and it names the policy version and the rung it was decided under.

  An automation that was running before the policy existed is not enforced until a person adopts it onto a responsibility with
  "papyrus automations adopt". The runner never guesses a responsibility, and a responsibility the policy has not named is "off"
  (the architecture, section 5). Nothing starts for lack of a policy; the runner has no fallback that starts a run anyway.

  Background:
    Given a site backend with the published procedure "distinctive.ttab.ruling-analysis"
    And the automation "distinctive.ttab" runs that procedure

  Scenario: A paused agent's wake does not start a run and says why
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "observe"
    And an admin paused "accept" because "Checking the acceptance rules"
    When a wake arrives for the automation
    Then no procedure ran
    And the run record says nothing to do with the reason "paused"
    And the run record says "accept is paused: Checking the acceptance rules"
    And the run record names policy version 2 and the rung "observe"

  Scenario: A run records the policy version and the rung it ran at
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "draft"
    When a wake arrives for the automation
    Then the procedure ran once
    And the run record names the responsibility "accept", policy version 1 and the rung "draft"

  Scenario: A site with no policy document starts no agent
    Given the automation is adopted as "accept"
    And the site has never saved an agent policy
    When a wake arrives for the automation
    Then no procedure ran
    And the run record says nothing to do with the reason "rung_off"
    And the run record names policy version 0 and the rung "off"

  Scenario: An automation nobody has adopted starts nothing, whatever the policy says
    Given the policy sets "accept" to "publish_soft"
    When a wake arrives for the automation
    Then no procedure ran
    And the run record says nothing to do with the reason "not_adopted"
    And the run record names no responsibility and no rung

  Scenario: A responsibility the policy does not name is off
    Given the automation is adopted as "accept"
    And the policy sets "rate" to "draft"
    When a wake arrives for the automation
    Then no procedure ran
    And the run record says nothing to do with the reason "rung_off"

  Scenario: A paused site stops every adopted automation
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "draft"
    And an admin paused the site because "Incident review"
    When a wake arrives for the automation
    Then no procedure ran
    And the run record says nothing to do with the reason "paused"
    And the run record says "The site is paused: Incident review"

  Scenario: A wake with no automation starts nothing
    When a wake arrives that names no automation
    Then no procedure ran
    And the run record says nothing to do with the reason "not_adopted"

  Scenario: A policy that cannot be read starts nothing and the run says it failed
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "draft"
    And the policy document cannot be read
    When a wake arrives for the automation and is refused
    Then no procedure ran
    And the run record is failed with the reason "policy_unreadable"

  Scenario: A skipped run shows in the automation's run list as nothing to do
    Given the automation is adopted as "accept"
    And the site has never saved an agent policy
    When a wake arrives for the automation
    Then the run list shows "– Nothing to do (rung_off)"

  Scenario: The policy is read by key, the live version only
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "observe"
    And the policy sets "accept" to "draft"
    When a wake arrives for the automation
    Then the runner read the policy document row, the live version's row and the live version's body, and nothing else

  Scenario: A person's own run in their session is not limited by an agent's rung
    Given the site has never saved an agent policy
    When a person starts the procedure from their own session
    Then the procedure ran once
    And the run record names no responsibility and no rung

  Scenario: A request that names no site policy location is refused and the refusal is recorded on the run
    Given the automation is adopted as "accept"
    And the policy sets "accept" to "draft"
    When a wake arrives with no tenant and no site bucket
    Then the request is refused because it names no site policy
    And the run record is failed with the reason "no_site_policy"
    And the run list shows "✗ Failed (no_site_policy)"
    And the run record belongs to the automation
    And no procedure ran
