Feature: Announcement text says only what the Story says
  A post on X speaks for the publication. It is drafted from the Story's title, dek and
  summary, checked automatically, and posted at once if it passes: no one approves it.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the site announces Articles rated 5 stars, in Dry run

  Scenario: A draft is written from the Story and carries its link
    When a 5-star Article "Can a system keep a secret from itself?" is published
    Then the model was given only the title, the dek and the summary
    And the recorded post carries the Article's link

  Scenario: A draft that adds a claim is stopped
    Given the model drafts "The first proof ever that a system can keep a secret."
    When a 5-star Article is published
    Then the Article is "Blocked: check failed"
    And the editors see "This claim is not in the Story: The first proof ever that a system can keep a secret."
    And the editors are told a check failed

  Scenario: A draft too long for X is stopped
    Given the model drafts a post of 300 characters
    When a 5-star Article is published
    Then the Article is "Blocked: check failed"
    And the editors see a message starting "Too long for X by"

  Scenario: A draft that invents a mention is stopped
    Given the model drafts "A look at secrets, with @someone."
    When a 5-star Article is published
    Then the editors see "A post may not invent @someone: it is not in the Story"

  Scenario: A draft with its own link is stopped
    Given the model drafts "Read it at https://example.org/x"
    When a 5-star Article is published
    Then the Article is "Blocked: check failed"

  Scenario: An editorial rule violation stops the draft
    Given the editorial rules reject the draft with "Uses an AI-writing cliché"
    When a 5-star Article is published
    Then the editors see "Uses an AI-writing cliché"

  Scenario: A site without writing guidelines gets no draft
    Given the site has no writing guidelines
    When a 5-star Article is published
    Then the Article is "Blocked: check failed"
    And the editors see a message starting "This publication has no writing guidelines"

  Scenario: A passing draft needs no approval
    Given the mode is On
    When a 5-star Article is published
    Then the announcement is "Posting"
    And no approval step exists anywhere in the settings

  Scenario: A failed check is not tried again by itself
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    When the Article is announced again because a corrected version was published
    Then there is still exactly one announcement for it
    And the model was asked once

  Scenario: Post length is counted the way X counts it
    Then "A link https://example.org/a/very/long/path/that/goes/on counts" weighs 23 for the link plus its other characters
    And a text of 140 Japanese characters weighs 280
    And a text of 141 Japanese characters is too long by 2

  Scenario: The link keeps the Story's own query and gets the tags
    Then the link "https://example.org/a?x=1&utm_source=old" becomes "https://example.org/a?x=1&utm_source=x&utm_medium=social&utm_campaign=announcement"
