@backend @link-rerender
Feature: Linking stories re-renders the affected pages without purging the edge
  A new `see_also` or concept link only shows on a story's page once something renders that page again. So right after a real write that created a link,
  `papyrus stories link-story` and `papyrus stories link-concept` ask the site to re-render exactly the published stories whose page changed, using the
  page re-render with no invalidation: nothing is purged, because the site's HTML lasts five minutes and every purged path is billed. Both ends of a story
  link are re-rendered, the story of a concept link is, and a Reference (which has no public page) is not. A dry run, a repeat that wrote nothing and an
  unpublished story re-render nothing, and `--no-rerender` skips it. A re-render that fails is a warning that names the story and the manual command; the
  link stays and the command succeeds. The agent tools do the same and return a `rerendered` list. The page re-render is a stand-in here; nothing reaches a real site.

  Background:
    Given a site with a published article "A big story", a published post "First post" and a draft post "Second post"
    And the page re-render is a recording stand-in

  Scenario: Both ends of a new story link are re-rendered with no purge
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1"
    Then the link command succeeds
    And the stories re-rendered were "item-big, item-post-1"
    And it printed "rerender" lines saying "no purge" and the closing line "visible on the site within about five minutes; nothing was purged"

  Scenario: A draft target is not re-rendered
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --to post-2"
    Then the stories re-rendered were "item-big, item-post-1"

  Scenario: A dry run and --no-rerender re-render nothing
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --dry-run"
    Then no story was re-rendered
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --no-rerender"
    Then no story was re-rendered

  Scenario: A failed re-render is a warning and the link stays
    Given the re-render of "item-post-1" fails
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1"
    Then the link command succeeds
    And there is 1 link
    And the warning names the manual command "papyrus ops content rerender --story item-post-1 --no-invalidate"
