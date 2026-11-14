Feature: A knowledge run can be taken back as one step
  A knowledge run writes pages and ideas into a site in bulk. When a run turns out to be wrong,
  someone has to take all of it back, and until now nothing on a page said which run made it,
  so cleanup meant guessing by type and stage. Every Item a run writes now records the run in
  its metadata. Undoing a run moves the Items it created to the retired stage and unpublishes
  the live ones, and never deletes anything. Undo is a dry run until it is told to apply, because
  this command line writes by default everywhere else and this command must not. Restoring puts
  the Items back. A person's own Items never carry a run, so an undo never touches them.

  Background:
    Given a site whose published article names the entities "Acme Loom" (maker) and "Beta Spool" (tool)

  Scenario: Every page a run writes records that run
    When the wiki sync applies as run "first-run"
    Then every wiki page records "first-run" as the run that wrote it and the run that created it

  Scenario: A later run that rewrites a page becomes its latest writer but not its creator
    Given the wiki sync applied as run "first-run" and every page was published
    And the entity "Acme Loom" was described
    When the wiki sync applies as run "second-run"
    Then the page for "Acme Loom" records "second-run" as the latest writer and "first-run" as its creator

  Scenario: An idea filed by a run records the run and is still labelled as generated
    When a run named "idea-run" files a generated idea
    Then the idea records "idea-run" as its creator
    And the idea is still labelled as written by AI

  Scenario: Undo writes nothing unless it is told to apply
    Given the wiki sync applied as run "first-run" and every page was published
    When the run "first-run" is undone without applying
    Then that command wrote no record
    And the report says it is a dry run and counts 2 pages to retire, both live
    And both pages are still live

  Scenario: Undo unpublishes and retires the pages of the run and deletes nothing
    Given the wiki sync applied as run "first-run" and every page was published
    When the run "first-run" is undone and applied
    Then both pages are retired, are drafts and are not live
    And both pages still exist
    And the list of pages to remove from the site holds both

  Scenario: Undo touches only the run it names
    Given the wiki sync applied as run "first-run" and every page was published
    And a later run "second-run" created the page for "Cog Works"
    When the run "second-run" is undone and applied
    Then the page for "Cog Works" is retired
    And the earlier run's pages "Acme Loom" and "Beta Spool" are still live

  Scenario: Items made by a person are never selected
    Given a person saved an article by hand
    When the run "first-run" is undone and applied
    Then the article is not retired

  Scenario: The next run does not bring a retired page back
    Given the wiki sync applied as run "first-run" and every page was published
    And the run "first-run" was undone and applied
    When the wiki sync applies as run "second-run" and every draft is published
    Then both pages are retired, are drafts and are not live

  Scenario: Undoing a run twice changes nothing the second time
    Given the wiki sync applied as run "first-run" and every page was published
    And the run "first-run" was undone and applied
    When the run "first-run" is undone and applied again
    Then that command wrote no record

  Scenario: Restore puts the pages back as drafts, and publishing makes them live again
    Given the wiki sync applied as run "first-run" and every page was published
    And the run "first-run" was undone and applied
    When the run "first-run" is restored and applied
    Then both pages are drafts that are no longer retired
    When all wiki drafts are published
    Then both pages are live
