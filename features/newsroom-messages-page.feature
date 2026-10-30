@brand-agnostic @conversation-fixtures
Feature: The Messages page is a forum
  The Messages page lists every conversation, newest activity first, like a web forum. Each thread is one card in a grid (the
  default) or one line in a list, chosen with two buttons, Grid and List, that remember the choice for the viewer. A thread shows
  its own title, which can differ from the headline of the Reference or Story it is about; that attachment is a small line under the
  title (the site and the Reference's headline, or the Story's title and its stage as text), and an unattached thread has none. A card
  also shows the message count with a message icon, who spoke last and how long ago, and the first line of the latest message. A
  card holds no conversation and costs no message reads. Selecting a thread opens its whole conversation, replies nested under their
  messages, with a Reply button and an "Add a message…" box. From 1024 pixels the conversation is a pane to the right of the list; below
  that it replaces the list at the full width with a Back button. The address holds the selection, so it can be linked and reopened.
  The conversation's title can be renamed in place. The sections are buttons: All, References, Stories, Chats and Other. Forum threads
  and chats are cards too and open their own views. The New message box asks for a title and the first message. Surfaces are flat
  tones with rounded corners and no borders. These scenarios use synthetic data in an isolated browser at 375, 768, 834, 1024 and 1440
  pixels and never touch production.

  Scenario: All lists every thread as a card, newest activity first
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens the page
    Then All is selected, the threads are in order of their last activity, and the machine record is not listed
    And the sections are buttons with icons and there are no drop-downs
    And each card shows its own title, what it is attached to, its message count, who spoke last and the latest message's first line
    And a card holds no conversation and no messages were read for the page

  Scenario: The editor switches between grid and list and the page remembers
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor taps List and reloads the page
    Then every thread is one line, the List button is pressed, and the page opens in list again
    And the page still works when the browser refuses to store the choice

  Scenario: A thread shows its own title, not its Reference's or Story's
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor looks at the Reference and Story threads
    Then each shows the thread's title, with the Reference's headline or the Story's title and stage as a small line below it

  Scenario: Each section shows only its own conversations
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor taps References, Stories, Chats and Other in turn
    Then each shows only its own threads and the New message box is on All and Other only
    And an empty section says so in plain words with an icon

  Scenario: Selecting a thread opens its conversation beside the list or in its place
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor selects a Reference thread at 375, 768, 834, 1024 and 1440 pixels
    Then the address holds the thread and the whole conversation shows with the Reference's header and no decision controls
    And at 1024 and 1440 pixels the list stays on the left with the conversation in a pane on the right
    And at 375, 768 and 834 pixels the conversation replaces the list at the full width and Back returns to the list and clears the address
    And only the open thread's messages were read

  Scenario: A linked address opens its thread
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens an address that names a thread, even one on a later page, or one that does not exist
    Then the thread opens, or the page says in words that it could not be found

  Scenario: Renaming a thread
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor taps Rename, changes the title and taps Save
    Then the new title shows in the conversation and in the list
    And a refused save says why in words with an icon and keeps the typed text

  Scenario: Replying in the conversation
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor replies to a message and then adds a message in the open conversation
    Then the reply is nested under the message and saved in that conversation with its parent
    And the thread's card counts the new messages and moves to the top
    And a refused save takes the message back, says so in words with an icon, and keeps the typed text

  Scenario: Starting a conversation takes a title
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor writes a message in the New message box and then gives it a title and taps Post
    Then Post waits for the title and says so in words, and the new thread appears first with that title and attached to nothing

  Scenario: Forum threads and chats are cards that open their own views
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens Other and Chats
    Then the forum thread links to its own view, the chat opens in the console, and neither opens a pane here

  Scenario: More conversations are read when asked for
    Given a Messages page with more conversations than fit on one page
    When the editor taps Show more conversations
    Then the next page follows in order with no conversation twice

  Scenario: The page is flat tones and rounded rectangles
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor looks at the grid, the list and an open conversation at 375, 1024 and 1440 pixels
    Then nothing has a border, an outline or a rule, nothing scrolls sideways, and lines stay one line beside the pane

  Scenario: Conversations are merged and paged exactly
    Given the Messages page helpers
    When streams of conversations are merged and messages are trimmed
    Then newest activity comes first across streams and pages
    And only the latest messages show, with the rest counted
