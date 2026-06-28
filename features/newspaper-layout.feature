Feature: Newspaper layout scenarios
  Layout scenarios are durable examples of newspaper behavior.
  They verify both the solver's decisions and the rendered page geometry.

  Scenario: Current edition renders from the composable layout engine
    Given I open the "current-edition" layout scenario at 1280 by 900
    Then the active content scenario should be "current-edition"
    And the active content source should be "scenario"
    And the active edition should expose a composable layout plan
    And the solved layout should use 6 columns
    And the front page should label article "agent-procedure-patterns" as continued on page 2
    And the front page should label article "schools-reading-lab" as continued on page 3
    And the front page should label article "market-hall" as continued on page 3
    When I scroll to page 3
    Then the active page should be a "regionStack" page
    And no measured line should be cropped
    And no solved furniture should overlap within a section
    And no measured line should overlap solved furniture
    And no continuation column should be dead
    And the "schools-reading-lab" section should show a responsive image inset
    And the "schools-reading-lab" section image should span 2 columns
    And the "schools-reading-lab" section image should be right aligned at the top
    And the "schools-reading-lab" section image should leave one rhythm row before copy
    And the "schools-reading-lab" section adjacent copy should flow beside the image
    And no browser console errors should occur

  Scenario Outline: Responsive pages preserve a shared vertical rhythm
    Given I open the "current-edition" layout scenario at <width> by <height>
    Then the active page should follow the vertical rhythm
    When I scroll to page 3
    Then the active page should follow the vertical rhythm
    And no measured line should be cropped
    And no browser console errors should occur

    Examples:
      | width | height |
      | 1280  | 900    |
      | 1280  | 1600   |
      | 640   | 1200   |
      | 390   | 900    |

  Scenario Outline: Masthead nameplates step down on column breakpoints
    Given I open the "current-edition" layout scenario at <width> by <height>
    Then the masthead should use <mastheadRows> rhythm rows with <titleRows> title rows and fit the page width
    Given I open the newsroom at <width> by <height>
    Then the masthead should use <mastheadRows> rhythm rows with <titleRows> title rows and fit the page width
    And no browser console errors should occur

    Examples:
      | width | height | mastheadRows | titleRows |
      | 1280  | 900    | 6            | 4         |
      | 640   | 1200   | 5            | 3         |
      | 390   | 900    | 4            | 2         |

  Scenario: Newsroom top shell responds to constrained container width
    Given I open the newsroom at 1280 by 900
    And I constrain the newsroom shell width to 760 pixels
    Then the newsroom masthead should fit width and align to rhythm rows
    And the newsroom tabs should use 3 columns
    And no browser console errors should occur

  Scenario: Front page masthead uses the edition title
    Given I open the "current-edition" layout scenario at 1280 by 900
    Then the front page masthead edition label should say "Current Edition"
    And no browser console errors should occur

  Scenario: Front page masthead falls back when the edition title is blank
    Given I open the "blank-edition-title" layout scenario at 1280 by 900
    Then the front page masthead edition label should say "WEEKLY EDITION"
    And no browser console errors should occur

  Scenario Outline: Shared continuations repair blank-column pressure
    Given I open the "shared-blank-column-pressure" layout scenario at <width> by <height>
    Then the solved layout should use <columns> columns
    When I scroll to page 3
    Then the active page should be a "regionStack" page
    And no measured line should be cropped
    And no solved furniture should overlap within a section
    And no measured line should overlap solved furniture
    And no continuation column should be dead
    And no browser console errors should occur

    Examples:
      | width | height | columns |
      | 1280  | 900    | 6       |
      | 640   | 1200   | 3       |
      | 390   | 900    | 1       |

  Scenario: Front page uses GraphQL content by default
    Given I open the front page at 1280 by 900
    Then the active content source should be "graphql"
    And the active edition should expose a composable layout plan
    And the solved layout should use 6 columns
    And the active edition should include article "schools-reading-lab"
    And edition pages should sit on a neutral gray substrate with one rhythm row between pages
    When I scroll to page 2
    Then the active page should be a "articlePage" page
    And the inside page header should center labels on the rhythm row
    And the "agent-procedure-patterns" continuation should not repeat front-page images
    And continuation title chrome should be compact
    And the active page should follow the vertical rhythm
    And no measured line should be cropped
    And no browser console errors should occur

  Scenario: Front feature slots control headline, copy, and right-side image
    Given I open the "current-edition" layout scenario at 1280 by 900
    Then the front article "agent-procedure-patterns" should use the requested slot composition
    And the first three front stories should not reserve top rules
    And front jump labels should use upper-row rhythm without h-rules
    And the front article "agent-procedure-patterns" should share one copy band below lead furniture
    And the front page should resolve editorial priority "primary" for article "agent-procedure-patterns"
    And the front page should resolve headline scale "rail" for article "schools-reading-lab"
    And the front page should resolve headline scale "feature" for article "agent-procedure-patterns"
    And the front page should resolve headline scale "rail" for article "market-hall"
    And the front headline for article "agent-procedure-patterns" should be larger than articles "schools-reading-lab" and "market-hall"
    And no article chrome should overlap
    And no measured line should be cropped
    And no measured line should overlap solved furniture
    And no browser console errors should occur

  Scenario: Front teaser body-depth rows keep the lead trio aligned
    Given I open the "front-body-depth-rows" layout scenario at 1280 by 900
    Then the front lead trio should share one equal-height row
    And no measured line should be cropped
    And no browser console errors should occur

  Scenario: Primary front story leads the mobile sequence
    Given I open the "current-edition" layout scenario at 390 by 900
    Then the solved layout should use 1 columns
    And the first front story should be article "agent-procedure-patterns"
    And the front page should resolve editorial priority "primary" for article "agent-procedure-patterns"
    And the front article "agent-procedure-patterns" should stack its image below title chrome
    And no article chrome should overlap
    And no measured line should overlap solved furniture
    And no measured line should be cropped
    And no browser console errors should occur

  Scenario: Four-column front page uses a responsive feature-top recipe
    Given I open the "current-edition" layout scenario at 900 by 1200
    Then the solved layout should use 4 columns
    And the first front story should be article "agent-procedure-patterns"
    And front article "agent-procedure-patterns" should occupy row 1 columns 1 through 4
    And front article "schools-reading-lab" should occupy row 2 columns 1 through 2
    And front article "market-hall" should occupy row 2 columns 3 through 4
    And the front article "agent-procedure-patterns" should inset its image in the top right half
    And the front article "agent-procedure-patterns" should flow copy around the inset image
    And the front page should render article "market-hall"
    And no measured line should be cropped
    And no browser console errors should occur

  Scenario: Three-column front feature keeps media inset out of article chrome
    Given I open the "current-edition" layout scenario at 780 by 1200
    Then the solved layout should use 3 columns
    And the first front story should be article "agent-procedure-patterns"
    And front article "agent-procedure-patterns" should occupy row 1 columns 1 through 3
    And the front article "agent-procedure-patterns" should stack its headline above the three-column media inset
    And the front article "agent-procedure-patterns" should flow copy around the inset image
    And no article chrome should overlap
    And no measured line should be cropped
    And no browser console errors should occur

  Scenario: Front page renders a newspaper footer
    Given I open the "current-edition" layout scenario at 1280 by 900
    Then the front page should render a newspaper footer
    And the front page footer should list edition sections
    And the front page solved height should include footer rhythm space
    And the front page footer should stack utility links in the right column
    When I scroll to page 2
    Then the active page should not render a front page footer
    And no browser console errors should occur

  Scenario Outline: Front page footer remains visible at responsive widths
    Given I open the front page at <width> by <height>
    Then the front page should render a newspaper footer
    And the front page footer should fit within the solved page
    And no browser console errors should occur

    Examples:
      | width | height |
      | 1280  | 900    |
      | 900   | 1200   |
      | 780   | 1200   |
      | 390   | 900    |

  Scenario: Newsroom opens knowledge overview
    Given I open the newsroom at 1280 by 900
    Then the newsroom should render
    And the newsroom should show the knowledge overview

  Scenario: Newsroom renders the body while the summary is still loading
    Given I am a test editor reader
    And the newsroom summary is delayed by 5000 milliseconds
    And I open the edition path "/newsroom" at 1280 by 900
    Then the newsroom should show the knowledge overview
    And the newsroom should not show an editor access gate
    And the newsroom aggregate counts should remain blank while the summary is loading
    And no browser console errors should occur

  Scenario: Newsroom degrades a missing summary to question marks
    Given I am a test editor reader
    And the newsroom summary is unavailable
    And I open the edition path "/newsroom" at 1280 by 900
    Then the newsroom should show the knowledge overview
    And the newsroom should not show an editor access gate
    And the newsroom aggregate counts should show question marks
    And the newsroom should not show a summary error banner
    And no browser console errors should occur

  Scenario Outline: Newsroom overview newspaper sections stay readable
    Given I open the newsroom at <width> by <height>
    Then the newsroom overview should show newspaper sections
    And newsroom overview section cards should not overlap or clip
    And no browser console errors should occur

    Examples:
      | width | height |
      | 1280  | 900    |
      | 390   | 900    |

  Scenario: Newsroom overview headers follow the vertical rhythm at three columns
    Given I am a test editor reader
    And the newsroom summary is unavailable
    And I open the edition path "/newsroom" at 780 by 1200
    Then the newsroom should show the knowledge overview
    And newsroom overview section headers should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Newsroom overview shows configured section rail
    Given I open the newsroom at 1280 by 900
    Then the newsroom section rail should show canonical sections in rank order
    And the newsroom section rail should keep canonical sections after 2500 milliseconds
    And the newsroom rotating expander should be collapsed by default
    When I open the newsroom rotating expander
    Then the newsroom rotating expander should be expanded
    And the newsroom section rail should show rotating section choices
    And the newsroom section rail should occupy one wide column
    Given I open the edition path "/newsroom/messages?demo=1" at 1280 by 900
    Then the newsroom section rail should not render

  Scenario: Deep newsroom section pages omit operational tabs
    Given I open the edition path "/newsroom/sections/news?demo=1" at 1280 by 900
    Then the deep newsroom section page should show "News"
    And the deep newsroom section page should still show "News" after 2500 milliseconds
    And the deep newsroom section page should omit operational tabs
    And no browser console errors should occur

  Scenario: Demo newsroom navigation keeps the desk visible
    Given I open the newsroom at 1280 by 900
    When I follow the newsroom overview link for "References"
    Then the active newsroom section should be "references"
    And the newsroom should not show an editor access gate
    When I follow the newsroom tab for "Concepts"
    Then the active newsroom section should be "concepts"
    And the newsroom should not show an editor access gate
    When I follow the newsroom tab for "Assignments"
    Then the active newsroom section should be "assignments"
    And the newsroom should not show an editor access gate
    When I follow the newsroom tab for "Administration"
    Then the active newsroom section should be "administration"
    And the newsroom should not show an editor access gate
    And no browser console errors should occur

  Scenario: Newsroom renders category steering proposals and category edits
    Given I open the topics newsroom at 1280 by 900
    Then the topics desk should render
    And the newsroom should show category proposal queue rows
    And the newsroom should show accepted subcategories under canonical categories
    And the newsroom should show proposed subcategories under canonical categories
    And the newsroom should offer accept reject defer and edit actions
    And no browser console errors should occur

  Scenario: Newsroom browses references and semantic concepts
    Given I open the references newsroom at 1280 by 900
    Then the references desk should show reference metadata and semantic neighbors
    Given I open the concepts newsroom at 1280 by 900
    Then the concepts desk should show semantic nodes and linked objects
    And no browser console errors should occur

  Scenario: Newsroom reference detail renders the header curation cluster
    Given I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    Then the selected reference deep link URL should be "reference-knowledge-corpus-demo-source-history-001"
    Then the reference detail should render the curation cluster
    And the reference detail curation controls should share one height
    And the reference detail curation cluster should align with the top toolbar
    And the reference detail should not show the lower curation selector
    And the reference detail toolbar should show previous and next actions
    And the reference detail toolbar previous action should be disabled
    And the reference detail toolbar next action should be enabled
    When I open the next reference from the detail toolbar
    Then the selected reference detail should change
    And the current URL should match the selected reference detail
    And the reference detail toolbar previous action should be enabled
    When I open the previous reference from the detail toolbar
    Then the selected reference detail should return to the original selection
    And the selected reference deep link URL should be "reference-knowledge-corpus-demo-source-history-001"
    When I open the reference detail curation actions
    Then the reference detail actions menu should offer "Research" and "Archive"
    And the reference detail actions menu should not offer "Reopen"
    And the reference detail actions menu should show an icon for "Research"
    And semantic reference links should use canonical path URLs
    When I set the selected reference quality to 1 stars
    Then the reference detail curation status should be "rejected"
    And the reference detail should show 0 filled quality stars
    When I set the selected reference quality to 4 stars
    Then the reference detail should immediately show 4 filled quality stars
    And the reference detail curation status should be "accepted"
    And the reference detail should show 4 filled quality stars
    And the reference detail should render topic workflow and corpus selector
    When I open the reference detail insight composer
    Then the reference detail insight composer should be visible
    And no browser console errors should occur

  Scenario: Newsroom reference quality failure restores the confirmed header state
    Given the reference quality mutation fails
    And I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    And I set the selected reference quality to 4 stars
    Then the reference detail should immediately show 4 filled quality stars
    And the reference detail quality save state should become "error"
    And the reference detail curation status should be "accepted"
    And the reference detail should show 0 filled quality stars
    And the reference detail quality message should mention "not saved"
    And no browser console errors should occur

  Scenario: Newsroom reference detail removes duplicated source URI from summary body
    Given I am a test editor reader
    And the newsroom uses mocked reference summaries with leading source URI
    And I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    Then the reference detail source URI should be clickable
    And the reference detail should use link-standard value typography for source URI and attachments
    And the reference detail should not show source URI above the summary
    And the reference detail summary should not start with source URI
    And the reference detail summary should be "Trimmed summary body for mock reference one."
    When I open reference "reference-knowledge-corpus-demo-source-history-002"
    Then the reference detail source URI should be clickable
    And the reference detail should not show source URI above the summary
    And the reference detail summary should be "Unchanged summary for mock reference two."
    And no browser console errors should occur

  Scenario: Newsroom reference detail renders extracted text
    Given I am a test editor reader
    And the newsroom uses mocked extracted text payload for reference detail
    And I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-001"
    Then the reference detail should place extracted text below metadata
    And the reference detail should render extracted text tabs
    And the reference detail extracted text active tab should be "filtered"
    And the reference detail extracted text should include "History 001 filtered text line one."
    When I switch the reference detail extracted text tab to "original"
    Then the reference detail extracted text should include "History 001 extracted text line one."
    And no browser console errors should occur

  Scenario: Newsroom reference detail hides missing extracted text tabs
    Given I am a test editor reader
    And the newsroom uses mocked filtered extracted text payload for reference detail
    And I open the references newsroom at 1280 by 900
    When I open reference "reference-knowledge-corpus-demo-source-history-002"
    Then the reference detail extracted text tab "filtered" should be visible
    And the reference detail extracted text tab "original" should be hidden
    And the reference detail extracted text active tab should be "filtered"
    And the reference detail extracted text should include "History 002 filtered text line one."
    And no browser console errors should occur

  Scenario: Newsroom reference detail shows missing extracted text state
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    Then the reference detail should show extracted text empty state when both tabs are missing
    And no browser console errors should occur

  Scenario: Newsroom reference detail loads from canonical deep links
    Given I open the newsroom path "/newsroom/references/reference-knowledge-corpus-demo-source-history-002?demo=1" at 1280 by 900
    Then the selected reference detail should be "reference-knowledge-corpus-demo-source-history-002"
    And the selected reference deep link URL should be "reference-knowledge-corpus-demo-source-history-002"
    And no browser console errors should occur

  Scenario Outline: Newsroom operational desks use newspaper card grids
    Given I open the "<section>" newsroom section at <width> by <height>
    Then the newsroom card grid should render for "<section>"
    And newsroom cards should not overlap or clip
    When I open the first newsroom card detail
    Then the initial newsroom detail open should not animate card resizing
    Then the newsroom card grid should scale to the split width
    And the newsroom left pane should be scrollable in split view
    When I scroll the newsroom left pane down
    Then the newsroom section lede should move up within the left pane
    When I select a different newsroom card
    Then the selected newsroom card should anchor to the top of the list view
    Then newsroom card selection should keep grid geometry stable
    And newsroom card selection should not animate card resizing
    And no browser console errors should occur

    Examples:
      | section     | width | height |
      | topics      | 1280  | 900    |
      | concepts    | 1280  | 900    |
      | messages    | 1280  | 900    |
      | references  | 1280  | 900    |
      | assignments | 1280  | 900    |

  Scenario: Newsroom reference-curation message detail uses the linked reference headline and subheading
    Given I am a test editor reader
    And the newsroom uses mocked reference-curation message detail data
    And I open the edition path "/newsroom/messages/message-mock-reference-curation-001" at 1280 by 900
    Then the message detail headline should be "Red-Teaming for Generative AI"
    And the message detail subheading should be "Silver Bullet or Security Theater?"
    And the message detail summary should be "An examination of whether red-teaming materially improves generative AI security outcomes."
    And the message detail headline should not be "https://example.com/papers/mock-reference.pdf: accepted"
    And no browser console errors should occur

  Scenario: Newsroom assignment filters animate non-selection reflow
    Given I open the "assignments" newsroom section at 1280 by 900
    Then the newsroom card grid should render for "assignments"
    When I change the newsroom metric filter to "Claimed"
    Then the newsroom card grid should animate and settle after non-selection reflow
    And newsroom cards should not overlap or clip
    And no browser console errors should occur

  Scenario Outline: Newsroom card grids stay readable on compact screens
    Given I open the "<section>" newsroom section at 390 by 900
    Then the newsroom card grid should render for "<section>"
    And newsroom cards should not overlap or clip
    And no browser console errors should occur

    Examples:
      | section     |
      | topics      |
      | concepts    |
      | messages    |
      | references  |
      | assignments |

  Scenario: Newsroom merges duplicate user identities
    Given I open the administration newsroom at 1280 by 900
    Then the users desk should show merge controls
    And the administration policies panel should render doctrine controls
    And the administration sections panel should render section controls
    When I update newsroom section "news" title to "Daily News" and save
    Then newsroom section "news" should have title "Daily News"
    When I move newsroom section "news" down one slot
    Then newsroom section "news" should appear after "business"
    When I merge newsroom user "Demo Reader" into "Demo Editor"
    Then newsroom user "Demo Editor" should include identity "reader@example.com"
    And newsroom user "Demo Reader" should not be listed
    And no browser console errors should occur

  Scenario: Newsroom claims and completes reference curation assignments
    Given I open the assignments newsroom at 1280 by 900
    Then the assignments desk should render
    When I claim assignment "assignment-demo-reference-intake-history-001" with note "Taking this one"
    Then assignment "assignment-demo-reference-intake-history-001" should be claimed
    When I complete assignment "assignment-demo-reference-intake-history-001" with note "Reviewed"
    Then assignment "assignment-demo-reference-intake-history-001" should be completed
    And no browser console errors should occur

  Scenario: Newsroom shows reporting context packets without publishing candidate Items
    Given I open the assignments newsroom at 1280 by 900
    Then the assignments desk should render
    When I open assignment "assignment-demo-reporting-news-001"
    Then assignment "assignment-demo-reporting-news-001" should show a private reporting packet
    And assignment "assignment-demo-reporting-news-001" should not appear as an edition item
    And no browser console errors should occur

  Scenario: Newsroom reviews reporting packets without publishing placement
    Given I am a test editor reader
    And I open the assignments newsroom at 1280 by 900
    Then the assignments desk should render
    When I open assignment "assignment-demo-reporting-news-001"
    And I review reporting packet for assignment "assignment-demo-reporting-news-001" as "hold" with note "Needs one more source"
    Then assignment "assignment-demo-reporting-news-001" should show reporting decision "hold"
    And assignment "assignment-demo-reporting-news-001" should not appear as an edition item
    When I review reporting packet for assignment "assignment-demo-reporting-news-001" as "select" with note "Move to copywriting"
    Then assignment "assignment-demo-reporting-news-001" should show reporting decision "select"
    And assignment "assignment-demo-reporting-news-001" should show a copywriting assignment without edition placement
    And no browser console errors should occur

  Scenario: Newsroom story budget groups reporting packets by section
    Given I am a test editor reader
    And I open the assignments newsroom at 1280 by 900
    When I switch assignments to Story Budget view
    Then the reporting story budget should show section "news" with 1 slot and 1 candidate
    And the reporting story budget should map candidate "assignment-demo-reporting-news-001" to slot rank 1
    And the reporting story budget should show section "news" with 0 filled slot and 1 unresolved slot
    And story budget candidate "assignment-demo-reporting-news-001" should show packet recommendation "hold"
    And story budget candidate "assignment-demo-reporting-news-001" should show risk and gap context
    When I open story budget candidate "assignment-demo-reporting-news-001"
    Then assignment "assignment-demo-reporting-news-001" should show a private reporting packet
    When I review story budget candidate "assignment-demo-reporting-news-001" as "hold"
    Then story budget candidate "assignment-demo-reporting-news-001" should show reporting decision "hold"
    And assignment "assignment-demo-reporting-news-001" should not appear as an edition item
    When I review story budget candidate "assignment-demo-reporting-news-001" as "select"
    Then story budget candidate "assignment-demo-reporting-news-001" should show reporting decision "select"
    And the reporting story budget should show section "news" with 1 filled slot and 0 unresolved slot
    And story budget candidate "assignment-demo-reporting-news-001" should show a copywriting assignment
    And no browser console errors should occur

  Scenario: Production newsroom requires editor access
    Given I open the edition path "/newsroom" at 1280 by 900
    Then the newsroom should show an editor access gate
    And no browser console errors should occur

  Scenario: Administration sections panel route variants resolve
    Given I open the edition path "/newsroom/administration/sections?demo=1" at 1280 by 900
    Then the administration sections panel should render section controls
    Given I open the edition path "/newsroom/administration?demo=1&panel=sections" at 1280 by 900
    Then the administration sections panel should render section controls
    And no browser console errors should occur

  Scenario: Unauthenticated readers do not see Newsroom appendix pages
    Given I open the "current-edition" layout scenario at 1280 by 900
    Then edition page count should not include appended Newsroom pages
    And the front page footer should not link to the newsroom
    And no Newsroom appendix pages should render
    And no browser console errors should occur

  Scenario: Editor readers see Newsroom appendix pages after the edition
    Given I am a test editor reader
    And I open the "current-edition" layout scenario at 1280 by 900
    Then edition page count should include appended Newsroom pages
    When I scroll to the canonical category register
    Then the final edition pages should include the canonical category register
    And the appendix page should use newspaper page styling
    When I scroll to the appendix page for root category "Foundation Model Scaling"
    Then the root category appendix page should show subcategory "Agent Memory"
    And no browser console errors should occur

  Scenario: Newsroom appendix pages fit on mobile
    Given I am a test editor reader
    And I open the "current-edition" layout scenario at 390 by 900
    When I scroll to the canonical category register
    Then the Newsroom appendix should not overflow horizontally
    And no browser console errors should occur

  Scenario: Archive renders an infinite front page grid
    Given I open the archive page at 1280 by 900
    Then the archive masthead should say "ARCHIVE"
    And the archive masthead should use the normal newspaper nameplate height
    And the archive header should describe previous editions
    And the archive page should expose the shared rhythm overlay
    And the archive layout should follow the archive rhythm
    And the archive should render front page preview cards
    And archive preview cards should be compact on the rhythm
    And archive preview cards should link to canonical edition routes
    And archive previews should include masthead, front grid, and footer
    And the archive should use a paper header over a neutral gray grid substrate
    And the archive API should cap requested batches at 12
    And the archive sentinel should load another batch when more editions exist
    And no browser console errors should occur

  Scenario: Archive uses a two-column phone grid
    Given I open the archive page at 390 by 900
    Then the archive should render front page preview cards
    And the archive should render a two-column front page grid
    And no browser console errors should occur

  Scenario: Scroll edition materializes visible pages and keeps placeholders
    Given I open the front page at 1280 by 900
    Then page 1 should be materialized
    And page 2 should be materialized
    And page 3 should be a page placeholder
    And no flipbook UI classes should be rendered
    When I scroll to page 3
    Then page 3 should be materialized
    And the active visible page should be 3
    And no browser console errors should occur

  Scenario: Continuation jump uses GSAP ScrollTo jump
    Given I open the front page at 1280 by 900
    When I follow the continuation jump for article "schools-reading-lab"
    Then the active visible page should be 3
    And the browser path should be "/2026/may/13/page/3"
    And page 3 should be materialized
    And no browser console errors should occur

  Scenario: Date page routes replace page hash state
    Given I open the edition path "/2026/may/13/page/2" at 1280 by 900
    Then the active visible page should be 2
    And the browser path should be "/2026/may/13/page/2"
    When I scroll to page 3
    Then the active visible page should be 3
    And the browser path should be "/2026/may/13/page/3"
    And no browser console errors should occur

  Scenario: Date-scoped article routes and edition anchors resolve
    Given I open the edition path "/2026/may/13/agent-procedure-patterns" at 1280 by 900
    Then the article page should show headline "Self-Evolving Agents Learn to Rewrite Their Own Playbooks"
    And the article back link should target "/2026/may/13#agent-procedure-patterns"
    Given I open the edition path "/2026/may/13#agent-procedure-patterns" at 1280 by 900
    Then the browser hash should be "#agent-procedure-patterns"
    And article "agent-procedure-patterns" should have exactly one edition anchor
    And no browser console errors should occur

  Scenario: Reader settings change the edition renderer without changing content URLs
    Given I open the settings page at 1280 by 900
    Then reader format "Newspaper" should be selected
    When I choose reader format "Blog"
    Then reader format "Blog" should be selected
    And settings should be saved in this browser
    When I reload the current page
    Then reader format "Blog" should be selected
    When I open the "current-edition" layout scenario in the same browser
    Then the active presentation should be "blog"
    And the reader presentation switcher should not render
    And the browser path should be "/"
    And presentation section "ai-ml" should render
    And presentation item "agent-procedure-patterns" should render with measured lines
    And the blog presentation footer should list edition sections
    And the blog presentation footer should include utility links
    When I open the settings page in the same browser
    And I choose reader format "Magazine"
    And I open the "current-edition" layout scenario in the same browser
    Then the active presentation should be "magazine"
    And the reader presentation switcher should not render
    And the browser path should be "/"
    And presentation section "ai-ml" should render
    And presentation item "agent-procedure-patterns" should render with measured lines
    And no browser console errors should occur

  Scenario: Section routes and item routes stay separate content links
    Then edition section route "/2026/may/13/section/ai-ml" should target section "ai-ml"
    And edition item route "/2026/may/13/agent-procedure-patterns" should target item "agent-procedure-patterns"

  Scenario: Layout validation accepts only canonical headline scales
    Then layout plan validation should accept headline scale "feature"
    And layout plan validation should reject headline scale "poster"
    And layout plan validation should accept editorial priority "primary"
    And layout plan validation should reject editorial priority "urgent"

  Scenario: Scroll edition reaches pages one at a time
    Given I open the "current-edition" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the active page should be a "articlePage" page
    When I scroll to page 3
    Then the active page should be a "regionStack" page
    When I scroll to page 2
    Then the active page should be a "articlePage" page
    And no browser console errors should occur

  Scenario: Shared continuation uses pull quotes when they improve the fit
    Given I open the "current-edition" layout scenario at 1280 by 900
    When I scroll to page 3
    Then the "schools-reading-lab" section should show a responsive pull quote
    And the "market-hall" section should show a responsive pull quote
    And responsive pull quotes should have no background
    And responsive pull quotes should fit their quote text without excess rows
    And responsive pull quotes should leave one rhythm row before copy
    And no solved furniture should overlap within a section
    And no measured line should overlap solved furniture
    And no browser console errors should occur

  Scenario: Single-story continuation can shrink to solved content
    Given I open the "current-edition" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the "agent-procedure-patterns" section should exhaust the remaining article text
    And the active continuation region should shrink to its solved blocks
    And the active page should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Stacked continuation regions fill by default
    Given I open the "height-policy-fill-default" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the active continuation region should preserve allocated fill height
    And the active page should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Article frames honor default row targets
    Given I open the "height-policy-default-rows" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the "agent-procedure-patterns" section should hold exactly 64 default rows
    And the active continuation region should shrink to its solved blocks
    And the active page should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Article frames can grow beyond default row targets
    Given I open the "height-policy-default-rows-grow" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the "agent-procedure-patterns" section should grow beyond 12 default rows
    And the "agent-procedure-patterns" section should exhaust the remaining article text
    And the active page should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Article frames can shrink below default row targets
    Given I open the "height-policy-default-rows-shrink" layout scenario at 1280 by 900
    When I scroll to page 2
    Then the "agent-procedure-patterns" section should shrink below 64 default rows
    And the active continuation region should shrink to its solved blocks
    And the active page should follow the vertical rhythm
    And no browser console errors should occur

  Scenario: Sparse copy rejects oversized article furniture
    Given I open the "furniture-sufficiency-pressure" layout scenario at 1280 by 900
    When I scroll to page 3
    Then the "schools-reading-lab" section should not show a responsive image inset
    And the "market-hall" section should not show a pull quote
    And the "market-hall" section should exhaust the remaining article text
    And no continuation column should be dead
    And no solved furniture should overlap within a section
    And no measured line should overlap solved furniture
    And no browser console errors should occur

  Scenario: Wide media insets preserve image frame aspect
    Given I open the "current-edition" layout scenario at 2400 by 900
    When I scroll to page 3
    Then the "market-hall" section image should span 2 columns
    And the "market-hall" section image should be centered at the top
    And the "market-hall" section image frame should preserve its aspect ratio
    And the "market-hall" section image should leave one rhythm row before copy
    And the "market-hall" section adjacent copy should flow beside the image
    And no browser console errors should occur

  Scenario: Long image captions reserve complete rhythm rows
    Given I open the "long-image-caption" layout scenario at 2400 by 900
    When I scroll to page 3
    Then the "market-hall" section image caption should render completely
    And image captions should have no background
    And no measured line should overlap solved furniture
    And no browser console errors should occur

  Scenario: Pull quotes are omitted when the article has no editorial quote
    Given I open the "shared-continuation-no-pull-quotes" layout scenario at 1280 by 900
    Then the active content scenario should be "shared-continuation-no-pull-quotes"
    When I scroll to page 3
    Then the "schools-reading-lab" section should not show a pull quote
    And the "market-hall" section should not show a pull quote
    And no solved furniture should overlap within a section
    And no measured line should overlap solved furniture
    And no browser console errors should occur

  Scenario: Theme-aware raster image sources switch in dark mode
    Given I open the "themed-ink-study" layout scenario at 1280 by 900
    Then the active page should swap raster image sources between light and dark theme
    And no browser console errors should occur

  Scenario Outline: Article chrome does not overlap under responsive typography
    Given I open the "<scenario>" layout scenario at 1280 by 900
    Then no article chrome should overlap
    And no measured line should be cropped
    When I scroll to page 2
    Then no article chrome should overlap
    And no measured line should be cropped
    And no browser console errors should occur

    Examples:
      | scenario             |
      | current-edition      |
      | front-chrome-compact |

  Scenario: Direct article routes resolve content through the repository
    Given I open article "schools-reading-lab" at 1280 by 900
    Then the article page should show headline "Agent Reliability Papers Turn Demos Into Stress Tests"
    And the article page should show deck "Benchmarks are starting to treat agents as production systems that must survive tools, memory, multi-turn work, and boring failure modes."
    And no browser console errors should occur
