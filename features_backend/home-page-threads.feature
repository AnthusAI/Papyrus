Feature: A page lists the site's public Message threads with ::include{kind="threads"}
  A Papyrus site can show part of its newsroom's conversation to visitors, read-only. The home-page snapshot task also writes
  _data/home-page/threads.json, a list of the recent public threads, and one file per thread under _data/home-page/threads/ that
  holds its Messages in sequence. An authored page places the threads with ::include{kind="threads" select="recent"}, as a list
  or as a grid, rendered at projection time so it needs no script. The Markdown twin keeps the include line as written.

  A thread is public only when it is an active conversation on a Reference that is in the home-page snapshot (accepted or
  recommended) or on a published Story. A Message is public only when it is an active comment that was never deleted: a deleted
  or moderated Message is left out entirely, because its text stays in the database after a soft delete. The author of a Message
  is shown by the public handle that the person chose in their profile settings, and otherwise as "Editor" (or "AI" when the
  Message was not written by a person). No email address, sign-in subject, profile id or other id is ever written, and the text
  of a Message is published as written except for anything shaped like an email address or a UUID and any raw HTML.

  Components on one page share a ledger with the Reference grids: the first component to place a thread keeps it, and a later
  one refills from its own ordering. Cards use flat tones and rounded rectangles, with no borders, and say what a thread is on
  in words and a Lucide icon, never by colour alone.

  Scenario: Threads on accepted References and published Stories are public; unanchored threads and threads on rejected References are not
    The fixture also holds a thread on a recommended Reference, which is public, a thread of an unpublished Story, an archived
    thread, a thread of the console conversation kind and a thread whose only Message was deleted.
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the threads in threads.json, most recently active first, are "Notes on the pending high candidate", "Is this tool worth adopting?", "Accepted seven", "Fungi follow-up"
    And a thread on a Reference is anchored by the Reference's public key and a thread on a Story by the Story's page address
    And threads.json holds none of "Chat about a rejected Reference", "Chat about an unpublished Story", "Chat with no anchor", "An archived thread", "A console conversation", "Only deleted messages"

  Scenario: A deleted Message is omitted entirely, and the thread's count excludes it
    The thread "Is this tool worth adopting?" has five Messages: a comment, a deleted one, a moderated one, a system note and a
    comment that was edited. Only the two comments are public.
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the thread "Is this tool worth adopting?" has 2 messages
    And its latest Message is marked as edited
    And no published file holds the text of a deleted, moderated or system Message

  Scenario: An author with a public handle is shown by that handle; one without is shown as Editor; no email, sub or UUID appears anywhere
    A handle that is not valid, such as one that looks like an email address, is never shown. A Message written by the assistant
    is shown as "AI". The fixture's Messages carry an email address, a UUID, a sign-in subject and an author label that is an
    email address on purpose.
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the first Message of the thread "Is this tool worth adopting?" is by the handle "ryan"
    And the latest Message of the thread "Is this tool worth adopting?" is by the label "Editor"
    And the latest Message of the thread "Accepted seven" is by the handle "ryan"
    And the latest Message of the thread "Fungi follow-up" is by the label "Editor"
    And the latest Message of the thread "Notes on the pending high candidate" is by the label "AI"
    And every public Message has exactly the public fields and no field that names a person or a record
    And the identity scanner finds nothing in any published file

  Scenario: With authors none, every author is shown by the anonymous label
    Given the home-page threads fixture site is projected with authors "none" and the anonymous label "Staff"
    When the home-page-snapshot task runs against the threads fixture
    Then every Message in every thread is by the label "Staff" or "AI"
    And the profile of no author was read

  Scenario: A page lists the most recently active threads as a list
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the threads list on "threads-list/index.html" lists "Notes on the pending high candidate", "Is this tool worth adopting?", "Accepted seven"
    And the threads list on "threads-list/index.html" is drawn as a "list"
    And "threads-list/index.html" shows the text "Recent conversations"

  Scenario: A page lists the most recently active threads as a grid
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the threads list on "threads-grid/index.html" lists "Notes on the pending high candidate", "Is this tool worth adopting?", "Accepted seven", "Fungi follow-up"
    And the threads list on "threads-grid/index.html" is drawn as a "grid"

  Scenario: A card says what the thread is on, how many Messages it has, when it last moved, the latest Message and who wrote it
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the card for "Is this tool worth adopting?" says "Reference: Accepted eight" next to a "link" icon
    And the card for "Fungi follow-up" says "Story: Fungi Underground" next to a "file-text" icon
    And the card for "Is this tool worth adopting?" says "2 messages" next to a "message-square" icon
    And the card for "Accepted seven" says "1 message" next to a "message-square" icon
    And the card for "Is this tool worth adopting?" shows the date "29 Oct 2026"
    And the card for "Is this tool worth adopting?" quotes "Agreed, a useful tool for the team." and says it is "by Editor"
    And the card for "Accepted seven" says it is "by ryan"
    And the card for "Fungi follow-up" links its anchor to the Story's page
    And the stylesheet and cards draw no borders and show every state in words and an icon

  Scenario: The latest Message is clipped at a sentence boundary and shown as plain text
    The Message of "Notes on the pending high candidate" is longer than the summary length. The card cuts it after a full
    sentence, and the Markdown marks and the address scrubbing leave no raw Markdown or HTML in the card.
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the card for "Notes on the pending high candidate" quotes at most 240 characters ending in a full stop
    And the card for "Accepted seven" shows the quote "Worth a look; write to about it. is not an id. Second sentence here."

  Scenario: A threads include never repeats a thread already placed on the page
    The page places two Reference cards, then a grid of two threads, then a list of three. The list skips the two threads the
    grid already placed and shows the two that are left; the Reference ledger and the thread ledger do not interfere.
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the threads grid on "threads-mixed/index.html" lists "Notes on the pending high candidate", "Is this tool worth adopting?"
    And the threads in the list on "threads-mixed/index.html" lists "Accepted seven", "Fungi follow-up"
    And no thread title appears twice on "threads-mixed/index.html"
    And the "recent" grid on "threads-mixed/index.html" has 2 cards

  Scenario: A thread that stops being public has its per-thread file deleted
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    And the thread "Is this tool worth adopting?" is archived and the home-page-snapshot task runs again
    Then the per-thread file of "Is this tool worth adopting?" is deleted
    And the per-thread files of "Notes on the pending high candidate", "Accepted seven", "Fungi follow-up" remain
    And the threads in threads.json, most recently active first, are "Notes on the pending high candidate", "Accepted seven", "Fungi follow-up"
    And the page "threads-list/index.html" was re-rendered by the second run
    And "threads-list/index.html" no longer lists "Is this tool worth adopting?"

  Scenario: A run that finds the same threads writes nothing
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    And the home-page-snapshot task runs again against the threads fixture
    Then the second run wrote and deleted nothing

  Scenario: A site with threads switched off writes no thread file and deletes none
    Given the home-page threads fixture site is projected with threads switched off
    When the home-page-snapshot task runs against the threads fixture
    Then the store holds no thread file

  Scenario: Each thread has a file of its Messages in sequence for the later forum pages
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then the file of the thread "Is this tool worth adopting?" holds its title, its anchor and 2 Messages in sequence
    And no page reads the per-thread files

  Scenario: Before the first snapshot a page shows its empty text
    Given the home-page threads fixture site is projected
    Then "threads-empty/index.html" shows the text "No conversations yet."
    And "threads-list/index.html" shows the text "No conversations yet."

  Scenario: A site whose conversations are all private shows the empty text and writes an empty list
    Given the home-page threads fixture site is projected with only private conversations
    When the home-page-snapshot task runs against the threads fixture
    Then threads.json lists no thread
    And "threads-empty/index.html" shows the text "No conversations yet."

  Scenario: The Markdown twin keeps the threads include line as written
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then "threads-list/index.md" contains the line '::include{kind="threads" select="recent" count="3" layout="list" heading="Recent conversations" empty="No conversations yet."}'
    And "threads-list/index.md" does not contain "home-page-thread"

  Scenario: A threads include on a site without homePage configured fails the build naming the file
    Given the home-page threads fixture site is projected without a homePage setting
    Then the threads build failed saying "pages/threads-list.md" and "homePage is not configured in projection.json"

  Scenario Outline: A threads include with an attribute it does not know fails the build naming the file
    Given the home-page threads fixture site is projected with the include attribute <attribute>
    Then the threads build failed saying "pages/threads-list.md" and "<message>"

    Examples:
      | attribute            | message                      |
      | select="busiest"     | select to be one of recent   |
      | layout="carousel"    | layout must be one of        |
      | count="many"         | count must be a whole number |
      | order="oldest"       | unknown attributes: order    |
