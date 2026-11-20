Feature: "Why was this Story not announced?" is a question, not a row
  `papyrus announcements explain --story X` reads the rules that decide whether a Story is announced and says, for each channel, which one applies: the channel's own rules
  (off, not published, type or section not announced, below the bar), the floors under every policy (nothing under three stars, a five only from a person), the source rule
  (a person must have reviewed the Story), and the review policy of the channel. A Story that was announced is told where. The question writes nothing: no row is made for a thing
  that did not happen.

  Background:
    Given an empty announcement catalog that knows its Stories
    And the clock reads "2026-11-17T09:00:00Z"
    And a publication whose announcement review is "soft"
    And the publication announces in "dry_run" mode from 3 stars

  Scenario: A Story under the bar names the rule
    Given the Story "slow-water" is published and titled "Slow water" with 2 stars given by "ellie"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explain command succeeded
    And the explanation names the rule "below_bar" for the channel "x"
    And the explanation for the channel "x" says "It has 2 stars, and the bar for announcements is 3 stars."
    And the question wrote nothing

  Scenario: An unrated Story is never announced
    Given the Story "slow-water" is published and titled "Slow water" and unrated
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "below_bar" for the channel "x"
    And the explanation for the channel "x" says "It has no stars"

  Scenario: A Story that is not published yet
    Given the Story "slow-water" is a draft with 4 stars given by "ellie"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "not_published" for the channel "x"
    And the explanation for the channel "x" says "The Story is not published yet"

  Scenario: A type the publication does not announce
    Given the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    And the Story "slow-water" is a "post"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "type_not_announced" for the channel "x"

  Scenario: Announcements are off
    Given the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    And the publication announces in "off" mode from 3 stars
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "off" for the channel "x"
    And the explanation for the channel "x" says "Announcements are off for this publication"

  Scenario: A five that a machine gave is not announced
    Given the Story "slow-water" is published and titled "Slow water" with 5 stars given by "agent:rate"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "machine_five" for the channel "x"
    And the explanation for the channel "x" says "a machine never supplies a five"

  Scenario: A Story nobody reviewed, on a publication that announces only reviewed Stories
    Given the publication announces only Stories a person has reviewed
    And the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    And the publication announces in "dry_run" mode from 3 stars
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "story_not_reviewed" for the channel "x"
    And the explanation for the channel "x" says "has not been reviewed by a person"

  Scenario: An announce agent that is off prepares no Delivery
    Given a publication whose announce agent is at the rung "off"
    And the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "no_delivery" for the channel "x"
    And the explanation for the channel "x" says "announce agent is off"

  Scenario: Nothing stops a qualifying Story
    Given the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation names the rule "would_announce" for the channel "x"
    And the explanation for the channel "x" says "soft review"
    And the question wrote nothing

  Scenario: A Story that was announced says where
    Given the Story "slow-water" is published and titled "Slow water" with 4 stars given by "ellie"
    And the Story "slow-water" at version 1 has 4 stars given by "ellie"
    And the announce agent announces the Story "slow-water" as "story_published" on these channels
      | channel | account  |
      | x       | handle-1 |
    When a person types "papyrus announcements explain --story slow-water"
    Then the explanation says the channel "x" was announced
    And the explanation for the channel "x" says "Announcement"
    And the question wrote nothing

  Scenario: A Story the site does not have
    When a person types "papyrus announcements explain --story no-such-story"
    Then the command failed with "not_found"
    And the question wrote nothing
