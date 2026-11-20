Feature: No text in the catalog
  The catalog holds short fields only. A Delivery's words, and any HTML or Markus a channel needs, are a file in S3 attached to the Delivery. The row holds the
  file's key and a hash over the words and the picture. A row that carries post text is refused, and so is any other catalog row that would carry the words of
  a Delivery.

  Background:
    Given an empty announcement catalog
    And the clock reads "2026-11-16T14:00:00Z"
    And the Story "slow-water" is at version 3

  Scenario: A Delivery row holds a key and a hash, never the words
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text                                          |
      | x       | handle-1 | none     | Slow water: a look at how tides keep a secret |
    Then the Delivery row "x" "handle-1" has a text key and a content hash
    And the Delivery row "x" "handle-1" contains none of "Slow water" anywhere
    And the Delivery "x" "handle-1" has these words in S3 "Slow water: a look at how tides keep a secret"

  Scenario: The content hash follows the words and the picture
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text        | image        |
      | x       | handle-1 | none     | First words | media/a.jpg  |
      | x       | handle-2 | none     | First words | media/b.jpg  |
      | x       | handle-3 | none     | Other words | media/a.jpg  |
    Then the content hashes of "handle-1", "handle-2" and "handle-3" are all different

  Scenario: A row that carries text is refused
    When a catalog row carrying the field "text" is checked
    Then the call is refused saying "The catalog holds no text"
    When a catalog row carrying the field "html" is checked
    Then the call is refused saying "The catalog holds no text"

  Scenario: The Announcement row holds no text either
    When the decision "story-published:slow-water" of kind "story_published" is made for the Story "slow-water" with these Deliveries
      | channel | account  | approval | text              |
      | x       | handle-1 | none     | Plain words here  |
    Then the Announcement row contains none of "Plain words" anywhere

  Scenario: The words are one file the upload function accepts
    Then the words of a Delivery are uploaded as role "delivery_text" for owner kind "delivery"
