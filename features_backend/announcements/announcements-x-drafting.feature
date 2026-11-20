Feature: The words of an X post say only what the Story says, and a draft that fails asks for help once
  A post on X speaks for the publication. It is drafted from the Story's title, dek and summary, checked automatically, and the post exactly as it will go is the words
  of the Delivery. A draft that fails any check is not an announcement: its Delivery is blocked with the reason "check failed", and exactly one review request, a flag that
  nobody waits for, is raised for the Announcement in the editor's inbox (not one for each channel, and not one for each wake). The machine does not draft it again by itself:
  only a change of an input, the Story's version or the guidelines, makes it try again, and then it tries once. An editor who edits the words saves a new version like on any
  Delivery.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars, in Dry run

  Scenario: A draft is written from the Story and carries its link
    When a 5-star Article "Can a system keep a secret from itself?" is published
    Then the model was given only the title, the dek and the summary
    And the post in the Delivery's words carries the Article's link

  Scenario: The Delivery lists the checks the draft passed
    When a 5-star Article is published
    Then the Delivery lists the checks length, markup and facts as passed
    And the words are kept in S3, not on the row

  Scenario: A draft that adds a claim is blocked
    Given the model drafts "The first proof ever that a system can keep a secret."
    When a 5-star Article is published
    Then the X Delivery reads "Blocked: check failed"
    And the Announcement's flag says "This claim is not in the Story: The first proof ever that a system can keep a secret."

  Scenario: A draft too long for X is blocked
    Given the model drafts a post of 300 characters
    When a 5-star Article is published
    Then the X Delivery reads "Blocked: check failed"
    And the Announcement's flag says "Too long for X by"

  Scenario: A draft that invents a mention is blocked
    Given the model drafts "A look at secrets, with @someone."
    When a 5-star Article is published
    Then the Announcement's flag says "A post may not invent @someone: it is not in the Story"

  Scenario: A draft with its own link is blocked
    Given the model drafts "Read it at https://example.org/x"
    When a 5-star Article is published
    Then the X Delivery reads "Blocked: check failed"

  Scenario: An editorial rule violation blocks the draft
    Given the editorial rules reject the draft with "Uses an AI-writing cliché"
    When a 5-star Article is published
    Then the Announcement's flag says "Uses an AI-writing cliché"

  Scenario: A site without writing guidelines gets no draft
    Given the site has no writing guidelines
    When a 5-star Article is published
    Then the X Delivery reads "Blocked: check failed"
    And the Announcement's flag says "This publication has no writing guidelines"
    And the Delivery has no words yet

  Scenario: A blocked draft raises exactly one review request
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    When the announce agent wakes for the Article
    And a person rates the Article again and the announce agent wakes for it
    Then exactly 1 review request was raised about the Announcement
    And the Delivery is not in the due index

  Scenario: A blocked draft is not drafted again until the Story or the guidelines change
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    When the announce agent wakes for the Article
    Then the model was asked once
    And the X Delivery reads "Blocked: check failed"

  Scenario: A new version of the Story drafts the blocked Delivery again, once
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    And the model now drafts "A look at whether a system can keep a secret from itself."
    When the Story changes to version 2 and the announce agent wakes for it
    Then the model was asked twice
    And the X Delivery reads "Dry run: not sent"
    And the Delivery has these words in S3 "A look at whether a system can keep a secret from itself."
    And exactly 1 review request was raised about the Announcement

  Scenario: Changed guidelines draft the blocked Delivery again
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    And the model now drafts "A look at whether a system can keep a secret from itself."
    When the guidelines change and the announce agent wakes for the Article
    Then the model was asked twice
    And the X Delivery reads "Dry run: not sent"

  Scenario: A draft that still fails after an input changed is not tried in a loop
    Given the model drafts "The first proof ever that a system can keep a secret."
    And a 5-star Article is published
    When the Story changes to version 2 and the announce agent wakes for it
    And the announce agent wakes for the Article
    Then the model was asked twice
    And the X Delivery reads "Blocked: check failed"
    And exactly 1 review request was raised about the Announcement

  Scenario: A crash between the Delivery and its block is finished on the next wake
    Given the model drafts "The first proof ever that a system can keep a secret."
    And the next write of a blocked Delivery fails as if the connection dropped
    When a 5-star Article is published
    Then the announce agent's run failed
    When the announce agent wakes for the Article
    Then the X Delivery reads "Blocked: check failed"
    And exactly 1 review request was raised about the Announcement
    And the model was asked once

  Scenario: Post length is counted the way X counts it
    Then "A link https://example.org/a/very/long/path/that/goes/on counts" weighs 23 for the link plus its other characters
    And a text of 140 Japanese characters weighs 280
    And a text of 141 Japanese characters is too long by 2

  Scenario: The link keeps the Story's own query and gets the tags
    Then the link "https://example.org/a?x=1&utm_source=old" becomes "https://example.org/a?x=1&utm_source=x&utm_medium=social&utm_campaign=announcement"
