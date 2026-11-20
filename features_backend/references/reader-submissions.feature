Feature: Public submit-a-link for readers
  A signed-in reader with a handle submits a link. It is public at once as pending, the same canonical URL cannot be
  submitted twice, similar recent links from the same site are a warning, and the count is limited per day. Entity
  extraction and the spam checks run later in the worker, never in the request.

  Background:
    Given a publication whose readers rate "real" and "useful"
    And the published items "item-one" and "item-two"
    And the signed-in readers "alice" and "bob"

  Scenario: A submission is public immediately as pending
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link with the note "Worked well" titled "A small tool"
    Then "alice" is answered with status 201
    And the answer to "alice" says the submission is pending with extraction pending
    When the snapshot runs
    Then the public file "_data/reader/submissions.json" lists 1 submission by "quiet-fox" as pending

  Scenario: A handle comes first
    When "alice" submits the first link titled "A small tool"
    Then "alice" is answered with status 422 "handle_required"
    And there are 0 stored submissions

  Scenario: The same canonical URL is submitted once
    Given "alice" is the submitter of the first link
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" submits the first link titled "A small tool"
    And "bob" submits the first link titled "The same tool"
    Then "bob" is answered with status 409 "duplicate_submission"
    And the refusal to "bob" names the existing submission
    And there is 1 stored submission

  Scenario: Another link from the same site in the last 48 hours is a warning only
    When "alice" picks the handle "quiet-fox"
    And "bob" picks the handle "loud-owl"
    And "alice" submits the first link titled "A small tool"
    And "bob" submits the second link titled "Another post"
    Then "bob" is answered with status 201
    And the answer to "bob" warns about 1 similar link
    And there are 2 stored submissions

  Scenario: A new account gets a third of the daily limit
    When "alice" picks the handle "quiet-fox"
    And "alice" submits 5 different links
    Then "alice" was refused 2 times with status 429
    And there are 3 stored submissions

  Scenario: Upvotes on a submission earn its submitter karma
    Given "alice" is the submitter of the first link
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And "bob" upvotes the first submission
    And the snapshot runs
    Then the public file "_data/reader/items.json" shows 1 upvote on the first submission
    And "quiet-fox" is on the karma list with 1

  Scenario: The worker adds spam signals after the request
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the link "https://bit.ly/zzz" titled "Buy now and earn $100 a day"
    Then there are 1 stored submissions
    When the snapshot runs
    Then the stored submission has humanus signals

  Scenario: The submissions file never identifies a reader
    When "alice" picks the handle "quiet-fox"
    And "alice" submits the first link titled "A small tool"
    And the snapshot runs
    Then the public files hold no site subject, person id or email address
