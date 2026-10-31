Feature: A site settings file turns each section into a front page and the home page into a home of sections
  A Papyrus site that lists its Stories in sections can give every section a front page and make its home page out of one block per
  section, with settings only and no site code. A section front page is page 1 of the section's listing, set with
  urls.sections.<name>.index: it opens with the section tabs, the section's label and description, a lead Story, the latest entries
  and, if asked, a grid of the section's accepted References, then a link to the older pages. The home of sections is set with
  homePage.layout "sections": one block per listed section in the order of urls.sections (or of homePage.homeSections), each with
  the section's label and description, its newest perSection entries (4 unless the site says otherwise) and a "More <label>" link to
  the section front page. Both are rendered by the standard front end with its own cards, so a site gets the same cards it already
  has. They are flat tones and rounded rectangles with no borders, the current tab is told apart by weight and a mark as well as
  colour, and the "More" link carries a Lucide arrow icon.

  Nothing changes for a site that does not set these. A site that keeps the default layout, and a site such as one that uses
  homePage only for Reference grids, projects exactly the pages it projected before. A page that a site's own main() hook builds
  still wins over the generated front page. The front pages have Markdown twins and appear in llms.txt.

  Scenario: A section with an index setting gets a front page with its description, a lead Story and the latest entries, and page 2 keeps the plain listing
    The essays index asks for 3 entries, so page 1 holds the lead Story and two more, and the fourth essay is on page 2, which
    is the ordinary listing page with no tabs.
    Given the section-fronts fixture site is projected
    Then the section front page "essays/index.html" is headed "Essays" with the description "Long reads about rivers and walls."
    And the section front page "essays/index.html" has the lead Story "Fords and Crossings"
    And the section front page "essays/index.html" lists the latest entries "Hedgerows", "Stone Walls"
    And the section front page "essays/index.html" has the section tabs "Essays", "Notes", "Links" with "Essays" current
    And the section front page "essays/index.html" links to older pages at "/essays/page/2/"
    And "essays/page/2/index.html" is the plain listing of "Slow Water" with no section front page

  Scenario: A home of sections shows one block per section in configured order, each linking to the section front page
    Letters has no Stories yet, so it has no block. The blocks follow the order of urls.sections.
    Given the section-fronts fixture site is projected
    Then the home page has the section blocks "Essays", "Notes", "Links" in that order
    And the block "Essays" on the home page links to "/essays/" with the text "More Essays"
    And the block "Essays" on the home page shows the description "Long reads about rivers and walls."
    And the block "Notes" on the home page links to "/notes/" with the text "More Notes"
    And the home page does not use the generated latest listing

  Scenario: Each block shows perSection entries, which defaults to 4 and can be set
    Four is the default when the site does not set perSection. The Essays section has four Stories, so its block shows all four.
    Given the section-fronts fixture site is projected with "homePage.perSection" removed
    Then the block "Essays" on the home page lists "Fords and Crossings", "Hedgerows", "Stone Walls", "Slow Water"
    And the block "Notes" on the home page lists "Field Note Two", "Field Note One"

  Scenario: A configured perSection limits every block
    Given the section-fronts fixture site is projected with "homePage.perSection" set to 1
    Then the block "Essays" on the home page lists "Fords and Crossings"
    And the block "Notes" on the home page lists "Field Note Two"
    And the block "Links" on the home page lists "Tide Tables"

  Scenario: homeSections chooses which sections have a block and in what order
    Given the section-fronts fixture site is projected with "homePage.homeSections" set to ["links", "essays"]
    Then the home page has the section blocks "Links", "Essays" in that order

  Scenario: The first entry of each block is a lead unless homeLead is false
    Given the section-fronts fixture site is projected with "homePage.homeLead" set to false
    Then the home page has no lead entries

  Scenario: A section with no entries is skipped on the home of sections unless listEmpty
    Given the section-fronts fixture site is projected
    Then the home page has no block "Letters"
    And the standard site lacks these pages: "letters/index.html"

  Scenario: A section that is listed when empty has a block that says nothing is published yet
    Given the section-fronts fixture site is projected with "urls.sections.letters.listEmpty" set to true
    Then the block "Letters" on the home page says "Nothing is published in this section yet."
    And the block "Letters" on the home page links to "/letters/" with the text "More Letters"

  Scenario: A site that keeps homePage.layout latest renders exactly what it rendered before
    A site that does not use homePage at all projects byte for byte what it did before this feature. A site that sets
    homePage and keeps the latest layout still shows the same page inside the main element.
    Given the standard sectioned fixture site
    Then the standard page "index.html" is byte for byte the golden page of the sectioned fixture
    And the standard site lacks these pages: "css/papyrus-section-fronts.css"
    When the sectioned fixture site is projected with homePage layout "latest"
    Then the main element of "index.html" is the same as in the golden page of the sectioned fixture
    And the standard site lacks these pages: "css/papyrus-section-fronts.css"

  Scenario: Every existing standard-site fixture projects byte-identical output when the new settings are not used
    The recorded digests were taken from the code before section fronts existed.
    Then the fixtures flat, sectioned, authors, showcase and home-page project the recorded bytes

  Scenario: A section index that names a references selection shows that section's accepted References once, after the stories
    The grid asks for 2 References, takes only the ones accepted into Essays, and sits after the lead Story and the latest entries.
    Given the section-fronts fixture site is projected
    Then the section front page "essays/index.html" shows the References "Hedge ledger", "Walls atlas" once, after the stories
    And the section front page "notes/index.html" shows no References grid

  Scenario: A section index authored from a source file replaces the generated layout
    The Notes index is a Markus file, so it has none of the generated tabs or lead.
    Given the section-fronts fixture site is projected
    Then the standard page "notes/index.html" says "Notes, written by hand"
    And the standard page "notes/index.html" does not say "markus-section-index"
    And the standard page "notes/index.md" says "Notes, written by hand"

  Scenario: Publishing a story in one section rewrites that section's index and the home of sections, not another section's index
    Given the section-fronts fixture site is projected
    When the title of the standard item "item-essays-fords" is changed to "Fords Revisited" and projected
    Then the standard site wrote at least "essays/index.html, index.html, essays/index.md"
    And the section-fronts site did not write "notes/index.html"
    And the section-fronts site did not write "links/index.html"

  Scenario: Section front pages and the home of sections have Markdown twins and appear in llms.txt
    Given the section-fronts fixture site is projected
    Then the standard page "essays/index.md" says "- [Fords and Crossings]"
    And the standard page "essays/index.md" says "::include{kind="references" select="recent" count="2" section="essays"}"
    And the standard page "index.md" says "## Essays"
    And the standard page "index.md" says "[More Essays]"
    And the standard page "llms.txt" says "[Essays front page]"
    And the standard page "llms.txt" says "[Home of sections]"
    And the standard page "essays/index.html" says "papyrus-section-fronts.css"

  Scenario: A site hook main() still wins over the generated section front page and the home of sections
    Given the section-fronts fixture site is projected with a main hook
    Then the standard page "essays/index.html" says "hook front page"
    And the standard page "index.html" says "hook front page"
    And the standard page "essays/index.html" does not say "markus-section-index"

  Scenario: A homePage layout of sections on a site without sections is an error
    When the settings of a site without sections ask for homePage layout "sections"
    Then the settings are refused with "needs urls.sections"

  Scenario: A section index that asks for References on a site without homePage is an error
    When the settings of a section index ask for References on a site without homePage
    Then the settings are refused with "needs homePage"

  Scenario: Counts that are not whole numbers are errors
    When the settings ask for "homePage.perSection" of 2.5
    Then the settings are refused with "whole number"
    When the settings ask for "urls.sections.essays.index.latest" of 0
    Then the settings are refused with "whole number"
