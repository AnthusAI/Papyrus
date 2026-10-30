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

  Scenario: Inside the newsroom the open thread wears only its ring
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens a thread in the grid and in the list inside the newsroom's own stylesheet at 1024 and 1440 pixels
    Then neither the open card nor its title has a bar along its edge, the card keeps its tone, and the ring is its only mark

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
    Then each shows only its own threads and the New thread button is on All and Other only
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

  Scenario: The author's name comes from their profile
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor opens a conversation whose authors have profiles
    Then each message shows its author's profile name, or the saved label's first part when the profile cannot be read
    And the profiles were asked for in one request for the whole conversation

  Scenario: Other people's messages cannot be edited or deleted
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When another editor opens a conversation written by someone else
    Then no message shows Edit or Delete, every message still shows Reply, and the title has no Rename
    And the author sees Edit and Delete, each with an icon and a word, on their own messages only

  Scenario: An author edits their own message
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the author taps Edit on their message, changes the text and taps Save
    Then the message shows the new text and says when it was edited, and Cancel leaves it as it was

  Scenario: An author deletes their own message and its replies stay
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the author taps Delete on a message that has a reply and confirms
    Then Delete this message? is asked inline with Delete and Keep, and Keep changes nothing
    And the message reads Message deleted with a ban icon and offers no Reply, Edit or Delete, its reply stays, and the thread's count does not drop

  Scenario: An admin can delete anyone's message but not edit it
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When an admin opens a conversation written by others
    Then every message shows Delete and none shows Edit, and the admin can rename any thread

  Scenario: A refused edit or delete says why and keeps the text
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the backend refuses an edit and a delete
    Then each says why in words with an icon, the edit box keeps the typed text, and the message is unchanged

  Scenario: Starting a conversation takes a title
    Given a Messages page with Reference, Story, unattached, forum and chat conversations and a machine record
    When the editor taps New thread, writes a message in the form in the detail view and then gives it a title and taps Post
    Then Post waits for the title and says so in words, and the new thread appears first with that title, attached to nothing, and opens in the detail view

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
