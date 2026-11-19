Feature: What a person changed in a Delivery is pinned, and a machine redraft never overwrites it
  The words of a Delivery are blocks, the paragraphs between blank lines. Every version records, for each block, who owns it and whether it is pinned. A block a person
  changed is marked owner human and pinned, and a later machine redraft never overwrites a pinned block: the redraft fills the rest and every pinned block comes out word
  for word, the same rule the Story translations follow. A block a person did not touch stays the machine's and unpinned. Only a person changes or unpins a pinned block,
  and an agent is blocked from doing so at every rung.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3
    And the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with an "email" Delivery for "site-one" under "soft" review drafted as
      """
      Slow water is out.

      Here is why it matters.

      Read more.
      """

  Scenario: The machine's first draft is the machine's and nothing is pinned
    Then version 1 of the Delivery "email" "site-one" has 3 blocks
    And block 1 of version 1 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 2 of version 1 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 3 of version 1 of the Delivery "email" "site-one" is owned by "machine" and not pinned

  Scenario: A block a person changed is theirs and pinned, and the ones they left are still the machine's
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Here is why it matters to the harbour.

      Read more.
      """
    Then version 2 of the Delivery "email" "site-one" has 3 blocks
    And block 1 of version 2 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 2 of version 2 of the Delivery "email" "site-one" is owned by "human" and pinned
    And block 3 of version 2 of the Delivery "email" "site-one" is owned by "machine" and not pinned

  Scenario: A block a person only moved keeps what it was
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Read more.

      Slow water is out.

      Here is why it matters.
      """
    Then block 1 of version 2 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 2 of version 2 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 3 of version 2 of the Delivery "email" "site-one" is owned by "machine" and not pinned

  Scenario: A later machine redraft keeps a pinned block word for word and rewrites the rest
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Here is why it matters to the harbour.

      Read more.
      """
    When the machine redrafts version 2 of the Delivery "email" "site-one" with these words
      """
      A fresh opening line.

      A fresh paragraph about why it matters.

      A fresh closing line.
      """
    Then version 3 of the Delivery "email" "site-one" has these words
      """
      A fresh opening line.

      Here is why it matters to the harbour.

      A fresh closing line.
      """
    And block 1 of version 3 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And block 2 of version 3 of the Delivery "email" "site-one" is owned by "human" and pinned
    And block 3 of version 3 of the Delivery "email" "site-one" is owned by "machine" and not pinned
    And version 2 of the Delivery "email" "site-one" has these words
      """
      Slow water is out.

      Here is why it matters to the harbour.

      Read more.
      """

  Scenario: A redraft that already reproduces the pinned block leaves it where the redraft put it
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Here is why it matters to the harbour.

      Read more.
      """
    When the machine redrafts version 2 of the Delivery "email" "site-one" with these words
      """
      Here is why it matters to the harbour.

      A new second paragraph.
      """
    Then version 3 of the Delivery "email" "site-one" has these words
      """
      Here is why it matters to the harbour.

      A new second paragraph.
      """
    And block 1 of version 3 of the Delivery "email" "site-one" is owned by "human" and pinned
    And block 2 of version 3 of the Delivery "email" "site-one" is owned by "machine" and not pinned

  Scenario: A redraft that is shorter than the pinned block's place does not lose it
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Here is why it matters.

      Read more here, written by Ellie.
      """
    When the machine redrafts version 2 of the Delivery "email" "site-one" with these words
      """
      One short paragraph.
      """
    Then version 3 of the Delivery "email" "site-one" has these words
      """
      One short paragraph.

      Read more here, written by Ellie.
      """
    And block 2 of version 3 of the Delivery "email" "site-one" is owned by "human" and pinned

  Scenario: A person may rewrite a pinned block with an ordinary save
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Ellie's own paragraph.

      Read more.
      """
    When the person "sierra" saves version 2 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Sierra's paragraph instead.

      Read more.
      """
    Then block 2 of version 3 of the Delivery "email" "site-one" is owned by "human" and pinned
    And version 3 of the Delivery "email" "site-one" was saved by "sierra" as human and replaced version 2

  Scenario: A person changes the words of a pinned block and it stays pinned
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Ellie's own paragraph.

      Read more.
      """
    When the person "ellie" changes block 2 of the Delivery "email" "site-one" from version 2 to "Ellie's own paragraph, tightened."
    Then version 3 of the Delivery "email" "site-one" has these words
      """
      Slow water is out.

      Ellie's own paragraph, tightened.

      Read more.
      """
    And block 2 of version 3 of the Delivery "email" "site-one" is owned by "human" and pinned

  Scenario: A person unpins a block and then a redraft may rewrite it
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Ellie's own paragraph.

      Read more.
      """
    When the person "ellie" unpins block 2 of the Delivery "email" "site-one" from version 2
    Then block 2 of version 3 of the Delivery "email" "site-one" is owned by "human" and not pinned
    When the machine redrafts version 3 of the Delivery "email" "site-one" with these words
      """
      A fresh opening line.

      A fresh middle paragraph.

      A fresh closing line.
      """
    Then version 4 of the Delivery "email" "site-one" has these words
      """
      A fresh opening line.

      A fresh middle paragraph.

      A fresh closing line.
      """
    And block 2 of version 4 of the Delivery "email" "site-one" is owned by "machine" and not pinned

  Scenario: Only a block that is pinned is changed as a pinned block
    When the person "ellie" changes block 1 of the Delivery "email" "site-one" from version 1 to "Changed."
    Then the call is refused saying "is not pinned"
    And the Delivery "email" "site-one" is at version 1

  Scenario: A block that is not there is not found
    When the person "ellie" unpins block 9 of the Delivery "email" "site-one" from version 1
    Then the call is refused saying "there is no block 9"

  Scenario: A pinned block is protected from an agent at every rung, through the one door
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Ellie's own paragraph.

      Read more.
      """
    And an announce agent working at the rung "publish_auto" on the channel "email" for the kind "story_published"
    And the writes so far are remembered
    When the announce agent asks the door to change block 2 of version 2 of the Delivery "email" "site-one" to "The agent's idea"
    Then the door answers "blocked"
    And nothing more was written

  Scenario: An agent's save through the door keeps what a person pinned
    Given the person "ellie" saves version 1 of the Delivery "email" "site-one" with these words
      """
      Slow water is out.

      Ellie's own paragraph.

      Read more.
      """
    And an announce agent working at the rung "draft" on the channel "email" for the kind "story_published"
    When the announce agent asks the door to save the words "One.\n\nTwo.\n\nThree." over version 2 of the Delivery "email" "site-one"
    Then the door answers "allowed"
    And version 3 of the Delivery "email" "site-one" has these words
      """
      One.

      Ellie's own paragraph.

      Three.
      """
