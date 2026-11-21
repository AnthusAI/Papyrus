Feature: The announce agent is a core agent definition that listens for the Item changes that start an Announcement
  The engine ships the definition of the standing responsibility "announce". It listens for two changes to a Story's own record, both from the Item change
  feed through the site's wake queue: the Story entering the published stage (its page is live) and a published Story's rating being set, changed or cleared. It
  listens for no schedule and for no other change, because nothing a publish does calls it. It runs one wake at a time for the agent, because every wake may spend from
  one account's budget and write to one account's Deliveries, and a repeat is harmless because the once-only key of the Announcement makes it find the first
  decision. Its procedure is registered with the engine's procedures, so the release that carries the definition carries the procedure it names. The definition names
  no rung, pause, budget or model: how far the agent goes is the site's agent policy.

  Scenario: The engine ships the announce agent definition
    When the engine's core definitions are validated
    Then the set is accepted
    And the core set holds the definition "announce" for the responsibility "announce"
    And the definition "announce" names the procedure "announce_story"
    And the procedure "announce_story" is registered with its file

  Scenario: It listens for the page going live, a rating change and a Delivery's approval, and for nothing else
    When the engine's core definitions are validated
    Then the definition "announce" listens for the Item change "stage_entered" with the filter "stage" "published"
    And the definition "announce" listens for the Item change "rated" with the filter "stage" "published"
    And the definition "announce" listens for the Delivery change "approved"
    And the definition "announce" listens for no other change

  Scenario: It runs one wake at a time, on the work tier
    When the engine's core definitions are validated
    Then the definition "announce" runs one at a time by "agent"
    And the definition "announce" has the tier "work"

  Scenario: Each operation is named at the lowest rung of the operation table
    When the engine's core definitions are validated
    Then every operation of the definition "announce" is named at the lowest rung the operation table allows

  Scenario: The announce agent never announces a Story that is not live or is under three stars, and never makes a second Announcement
    When the engine's core definitions are validated
    Then the definition "announce" must never "Announce a Story whose page is not live now"
    And the definition "announce" must never "Make a second Announcement"
    And the definition "announce" must never "Assign a rating"
    And the definition "announce" must never "Send a message"

  Scenario: The definition names no rung, pause, budget or model
    When the engine's core definitions are validated
    Then the definition "announce" names no rung, pause, budget or model

  Scenario: papyrus agents validate accepts the engine's core definitions
    When papyrus agents validate is run on the engine's core definitions with the network closed
    Then the command exits with status 0
    And the answer lists "announce" among the definitions using the operation "announcements_explain"
