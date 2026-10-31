Feature: Public thread pages
  A site that opts in with homePage.forum gives every public Message thread its own static, read-only page at
  <threadBase>/<key>/, where threadBase defaults to "conversations". The page is drawn from the per-thread file that the home-page
  snapshot already writes under _data/home-page/threads/, so it shows exactly what that file holds and nothing else: a header with
  the thread's title and the thing it is about (a Reference's card, or a line that links to the Story), then one flat block per
  Message in sequence. A Message says who wrote it by a public handle with a Lucide "user" icon, or by a role label such as
  "Editor" with a "badge-check" icon, shows when it was written in a time element, and says "edited" in words beside a "pencil"
  icon when it was edited. The page has no borders, never uses colour alone, and works without a script.

  Every thread page has a Markdown twin and an entry in llms.txt. The "threads" include on any page links each thread to its page
  once the site has a forum. A thread that stops being public loses its page and its twin on the next snapshot, and a page is
  rewritten only when its own thread file changed. threadBase cannot be a path that the platform serves itself. No email
  address, sign-in subject or id appears on a thread page.

  Scenario: A public thread renders as a page with its Messages in sequence
    The thread "Is this tool worth adopting?" is on a Reference and has two public Messages: the first by the handle "ryan", the
    second by the role label "Editor", edited after it was written.
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    Then the thread page of "Is this tool worth adopting?" is written under "conversations/"
    And the thread page of "Is this tool worth adopting?" shows its Messages by "ryan", "Editor" in sequence
    And the thread page of "Is this tool worth adopting?" is about the Reference "Accepted eight"
    And the thread page of "Is this tool worth adopting?" draws the "user" icon, the "badge-check" icon and the "pencil" icon
    And the thread page of "Is this tool worth adopting?" says "edited" once and gives every Message a time element
    And the thread page of "Fungi follow-up" is about the Story "Fungi Underground" with a link to "/fungi.html"
    And the home-page stylesheet draws no borders or lines

  Scenario: The page has a Markdown twin and an llms.txt entry
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    Then the thread page of "Is this tool worth adopting?" has a Markdown twin that starts with its title and holds its Messages in sequence
    And llms.txt lists the thread page of "Is this tool worth adopting?"
    And the sitemap lists the thread page of "Is this tool worth adopting?"

  Scenario: The threads include links each thread to its page
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    Then every thread on "threads-list/index.html" links to its thread page

  Scenario: A thread that is no longer public loses its page on the next snapshot
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    And the thread "Is this tool worth adopting?" is archived and the home-page-snapshot task runs again
    Then the page and the Markdown twin of the archived thread are deleted
    And the thread pages of "Notes on the pending high candidate", "Accepted seven", "Fungi follow-up" remain

  Scenario: A page is rewritten only when its own thread changed
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    And the home-page-snapshot task runs again against the threads fixture
    Then the second run wrote and deleted nothing

  Scenario: A site without homePage.forum renders no thread pages and the threads include links nowhere
    Given the home-page threads fixture site is projected
    When the home-page-snapshot task runs against the threads fixture
    Then no thread page is written
    And no thread on "threads-list/index.html" is a link

  Scenario Outline: threadBase may not be a reserved prefix
    Given a projection.json that sets homePage.forum.threadBase to "<segment>"
    When the standard settings are read
    Then reading fails saying "homePage.forum.threadBase" and "is reserved" and "newsroom"

    Examples:
      | segment  |
      | api      |
      | _data    |
      | _papyrus |

  Scenario: An unknown forum setting is a build error naming the key
    Given the home-page threads fixture site is projected with the forum setting "pageLimit"
    Then the threads build failed saying "homePage.forum" and "pageLimit"

  Scenario: No email, sub or UUID appears on a thread page (reader-privacy scan)
    The fixture's Messages carry an email address, a UUID, a sign-in subject and an author label that is an email address on
    purpose.
    Given the home-page threads fixture site is projected with a forum
    When the home-page-snapshot task runs against the threads fixture
    Then the identity scanner finds nothing in any thread page
