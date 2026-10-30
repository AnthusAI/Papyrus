@brand-agnostic @conversation-fixtures
Feature: One Messages page for every conversation
  The Messages page lists every conversation, newest activity first, as cards in a grid. The sections are buttons: All, References,
  Stories, Chats and Other, and All is where the page opens. Messages lead each card: the latest few, with who wrote them and how long
  ago, replies indented one level, a Reply button and an "Add a message…" box; the rest are one button away, "Show all" with the count.
  A conversation about a Reference shows that Reference below the messages, as an attachment with its picture, headline and dek and
  no decision controls; it opens the Reference. A conversation about a Story shows the Story's title, its stage as text and a link.
  Edition and section forum threads are ordinary conversations under Other and open their own thread view; chat sessions are under
  Chats. Machine records are not listed. All and Other have a New message box that starts a conversation about nothing but itself.
  Surfaces are flat tones with rounded corners and no borders. These scenarios use synthetic data in an isolated browser at 375 and
  1440 pixels and never touch production.

  Scenario: All lists every conversation, newest activity first
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens the page
    Then All is selected and the conversations are in order of their last activity
    And the machine record is not listed
    And the sections are buttons with icons and there are no drop-downs

  Scenario: Each section shows only its own conversations
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor taps References, Stories, Chats and Other in turn
    Then each shows only its own conversations, with the Story's title, stage and link, and an Open chat button
    And the New message box is on All and Other only
    And an empty section says so in plain words with an icon

  Scenario: A Reference conversation leads with its messages and shows the Reference below
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor looks at a Reference conversation
    Then the messages come first and the Reference is below with its picture, headline and dek
    And the Reference has no decision controls and opens the Reference
    And only the latest messages show until the editor taps Show all with the count

  Scenario: Replying on the Messages page
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor replies to a message and then adds a message in the card
    Then the reply is nested under the message and saved in that conversation with its parent
    And a refused save takes the message back, says so in words with an icon, and keeps the typed text

  Scenario: Starting a conversation about nothing
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor writes in the New message box and taps Post
    Then a new conversation appears first, attached to nothing, and the box clears

  Scenario: Forum threads are ordinary conversations under Other
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens Other
    Then the forum thread is a card with its message count and an Open thread link to its own view

  Scenario: More conversations are read when asked for
    Given a Messages page with more conversations than fit on one page
    When the editor taps Show more conversations
    Then the next page follows in order with no conversation twice

  Scenario: The page is flat tones and rounded rectangles
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor looks at the page at 375 and 1440 pixels
    Then nothing has a border, an outline or a rule and nothing scrolls sideways

  Scenario: Conversations are merged and paged exactly
    Given the Messages page helpers
    When streams of conversations are merged and messages are trimmed
    Then newest activity comes first across streams and pages
    And only the latest messages show, with the rest counted
