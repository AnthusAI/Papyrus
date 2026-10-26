Feature: A daily Cited Trends run does not write about the same maker every day
  When the trend path runs daily, the same entity keeps topping the ranking while its story waits for an editor. An entity that
  anchored a story draft in the last seven days (the cooldown is configuration, 0 turns it off) cannot anchor another one, unless an
  editor declined that draft. The run record lists the entities that are cooling down and the date of the draft each one anchored.
  Broad kinds such as a licence only ever appear as context, so they never cool down.

  Background:
    Given a weekly knowledge snapshot for the week of "2026-10-19" with two named clusters and five entities
    And the site has the sections "Analysis" and "News"

  Scenario: An entity that anchored a recent draft is passed over and the run says why
    Given an earlier story draft Proposal anchored on "maker--zed" was filed on 2026-10-20
    When the operator drafts trend stories and files them as Proposals
    Then the run did not select "maker--zed" as an anchor and its record says it is cooling down since 2026-10-20

  Scenario: A declined draft does not cool its entities down
    Given an earlier declined story draft Proposal anchored on "maker--zed" was filed on 2026-10-20
    When the operator drafts trend stories and files them as Proposals
    Then the run selected "maker--zed" as an anchor

  Scenario: A draft older than the cooldown does not cool its entities down
    Given an earlier story draft Proposal anchored on "maker--zed" was filed on 2026-10-10
    When the operator drafts trend stories and files them as Proposals
    Then the run selected "maker--zed" as an anchor

  Scenario: The cooldown is configuration and zero turns it off
    Given an earlier story draft Proposal anchored on "maker--zed" was filed on 2026-10-20
    And the anchor cooldown is off
    When the operator drafts trend stories and files them as Proposals
    Then the run selected "maker--zed" as an anchor
