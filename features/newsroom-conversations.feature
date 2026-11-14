@brand-agnostic @conversation-fixtures
Feature: Editors write messages on a Reference and reply to each other
  When a Reference gives an editor an idea there is somewhere to write it down. Under the Reference's review card is a message box:
  the messages so far, a box that says "Add a message…" and a Post button. A message shows the moment it is posted, as the signed-in
  author, and is saved against that Reference: all the messages about one Reference live in one conversation, found by the Reference
  itself. Every message has a Reply button that opens the same box under it, and the reply is nested beneath it. A reply to a reply
  stays flat under the same top-level message and says who it answers. If a save fails the message is taken back, the reason is said
  in words with an icon, and what was typed is kept. A Reference's card in the feed shows how many messages it has, as an icon and a
  number. The "Why?" note on a vote is a separate thing: it teaches the Cyclotron and is not a message. These scenarios use synthetic
  data in an isolated browser at 375 and 1440 pixels and never touch production.

  Scenario: An editor posts a message on a Reference
    Given a Reference open for review with no messages yet
    When the editor writes a message and taps Post
    Then the message shows at once, marked as sending in words, and the box clears
    And the saved message names its author without the full address
    And the message is saved in the conversation of that Reference
    And the feed's message count follows what is written

  Scenario: A reply is nested under the message it answers
    Given a Reference open for review with one message
    When the editor taps Reply on it, writes a reply and taps Reply
    Then the reply sits under that message and the reply box closes
    And the reply is saved with the message it answers as its parent

  Scenario: A reply to a reply stays flat under the same message and says who it answers
    Given a Reference open for review with a message, a reply, a reply to that reply, and a second message
    When the editor opens the conversation
    Then there are two top-level messages and both replies sit under the first, one level deep
    And the reply to a reply says "In reply to" and the name of the author it answers, with an icon
    And a new reply to that reply lands under the same top-level message

  Scenario: A refused save keeps the typed text
    Given a Reference open for review where the backend refuses to save
    When the editor writes a message and taps Post
    Then the message is taken back out of the list
    And the failure is said in words with an icon, never by colour alone
    And what the editor typed is still in the box

  Scenario: A feed card shows how many messages the Reference has
    Given a feed of References where one has three messages, one has one and one has none
    When the editor opens the feed
    Then a card with messages shows a message icon and the number, labelled with the count in words
    And a card with no messages shows no count

  Scenario: The conversation is flat tones and rounded rectangles
    Given a Reference open for review with several messages and a reply box open
    When the editor looks at the conversation at 375 and 1440 pixels
    Then no message, box or button has a border, an outline or a rule
    And there are no drop-downs and nothing scrolls sideways

  Scenario: Conversations are found by their anchor and written safely
    Given the conversation helpers
    When they build keys, number messages, nest replies and write
    Then the anchor key names the Reference, and one thread id follows from it
    And a create that loses the race for its sequence number retries with the next number
    And a thread that two editors start at once is shared, not split
    And replies nest one level deep
