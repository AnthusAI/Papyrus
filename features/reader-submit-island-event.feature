@brand-agnostic
Feature: The Submit island tells the page about a new submission
  A publication can show a reader what happened to the links they submitted, such as the model, maker and task the
  extraction step found. To do that the page needs the new submission's id, which only the Submit island learns. The
  island announces it as a "papyrus-reader:submitted" event on the document. These scenarios are verified in a real
  browser against a fake reader API by scripts/test-reader-islands.ts (the "submit" tests), which run in test:ci:ts.

  Scenario: A new submission is announced with its id and title
    Given a signed-in reader with a handle on a page with a Submit island
    When the reader submits a new link titled "A small tool" and the server answers 201 with the subject "sub-abc"
    Then the document receives one "papyrus-reader:submitted" event whose detail is the subject "sub-abc" and the title "A small tool"

  Scenario: A duplicate is never announced, because it may be another reader's submission
    Given a signed-in reader with a handle on a page with a Submit island
    When the reader submits a link the server answers as a 409 duplicate of an existing submission
    Then no "papyrus-reader:submitted" event is sent
