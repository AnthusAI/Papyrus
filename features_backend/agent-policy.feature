Feature: The agent policy document
  How far each always-on agent may go on a site is data, not code. One document per site, a versioned site document of kind
  "agents", holds the rung of each responsibility: off, observe, propose, draft, prepare, publish_soft, publish_auto. It can narrow
  a rung by section, story type, channel, announcement kind or list, and the narrowest override decides. It also holds a pause for
  each agent and for the whole site, and the quiet window, the loop limit, the budget and the model tiers that later tasks read.
  Every change is a new version that says who made it, when and why. Only an admin who is a person changes it: an editor is
  refused and an agent is blocked at every rung. A deploy never writes it, so a deploy can never change a rung or lift a pause.
  Each run, started or skipped, names the policy version and the rung it was decided under.

  Scenario: A new site starts quiet
    Given a site that has never saved an agent policy
    Then every responsibility is at "off" under policy version 0
    And a wake for "rate" starts nothing and says "rate is off"

  Scenario: An admin raises a rung with a reason
    Given a site that has never saved an agent policy
    When an admin sets "rate" to "propose" because "Start with suggestions only"
    Then the policy is version 1
    And version 1 records the admin, a time and the reason "Start with suggestions only"
    And the rung of "rate" is "propose"

  Scenario: A rung change is a new version and history stays
    Given a site where "rate" was set to "observe" and then to "draft"
    Then the policy is version 2
    And version 1 still holds "rate" at "observe"
    And each of the two versions records who, when and why

  Scenario: An editor cannot change the policy
    Given a site where "rate" is at "observe"
    When an editor tries to set "rate" to "publish_auto" because "Ship it"
    Then the change is refused as not authorized
    And the policy is still version 1 and the rung of "rate" is "observe"

  Scenario: An agent cannot change the policy, even at the top rung
    Given a site where "rate" is at "publish_auto"
    When an agent tries to set "rate" to "off" because "I would rather not"
    Then the change is blocked
    And the policy is still version 1 and the rung of "rate" is "publish_auto"

  Scenario: A change with no reason is refused
    Given a site that has never saved an agent policy
    When an admin sets "rate" to "propose" because " "
    Then the change is refused as invalid
    And the policy is still version 0

  Scenario: A rung that does not exist is refused
    Given a site that has never saved an agent policy
    When an admin sets "rate" to "autopilot" because "Try it"
    Then the change is refused as invalid
    And the policy is still version 0

  Scenario: A section override beats the site rung
    Given a site where "improve" is at "prepare"
    And an admin gave "improve" the rung "publish_soft" for section "briefs" because "Briefs are low risk"
    Then the rung of "improve" for section "briefs" is "publish_soft", chosen by an override
    And the rung of "improve" for section "features" is "prepare"
    And the rung of "improve" with nothing in view is "prepare"

  Scenario: The narrowest matching override decides
    Given a site where "announce" is at "publish_soft"
    And an admin gave "announce" the rung "prepare" for channel "linkedin" because "Check these first"
    And an admin gave "announce" the rung "publish_auto" for list "weekly" because "The weekly list is proven"
    And an admin gave "announce" the rung "draft" for channel "linkedin" and kind "roundup" because "Roundups on LinkedIn stay drafts"
    Then the rung of "announce" for channel "linkedin" is "prepare"
    And the rung of "announce" for channel "linkedin" and kind "roundup" is "draft"
    And the rung of "announce" for list "weekly" and channel "linkedin" is "publish_auto"
    And the rung of "announce" for channel "email" is "publish_soft"

  Scenario: A kind override is narrower than a channel override
    Given a site where "announce" is at "publish_soft"
    And an admin gave "announce" the rung "publish_auto" for channel "linkedin" because "LinkedIn goes by itself"
    And an admin gave "announce" the rung "prepare" for kind "roundup" because "Roundups wait for a person"
    Then the rung of "announce" for channel "linkedin" and kind "roundup" is "prepare"
    And the rung of "announce" for channel "linkedin" and kind "story_published" is "publish_auto"

  Scenario: Two overrides cannot claim the same scope
    Given a site where "improve" is at "prepare"
    And an admin gave "improve" the rung "publish_soft" for section "briefs" because "Briefs are low risk"
    When an admin sets the rung of "improve" for section "briefs" to "draft" because "Briefs need more care"
    Then there is still one override for section "briefs" and it holds "draft"

  Scenario: Pausing an agent stops its new runs and says why
    Given a site where "translate" is at "publish_soft"
    When an admin pauses "translate" because "A glossary error is being fixed"
    Then a wake for "translate" starts nothing and says "translate is paused: A glossary error is being fixed"
    And a wake for "rate" is not affected by that pause

  Scenario: Pausing the site stops every agent
    Given a site with "rate" at "draft" and "translate" at "publish_soft"
    When an admin pauses the site because "Incident review"
    Then a wake for "rate" starts nothing and says "The site is paused: Incident review"
    And a wake for "translate" starts nothing and says "The site is paused: Incident review"

  Scenario: Resuming does not replay skipped ticks
    Given a site where "rate" is at "draft"
    And an admin paused "rate" because "Checking the rating rules"
    And three timed wakes for "rate" came and were each skipped
    When an admin resumes "rate" because "Rules checked"
    Then no run is started for the three skipped wakes
    And the next wake for "rate" starts under the new policy version

  Scenario: Every run names the policy version and rung it ran under
    Given a site where "rate" is at "draft"
    When an admin sets "rate" to "propose" because "Back to suggestions"
    Then a wake for "rate" starts, and its run record carries policy version 2 and rung "propose"
    And a skipped wake carries the policy version and rung it was decided under as well

  Scenario: Observe starts a run that only records
    Given a site where "rate" is at "observe"
    Then a wake for "rate" starts at the rung "observe"

  Scenario: The quiet window, loop limit, budget and tiers are held for later tasks
    Given a site that has never saved an agent policy
    When an admin sets a quiet window, a budget and the model tiers for the site because "Set the working rules"
    And an admin sets the loop limit of "improve" to 3 because "Stop endless revisions"
    Then the policy holds those values exactly as given
    And an invalid quiet window is refused naming the field

  Scenario: Reading the policy changes nothing
    Given a site where "rate" is at "draft"
    When the runner reads the policy five times
    Then the policy is still version 1
    And the policy store was not written to
