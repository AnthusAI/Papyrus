@brand-agnostic
Feature: Messages belong to their author
  A Message records who wrote it (the sub of the signed-in person) and the data API lets that person, and only that person, change
  it. Editors and admins still read and add Messages. An admin can remove anyone's Message for moderation but cannot rewrite it.
  A Message also records when it was edited, and when and by whom it was deleted, so a removal is a soft delete that leaves the
  conversation's replies in place. The router, procedures and other functions write through their own grants, which this does not
  change. These scenarios read the schema the data API is built from; they deploy nothing.

  Scenario: The author alone can change their own Message
    Given the data API schema
    When the rules on Message are read
    Then the author, matched on the sub claim in the authorSub field, can read, update and delete their own Messages
    And no group can update a Message

  Scenario: Editors and admins keep reading and adding, and only admins remove others' Messages
    Given the data API schema
    When the rules on Message are read
    Then editors and admins can read and create Messages
    And only admins can delete a Message they did not write

  Scenario: A Message records edits and deletions
    Given the data API schema
    When the fields of Message are read
    Then Message has editedAt, deletedAt and deletedBySub

  Scenario: Machine writers and other models are untouched
    Given the data API schema
    When the function grants and the other models are read
    Then the functions keep their grants and the assignment function can still create and update Messages
    And MessageThread has no owner rule
    And the typed schema carries the same rule and fields
