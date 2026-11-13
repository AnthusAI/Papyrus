@backend @story-type
Feature: An editor chooses a story's type from the CLI
  A story is an article, a post, or another type the site offers. `papyrus stories create --type post` makes the story with that type, and
  `papyrus stories set-type --story <lineage> --type post` changes the type of a story that is not published yet. The type is a lowercase name that
  is not a system type and not `untyped`; when the site's own list of types is known (a `projection.json` in PAPYRUS_SITE_STATIC_DIR, or in ./web) the
  type must be one the site offers, and with no list the name is accepted with a note and never guessed. A story with no type is `untyped`
  and cannot be published until it has one, so `create` warns when it made one. A published story cannot change type from the CLI, because the address
  of its page depends on the type. A dry run writes nothing. Nothing here reaches a real site, login or AWS.

  Scenario: A new story is made a post
    Given a site that offers the types "article" and "post"
    When an editor creates a story "A post" with type "post"
    Then the story is stored as a "post" with the type status "post#draft"

  Scenario: A new story with no type is untyped
    Given a site that offers the types "article" and "post"
    When an editor creates a story "No type" with no type
    Then the story is stored as an "untyped"

  Scenario: A type the site does not offer is refused
    Given a site that offers the types "article" and "post"
    When an editor asks for the type "guide"
    Then the command refuses it, naming the types "article, post"

  Scenario: An unpublished story changes type and a published one does not
    Given a site that offers the types "article" and "post"
    And a story "Switch me" with no type
    When an editor sets its type to "post"
    Then the story is stored as a "post" with the type status "post#draft"
    When the story is published and an editor sets its type to "article"
    Then the command refuses because the story is published
