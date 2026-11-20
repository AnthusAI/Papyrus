@backend @story-reference-links
Feature: An editor points a story to a Reference to read too
  Besides other stories, a story can point a reader to an accepted Reference: "read this source too". It is a looser association than citing or consulting
  the Reference, which stay the reporting trail. An editor writes it with `papyrus stories link-story --story <lineage or slug> --reference <reference id>`,
  repeating `--reference` for several. It is the same `see_also` relation as between stories, but directional (story to Reference) and recorded as kind
  `item.reference-link`. Only accepted References can be linked, because only those are shown on the page: if any Reference is missing or not accepted
  the command stops with a plain message and writes nothing, and there is no override. A repeat writes nothing, and a link a person rejected is never
  revived by a writer. The command prints each Reference's title, host and curation status. `papyrus stories show` lists the story's see-also References,
  `papyrus stories check-links` judges them, and agents pass `see_also_references` to `papyrus_link_stories`. The CLI runs for real against a stand-in
  for the site; nothing here reaches a real site, login or AWS.

  Background:
    Given a site with a story "A big story" and accepted, pending and rejected References

  Scenario: An editor points a story to two accepted References
    When a signed-in editor asks the CLI: "papyrus stories link-story --story big --reference ref-a --reference ref-b --note 'read this too'"
    Then the link command succeeds
    And it printed a "write" line for "Title ref-a" with host "example.org" and status "accepted"
    And there are 2 see-also edges from the story to References, each recorded as added by "Grace Editor"

  Scenario: A Reference that is not accepted refuses the whole command
    When a signed-in editor asks the CLI: "papyrus stories link-story --story big --reference ref-a --reference ref-pending"
    Then the command stopped saying the Reference is pending and nothing was written

  Scenario: A missing Reference refuses the whole command
    When a signed-in editor asks the CLI: "papyrus stories link-story --story big --reference ref-a --reference ref-none"
    Then the command stopped saying the Reference was not found and nothing was written

  Scenario: Pointing to the same Reference again writes nothing
    Given the editor has already pointed the story to "ref-a"
    When a signed-in editor asks the CLI: "papyrus stories link-story --story big --reference ref-a"
    Then the link command succeeds
    And it printed an "exists" line and wrote nothing

  Scenario: A rejected link is not revived
    Given the editor has already pointed the story to "ref-a"
    And a person rejected that link
    When the writer is asked to link the story to "ref-a" again
    Then the outcome is "rejected" and the stored link is unchanged

  Scenario: The story shows its see-also References
    Given the editor has already pointed the story to "ref-a"
    When an editor shows the story
    Then the output lists the see-also Reference "Title ref-a"

  Scenario: An agent tool links accepted References and refuses the rest
    When an agent calls papyrus_link_stories with see_also_references "ref-a"
    Then the agent's link is written as derived
    And an agent call with "ref-b" and "ref-pending" is refused and writes nothing more

  Scenario: The audit judges story-to-Reference edges
    Given the editor has already pointed the story to "ref-a"
    And the Reference "ref-a" was later rejected and a hand-written "supersedes" edge points at it
    When the story links are checked
    Then it reports a "reference not accepted" problem and a "wrong predicate" problem and nothing else
