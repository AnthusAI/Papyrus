Feature: Examples reach the drafter, and every draft names what it read
  Before the drafter writes, it loads the active examples that apply to the channel and kind it is writing for: the ones for the whole publication, for the channel, and for the
  kind on the channel, newest first and within a character budget. Each is the machine's draft beside the words a person made of it and, when they gave one, why. An example for
  X is not loaded when the drafter writes for email, and an example a person turned off, or one an accepted guideline was made from (absorbed), is not loaded at all. Each draft
  records what it read: the guideline layers (scope, item, version and hash of each) and the examples, and "papyrus announcements explain --delivery" prints them, so "why did it
  write this?" always has an answer. The model is a stand-in that returns the words it is told to and shows what it was given.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On

  Scenario: A draft after an example for the channel follows it, and the Delivery lists the example it read
    Given an Article was announced on X, rewritten by the person "ellie" as "A secret kept from itself." and sent, who said it reaches the "channel" with the reason "Open with the verb."
    And the model now drafts "Keep a secret from itself."
    When a second 5-star Article is published
    Then the model was told the person's version "A secret kept from itself."
    And the model was told the reason "Open with the verb."
    And the model was shown the draft "A look at whether a system can keep a secret from itself."
    And the draft of the second Article lists the first Article's Delivery among the examples it read
    And explaining the second Article's X Delivery names the example as "active" for the "channel"

  Scenario: A draft with no example reads none and says so
    When a 5-star Article is published
    Then the model was told no earlier drafts a person rewrote
    And explaining the X Delivery lists 0 examples

  Scenario: The guideline layers a draft read are recorded with their version and hash
    Given the writing guidelines have the layers "publication" at version 4 with the hash "ab12cd" and "section" at version 2 with the hash "ef34ab"
    When a 5-star Article is published
    Then explaining the X Delivery lists the guideline layers "publication" version 4 and "section" version 2 with their hashes

  Scenario: An example for X is loaded for X and not for email
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, who said it reaches the "channel"
    Then 1 example is loaded for the channel "x" and the kind "story_published"
    And 0 examples are loaded for the channel "email" and the kind "story_published"

  Scenario: An example for a kind is loaded for that kind and not for another
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, who said it reaches the "kind"
    Then 1 example is loaded for the channel "x" and the kind "story_published"
    And 0 examples are loaded for the channel "x" and the kind "roundup"

  Scenario: An example for the whole publication is loaded on every channel
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, who said it reaches the "publication"
    Then 1 example is loaded for the channel "email" and the kind "roundup"

  Scenario: A candidate and a "just this one" are never loaded
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, with no scope chosen
    And an Article was announced on X, rewritten by the person "ellie" as "Slow water arrives." and sent, who said it reaches the "this_one"
    Then 0 examples are loaded for the channel "x" and the kind "story_published"

  Scenario: Examples come newest first and the budget leaves the older ones out
    Given an Article was announced on X, rewritten by the person "ellie" as "First rewrite, the oldest." and sent, who said it reaches the "channel"
    And an Article was announced on X, rewritten by the person "ellie" as "Second rewrite, the middle." and sent, who said it reaches the "channel"
    And an Article was announced on X, rewritten by the person "ellie" as "Third rewrite, the newest." and sent, who said it reaches the "channel"
    Then the examples loaded for the channel "x" and the kind "story_published" read newest first: "Third rewrite, the newest.", "Second rewrite, the middle.", "First rewrite, the oldest."
    When the examples are loaded for the channel "x" and the kind "story_published" within a budget that holds two of them
    Then the examples loaded read: "Third rewrite, the newest.", "Second rewrite, the middle."
    And 1 example was left out by the budget

  Scenario: Turning an example off removes it from the next draft
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, who said it reaches the "channel"
    When the person "ada" turns the first example off because "It no longer fits our tone."
    Then 0 examples are loaded for the channel "x" and the kind "story_published"
    And the first example is "off" and in no partition of active examples
    And the first example's history says "example off: It no longer fits our tone."

  Scenario: An example an accepted guideline was made from is absorbed and no longer loaded by itself
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, who said it reaches the "channel"
    When the first example is absorbed into an accepted guideline
    Then 0 examples are loaded for the channel "x" and the kind "story_published"
    And the first example is "absorbed" and in no partition of active examples

  Scenario: Only an active example can be stopped, and a stop says why
    Given an Article was announced on X, rewritten by the person "ellie" as "Slow water has landed in the harbour." and sent, with no scope chosen
    When the person "ada" turns the first example off because "No longer wanted."
    Then the call is refused saying "is not an active example"
