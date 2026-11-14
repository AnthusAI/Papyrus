@backend @story-create
Feature: A story made with --with-assignment keeps its References when the assignment fails
  `papyrus stories create --reference ID --with-assignment` makes the Story, attaches each Reference as `based_on`, then opens a `reporting.candidate`
  Assignment. The Story's own `--type` (article, post) is never the Assignment's type, so a typed story still gets its Assignment. The References are attached
  before the Assignment is tried, so a failed Assignment never drops them. When the Assignment step fails the command exits non-zero and says what happened:
  the Story's lineage, how many References were attached, why no Assignment was made, and the command that retries it. Nothing here reaches a real site.

  Scenario: A typed story gets a reporting assignment
    Given a site that offers the types "article" and "post"
    When an editor creates a post "Typed" with a reference and --with-assignment
    Then the assignment was requested with the type "reporting.candidate"
    And the command succeeds and the reference is attached

  Scenario: A failed assignment keeps the references and says so
    Given a site that offers the types "article" and "post"
    When an editor creates a post "Keeps refs" with a reference and --with-assignment but the assignment step fails with "no corpus"
    Then the command exits non-zero
    And the reference is attached to the story
    And the summary says "references attached: 1" and "assignment NOT created: no corpus" and a retry command

  Scenario: A dry run says the assignment type and the references
    Given a site that offers the types "article" and "post"
    When an editor dry-runs creating a post "Preview" with a reference and --with-assignment
    Then the output mentions one reference and a reporting.candidate Assignment
    And no reference or assignment is written
