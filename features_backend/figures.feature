@cli
Feature: Figures are drawn once, rendered in light and dark, and checked the same way for every site
  A diagram, chart or illustration for a Story is one SVG source written with color roles. `papyrus figures render` resolves it twice,
  once for the light theme and once for the dark theme, lays it out in headless Chromium with the fonts embedded, measures the real layout
  for its checks (type size on a phone, text at the margin or hanging off its shape, contrast, overlapping labels, thin lines), and writes a
  light picture and a dark picture at twice the canvas size. Light and dark are both mandatory: there is no way to ask for one theme, a
  problem in either theme fails the figure, and `stories save-version` warns when a figure is saved with only a light picture (a site or an
  editor can make that a refusal instead). The general rules and the shape library belong to Papyrus and name no brand. Everything that
  belongs to one site, its colors, fonts, role mapping and worked examples, is that site's design system, which is read through one loading
  seam: a folder today and the site's backend later. A site with no design system gets a stated, unbranded default or a question, and
  never an invented brand. The checks and the rendering run on the machine that calls them and reach no site and no AWS account.

  Scenario: The rules say outright that light and dark are both mandatory
    When an agent runs "papyrus figures rules"
    Then the command succeeded
    And the printed text starts with "# Figure rules"
    And the printed text contains "## 0. Light and dark are both mandatory"
    And the printed text contains "Every figure ships in a light picture and a dark picture, always."
    And the printed text contains "Never invent a brand"
    And the printed text names no site, brand or font of any publication

  Scenario: The shape library is available to an agent that has no checkout
    When an agent runs "papyrus figures primitives"
    Then the command succeeded
    And the printed text contains "symbol id="
    And the printed text contains "arrow-head"
    And the printed text contains "hatch-pattern"

  Scenario: Rendering needs a design system, and a missing one is never replaced by an invented brand
    Given a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain" in the working folder
    Then the command failed
    And the printed error contains "never invent a brand"
    And the printed error contains "--neutral-default"
    And no picture was written

  Scenario: A site with no design system can use the stated neutral default
    Given a Chromium is available to render with
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --neutral-default" in the working folder
    Then the command succeeded
    And the printed text contains "plain: ok"
    And the printed text contains "note: this design system names a generic font and embeds none"

  Scenario: One source always produces a light picture and a dark picture
    Given a Chromium is available to render with
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --neutral-default --out pictures" in the working folder
    Then the command succeeded
    And the folder "pictures" holds "plain.png", "plain.dark.png" and "plain.figure.json"
    And the light and dark pictures have the same size, twice the canvas width wide
    And the light and dark pictures differ
    And "plain.figure.json" lists the themes "light" and "dark"

  Scenario: A site's own design system supplies the colors, and the dark values differ from the light ones
    Given a Chromium is available to render with
    And a design system folder "site-design" with a light ink of "#202020" and a dark ink of "#fafafa"
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --design-system site-design --check-only --json" in the working folder
    Then the command succeeded
    And the printed JSON names the design system "Neutral default (unbranded)" with figure "plain" ok
    And no picture was written

  Scenario: A problem in the dark theme alone fails the figure
    Given a Chromium is available to render with
    And a design system folder "site-design" whose dark ink is almost the same color as its dark tile
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --design-system site-design --check-only" in the working folder
    Then the command failed
    And the printed text contains "plain: PROBLEM: dark:"
    And the printed text does not contain "plain: PROBLEM: light:"
    And the printed text contains "plain: FAILED"

  Scenario: The source is checked before anything is drawn
    Given a Chromium is available to render with
    And a figure folder "plain" holding a figure that uses a raw color
    When an agent runs the figures command "papyrus figures render plain --neutral-default" in the working folder
    Then the command failed
    And the printed text contains "figure.svg holds a raw color"
    And no picture was written

  Scenario: There is no way to render only one theme
    Given a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --neutral-default --light-only" in the working folder
    Then the command failed
    And the printed error contains "Unknown flag --light-only"

  Scenario: A design system whose color has no dark value cannot be used to draw
    Given a design system folder "site-design" in which one color has no dark value
    And a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures render plain --design-system site-design" in the working folder
    Then the command failed
    And the printed error contains "no dark value; light and dark are both mandatory"

  Scenario: A design system can be loaded from any source that answers the same three questions
    Given a design system source that keeps its files in memory
    When the design system is loaded through the seam
    Then it has the neutral canvas and its source is "in memory"
    And no folder was read

  Scenario: The directive for the Story is printed from the figure's own description
    Given a figure folder "plain" holding a clean one-tile figure
    When an agent runs the figures command "papyrus figures directive plain" in the working folder
    Then the command succeeded
    And the printed text starts with "::image{"
    And the printed text contains "plain.png"
    And the printed text contains "caption="
    And the printed text contains "Approved by <name>."

  Scenario: Saving a figure with only a light picture warns
    Given a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run
    Then the save went ahead
    And the output warns that "chart.png" is a figure with no dark picture

  Scenario: A site or an editor can refuse a figure with only a light picture
    Given a pictures folder holding the figure "chart" with a light picture only
    When a story version is saved with those pictures as a dry run, requiring dark figures
    Then the save was refused naming "chart.png" and saying dark pictures are required
    When a story version is saved with those pictures as a dry run, with PAPYRUS_REQUIRE_DARK_FIGURES set
    Then the save was refused naming "chart.png" and saying dark pictures are required

  Scenario: A complete figure saves without a warning
    Given a pictures folder holding the figure "chart" with both pictures
    When a story version is saved with those pictures as a dry run, requiring dark figures
    Then the save went ahead
    And the output has no figure warning

  Scenario: An ordinary photograph with no dark picture is not a figure and is not warned about
    Given a pictures folder holding the photograph "chart" with a light picture only
    When a story version is saved with those pictures as a dry run
    Then the save went ahead
    And the output has no figure warning

  Scenario: The commands document themselves
    When an agent runs "papyrus figures render --help"
    Then the command succeeded
    And the printed text contains "--design-system DIR"
    And the printed text contains "--neutral-default"
    And the printed text contains "Writes: nothing on a site"
    When an agent runs "papyrus guide figures"
    Then the printed text starts with "## Draw a figure"
    And the printed text contains "Both light and dark are mandatory"

  Scenario: The skill covers the whole job and points at the rules that bind it
    Given the figures skill in ".agents/skills/figures/SKILL.md"
    Then the skill covers deciding whether to draw, choosing a form, acceptance criteria, drawing, checking, approval and saving into a Story
    And the skill says that light and dark are both mandatory
    And the skill says to read the site's design system and never to invent a brand
    And ".claude/skills" is the same folder as ".agents/skills"

  Scenario: The copywriting skill and the story procedure send an agent to the figures skill
    Then the copywriting skill links to the figures skill
    And the story procedure's illustration step links to the figures skill
