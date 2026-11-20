@cli
Feature: A site's design system is backend data, published from the site's repository and read through the signed-in CLI
  A site's tokens (a light and a dark value for every color, and the type styles), its fonts, the mapping from figure roles to those tokens, and its worked
  examples are that site's design system. They are stored in the site's backend next to its mission and policy, so an agent that can sign in to the site
  but cannot see its code can still draw figures that look like the site. They are kept the way the other guidelines are kept: the database holds only a
  catalog row (the slug, the version, who saved it, when, why and a hash of the content), and the content itself, text and fonts, is files in S3 attached
  to that version. No text is stored in the database, and nothing here adds a table, an index or a subscription. A site's repository stays the place
  where the design system is edited, and publishes it with `papyrus design-system push` as part of its deploy. `papyrus design-system show` and `pull`
  read it back, `papyrus figures render` draws with it when it is given no other design system, and the site can also say that a figure with no dark
  picture is refused when a Story is saved. Everything is checked against an in-memory backend that fails on any table scan; no site and no AWS account is
  reached.

  Background:
    Given a site that stores no design system yet

  Scenario: Pushing a design system stores a catalog row in the database and the content in S3
    Given a design system folder "site-design" with two fonts and one worked example
    When the folder "site-design" is pushed with the reason "First design system"
    Then the push saved version 1
    And exactly one design system row is stored, for the slug "editorial-doctrine-design-system", with an empty body and no metadata
    And one file holding the mapping, the tokens and the worked example is stored in S3 as the "doctrine_document" of that row
    And each of the two fonts is stored in S3 as a "doctrine_asset" of that row
    And nothing of the design system's text is in the database rows

  Scenario: A preview writes nothing
    Given a design system folder "site-design" with two fonts and one worked example
    When the folder "site-design" is pushed as a dry run with the reason "First design system"
    Then the output says it would save version 1 and lists the mapping, the example and both fonts
    And no row and no file is stored

  Scenario: Pushing the same design system again makes no new version
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    When the folder "site-design" is pushed with the reason "Again"
    Then the push reported the design system unchanged at version 1
    And only one catalog row is stored

  Scenario: Changing a font makes a new version and the older version stays readable
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    When one font of "site-design" is replaced and the folder is pushed with the reason "New display font"
    Then the push saved version 2
    And version 2 is the current design system and version 1 is superseded
    And reading version 1 returns the old font and reading the current one returns the new font
    And the design system's history lists "New display font" before "First design system"

  Scenario: A design system that cannot be used to draw is refused and nothing is stored
    Given a design system folder "site-design" in which one color has no dark value
    When the folder "site-design" is pushed with the reason "Broken"
    Then the push was refused saying "no dark value; light and dark are both mandatory"
    And no row and no file is stored

  Scenario: A setting the site does not have is refused
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireLight": true}
    When the folder "site-design" is pushed with the reason "Odd setting"
    Then the push was refused saying "not a figure setting"
    And no row and no file is stored

  Scenario: The stored design system answers the three questions a folder answers
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    Then the stored design system returns the same mapping text, the same font bytes and the same worked examples as the folder
    And loading the stored design system gives the same roles, tokens, fonts and type styles as loading the folder

  Scenario: Showing the design system says what it holds, or that the site has none
    When an agent shows the site's design system
    Then the printed text contains "This site has no design system"
    And the printed text contains "--neutral-default"
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireDarkFigures": true}
    And the folder "site-design" has been pushed with the reason "First design system"
    When an agent shows the site's design system
    Then the printed text contains "version 1"
    And the printed text contains "examples/one"
    And the printed text contains "fonts/Display.ttf"
    And the printed text contains "requireDarkFigures = true"
    When an agent shows the site's design system as JSON
    Then the printed JSON has version 1, the setting requireDarkFigures true and the figure role "ground"

  Scenario: Pulling writes back the folder that was pushed
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireDarkFigures": true}
    And the folder "site-design" has been pushed with the reason "First design system"
    When an agent pulls the design system into the new folder "pulled"
    Then the folder "pulled" holds exactly the files of "site-design", with the same bytes
    When an agent pulls the design system into the new folder "pulled" again
    Then the command failed
    And the printed error contains "is not empty"

  Scenario: A stored font that was changed behind the site's back is refused
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    When a stored font file is changed in S3
    Then reading that font from the stored design system is refused because it does not match its hash

  Scenario: Reading never lists or scans a table
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    When the design system, its history, its settings and its context entry are read
    Then every design system read was a query on the slug index or the attachment owner index

  Scenario: The design system belongs to one tenant
    Given a design system folder "site-design" with two fonts and one worked example
    And the site belongs to the tenant "tenant-a" with the slug "acme"
    And the folder "site-design" has been pushed with the reason "First design system"
    Then the catalog row carries the tenant slug "acme"
    But a session of the tenant "tenant-b" cannot read it

  Scenario: A push with no settings file keeps the site's settings, and an explicit false turns the setting off
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireDarkFigures": true}
    And the folder "site-design" has been pushed with the reason "First design system"
    When one font of "site-design" is replaced, the setting file removed, and the folder pushed with the reason "Font only"
    Then the site requires dark figures
    When the folder "site-design" has the setting file {"requireDarkFigures": false} and is pushed with the reason "Allow light"
    Then the site does not require dark figures

  Scenario: The context pack points an agent at the design system
    When the editorial context entry for the design system is built
    Then there is no design system entry
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    When the editorial context entry for the design system is built
    Then the entry names version 1, says to read it with "papyrus design-system show" and says never to invent a brand
    And building the entry made one index query and downloaded nothing

  Scenario: Drawing a figure uses the site's stored design system when no other is named
    Given a Chromium is available to render with
    And a design system folder "site-design" with a light ink of "#202020" and a dark ink of "#fafafa"
    And the folder "site-design" has been pushed with the reason "First design system"
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --check-only --json" in the working folder
    Then the command succeeded
    And the printed error contains "using the site's stored design system"
    And the printed JSON names the design system "Neutral default (unbranded)" with figure "plain" ok

  Scenario: A folder named on the command line overrides the stored design system
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --design-system missing-folder --check-only" in the working folder
    Then the command failed
    And the printed error contains "missing-folder"
    And the site's design system was not read

  Scenario: With no stored design system, drawing stops instead of inventing a brand
    Given a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain" in the working folder
    Then the command failed
    And the printed error contains "the site stores none"
    And the printed error contains "--neutral-default"
    And the printed error contains "never invent a brand"
    And no picture was written

  Scenario: When the site cannot be reached, drawing says why and does not guess
    Given the site cannot be read because the session is not signed in
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain" in the working folder
    Then the command failed
    And the printed error contains "reading the site's design system failed (not signed in)"
    And the printed error contains "never invent a brand"

  Scenario: A site that requires dark figures refuses a Story version with a light-only figure
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireDarkFigures": true}
    And the folder "site-design" has been pushed with the reason "First design system"
    And a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run
    Then the save was refused naming "chart.png" and saying dark pictures are required
    And the refusal names this site's requireDarkFigures setting

  Scenario: A site that does not require dark figures only warns
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has been pushed with the reason "First design system"
    And a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run
    Then the save went ahead
    And the output warns that "chart.png" is a figure with no dark picture

  Scenario: The environment variable and the flag override the site's setting
    Given a design system folder "site-design" with two fonts and one worked example
    And the folder "site-design" has the setting file {"requireDarkFigures": true}
    And the folder "site-design" has been pushed with the reason "First design system"
    And a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run, with PAPYRUS_REQUIRE_DARK_FIGURES set to "0"
    Then the save went ahead
    And the output warns that "chart.png" is a figure with no dark picture
    When a story version is saved with those pictures as a dry run, requiring dark figures
    Then the save was refused naming "chart.png" and saying dark pictures are required

  Scenario: A site's setting is not read when every figure has both pictures
    Given the site cannot be read because the session is not signed in
    And a pictures folder holding the figure "chart" with both pictures
    When a story version is saved with those pictures as a dry run
    Then the save went ahead
    And the output has no figure warning

  Scenario: A setting that cannot be read is reported, not guessed
    Given the site cannot be read because the session is not signed in
    And a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run
    Then the save was refused saying the site's requireDarkFigures setting could not be read

  Scenario: The commands document themselves
    When an agent runs "papyrus design-system push --help"
    Then the command succeeded
    And the printed text contains "--reason TEXT"
    And the printed text contains "--dry-run"
    And the printed text contains "requireDarkFigures"
    When an agent runs "papyrus design-system"
    Then the printed text contains "show"
    And the printed text contains "pull"
    And the printed text contains "push"
    When an agent runs "papyrus guide figures"
    Then the printed text contains "papyrus design-system show"
