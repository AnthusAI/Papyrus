@backend @reference-list-paging
Feature: A long Reference list loads more as the reader scrolls, and has no fixed cap
  A public site can show every Reference an editor accepted, and every one Cyclotron recommends, on one page, without the page growing with the corpus.
  Right now a page asks for "count=500", which is a cap that hides whatever comes after it. A site that opts in (homePage.references.paging in
  projection.json) and a list that opts in (paged="true" on its include) get the pattern readers know from a feed: the first cards are in the page itself,
  and more arrive as the reader scrolls. The cards past the first page are written at build time as small data files, cut by a rule that depends on the
  Reference and not on its place, so a new Reference near the top rewrites a few files and not every one. The data pages are pages too, with a link to the
  next, so a reader without a script and a crawler reach every Reference. Nothing here is private: the files hold what the public snapshot already holds,
  and a card never carries a count or a position. A site that has not opted in is unchanged. This is the public static Reference list only; the newsroom
  CMS feed is a different thing.

  Background:
    Given a public site with 130 accepted and 40 recommended References, a first page of 6 and about 12 cards to a data file

  Scenario: The first page is in the HTML and a plain link leads to the rest
    The control under the first page is an ordinary link to the next static page. A script, when there is one, turns it into a button.
    Then the "recent" list on "wire/index.html" shows 6 cards in the page itself
    And the "recent" list has a link to a next static page and a polite live region
    And following the "next" links from the first page reaches all 130 accepted References once each

  Scenario: Every Reference is reachable and the shared order holds across the pages
    The order is the one the snapshot already ranks by. The pages do not re-rank and nothing is dropped at the end.
    Then the data files of the "recent" list give the remaining 124 References in the order of the first page's list
    And the "recommended" list shows all 40 recommended References and none of the accepted ones

  Scenario: The data file is the same cards as the static page
    The script only inserts what the build drew, so there is one renderer.
    Then each data file of the "recent" list carries exactly the cards of its static page
    And no page or data file contains a build marker

  Scenario: The site's own card drawing applies to the pages loaded later
    Machines on Machines redraws the stock tile as its own card in its page_finish hook at build time. The same hook draws the data files.
    Given the site has a page_finish hook that redraws every stock tile as its own card
    Then the first page and every data file of the "recent" list show the site's own card and no stock tile

  Scenario: A site that has not opted in is unchanged
    Given a site that does not set homePage.references.paging
    Then a page with an ordinary references include is byte for byte what it was, and no list file or script is published
    And a paged include on that site stops the build and names the setting

  Scenario: Only a page with a paged list loads the script
    Given the site opted in but a page has only an ordinary references include
    Then that page loads no reference-list script and no list file exists

  Scenario: A wrong paged include is named at build time
    Then a paged include with a "more" link is refused
    And a second paged list on one page with the same name is refused

  Scenario: Nothing private reaches a data file or a page
    Then no data file, static page or Markdown twin of the paged lists holds a field the public snapshot does not publish

  Scenario: The Markdown twin is the first page and a link, and the twins chain on
    A twin that listed every Reference would grow with the corpus, and so would llms-full.txt. The twin lists the first page, then a link to the Markdown of the next
    page, which lists its References and links to the one after it.
    Then the Markdown twin of "wire/index.html" lists 6 References for each list and a "More" link
    And the Markdown of the first data page links back and on

  Scenario: A new Reference at the top rewrites only the files it affects
    Cutting the list every 48 References would move every cut after an insertion. The cut comes from the Reference itself, so the cuts find their places again within a chunk or two.
    Given a public site with 2000 accepted References in 48-card data files
    When a new Reference is accepted at the top of the order and every other Reference moves down one place
    Then the page is rewritten and at most 4 list files are written, out of about 135
    And every other list file is byte for byte what it was

  Scenario: A Reference that is removed from the middle rewrites only the files it affects
    Given a public site with 2000 accepted References in 48-card data files
    When a Reference is removed from the middle of the list
    Then at most 4 list files are written

  Scenario: A change that moves nothing a list shows rewrites no list file
    Given a public site with 300 accepted References in 12-card data files
    When only the snapshot's freshness stamp changes
    Then no list file is written

  Scenario: A data file that the cuts no longer make is found stale and removed
    Given a public site with 200 accepted References in 12-card data files
    When the snapshot loses most of its References
    Then the files of the chunks that no longer exist are the ones found stale, and no other
