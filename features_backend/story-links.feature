@backend @story-links
Feature: An editor links a story to related stories
  A story's See also block lists other stories that go with it: an article points to related articles, and a larger story points to several of its
  posts. An editor builds that list with `papyrus stories link-story --story <lineage or slug> --to <lineage or slug>`, repeating `--to` to attach
  many stories in one call, in a session opened with `papyrus login`. A link is a `see_also` SemanticRelation between two stories. It is
  symmetric, so a link from A to B and one from B to A are the same link: if either exists the command says so and writes nothing, which makes it safe
  to repeat. The editor and administrator groups may create a SemanticRelation but never update one, so a link is only ever created. The command
  prints each target's title, type and stage, and warns (without failing) when a target is not published yet, because the public See also block shows
  published stories only. There is exactly one relation name, `see_also`, written by the code and read by the page: no command, tool or argument
  can choose another, and a story-to-story relation under any other name is listed by `papyrus stories show` as not official. `papyrus stories show` lists a story's related stories from either end. The CLI runs for real against a stand-in for the
  site that enforces those rules; nothing here reaches a real site, login or AWS.

  Background:
    Given a site with a published article "A big story", a published post "First post" and a draft post "Second post"

  Scenario: An editor attaches an article to several posts in one call
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --to post-2"
    Then the link command succeeds
    And it printed a "write" line for "First post" as a post at stage published
    And it printed a "write" line for "Second post" as a post at stage draft
    And there are 2 links, each recorded as added by "Grace Editor"

  Scenario: A target that is not published yet is a warning, not an error
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-2"
    Then the link command succeeds
    And it warned that "Second post" is not published yet and the public See also block shows published stories only
    And there is 1 link

  Scenario: Linking the same pair again, from either end, writes nothing
    Given the editor has already linked "A big story" and "First post"
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story post-1 --to big"
    Then the link command succeeds
    And it printed an "exists" line for "A big story" and no "write" line
    And there is still 1 link

  Scenario: A story cannot be linked to itself
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --to big"
    Then the link command fails with "A story cannot be linked to itself"
    And there are 0 links

  Scenario: Every target must be an existing story before anything is written
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --to missing"
    Then the link command fails with "No story found"
    And there are 0 links

  Scenario: A dry run says what would happen and writes nothing
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --dry-run"
    Then the link command succeeds
    And it printed a "dry run" line for "First post" and no "write" line
    And there are 0 links

  Scenario: A viewer cannot create a link and sees no write line
    When a signed-in viewer "Val Viewer" asks the CLI: "papyrus stories link-story --story big --to post-1"
    Then the link command fails with "Not Authorized to access createSemanticRelation"
    And the link command printed no write line

  Scenario: A story's page in the CLI lists its related stories from either end
    Given the editor has already noted a link from "A big story" to "Second post" saying "goes deeper"
    When an editor shows the story "post-2"
    Then the related stories listed are "A big story" as an article at stage published with the note "goes deeper"
    When an editor shows the story "big"
    Then the related stories listed are "Second post" as a post at stage draft with the note "goes deeper"

  Scenario: No relation name can be chosen, so every link carries the one official name
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1 --relation expands_on"
    Then the link command fails with "Allowed values: see_also"
    And there are 0 links
    When a signed-in editor "Grace Editor" asks the CLI: "papyrus stories link-story --story big --to post-1"
    Then the written link is the one official relation see_also, with its seeded relation type

  Scenario: A link written by hand under another name is surfaced, not silently ignored
    Given someone wrote a link from "A big story" to "First post" by hand under the name "relatedto"
    When an editor shows the story "big" as JSON
    Then the JSON lists no related stories and flags the relation "relatedto" as not official
