Feature: The Newsletter page runs the site's email from the newsroom
  Under Administration, editors and admins see how many people are on each list, the issues with
  their status and counts, who each issue went to, and whether sending is paused. Admins also
  approve an issue for a time, stop one that is sending, resume a paused site, and see, export and
  erase subscribers. The page uses fixture data in the demo workspace.

  @brand-agnostic
  Scenario: An admin reads the lists, the pause and the issues
    Given I open the newsletter newsroom at 1280 by 900
    Then the newsletter page should show the section "Lists"
    And the newsletter page should show the section "Issues"
    And the newsletter page should show the section "Site status"
    And the newsletter page should show the section "Subscribers"
    And the newsletter list "Weekly roundup" should read 412 confirmed
    And the newsletter page should say sending is paused
    And the newsletter issue "Weekly roundup: Jan 8 to Jan 15, 2027" should be "Scheduled" with a warning "Edited since approval"
    And the newsletter issue "Weekly roundup: Jan 1 to Jan 8, 2027" should be "Blocked" with a warning "postal address missing"
    And the newsletter issue "An alert with a status this panel does not know" should be "Quarantined"
    And the newsletter issue "Weekly roundup: Dec 18 to Dec 25, 2026" should link to the editor and the archive
    And no newsletter address should be shown outside the subscribers table

  @brand-agnostic
  Scenario: Preview shows the email in a sandboxed frame
    Given I open the newsletter newsroom at 1280 by 900
    When I preview the newsletter issue "Weekly roundup: Jan 15 to Jan 22, 2027"
    Then the newsletter preview should be a sandboxed frame with a plain text version

  @brand-agnostic
  Scenario: An admin approves a draft for a time in the site time zone
    Given I open the newsletter newsroom at 1280 by 900
    When I approve the newsletter issue "Weekly roundup: Jan 15 to Jan 22, 2027" for "2027-01-22T09:00"
    Then the newsletter message should say "Approved for 2027-01-22 09:00 EST"
    And the newsletter issue "Weekly roundup: Jan 15 to Jan 22, 2027" should be "Scheduled"

  @brand-agnostic
  Scenario: Stopping an issue that is sending asks first
    Given I open the newsletter newsroom at 1280 by 900
    When I ask to stop the newsletter issue "Weekly roundup: Dec 25 to Jan 1, 2027"
    Then the newsletter issue "Weekly roundup: Dec 25 to Jan 1, 2027" should be "Sending"
    When I confirm stopping
    Then the newsletter issue "Weekly roundup: Dec 25 to Jan 1, 2027" should be "Stopped"

  @brand-agnostic
  Scenario: An admin resumes a paused site
    Given I open the newsletter newsroom at 1280 by 900
    When I resume newsletter sending
    Then the newsletter page should say sending is on

  @brand-agnostic
  Scenario: Delivery history shows each address and its result
    Given I open the newsletter newsroom at 1280 by 900
    When I open the deliveries of the newsletter issue "Weekly roundup: Dec 18 to Dec 25, 2026"
    Then the newsletter deliveries should list a "bounced" and a "complained" result
    And the newsletter deliveries should show the recent events for that issue

  @brand-agnostic
  Scenario: Erasing a subscriber needs a second step
    Given I open the newsletter newsroom at 1280 by 900
    When I enter the address "reader3@example.com" to erase
    Then the newsletter page should still list "reader3@example.com"
    When I confirm erasing
    Then the newsletter message should say "Erased reader3@example.com"
    And the newsletter page should not list "reader3@example.com"
    And no browser console errors should occur
