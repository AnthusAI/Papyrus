Feature: A publish tells the site's notifications function
  publish_alerts.py is the only place a publish announces. Beside the newsletter, it asynchronously invokes the site's
  notifications function, once per real publish and only after the page is live. A problem with notifications never fails
  or slows a publish, and a site without the plugin invokes nothing. A bulk import must not alert.

  Background:
    Given a site whose notifications plugin is on

  Scenario: A real publish announces once, after the page is live
    When the editor publishes an article
    Then the notifications function was told about 1 publish
    And the announcement carries the event id "story.published:" followed by the article's lineage

  Scenario: Publishing the same content again announces nothing more
    Given the editor publishes an article
    When the editor publishes the same article again without changes
    Then the notifications function was told about 1 publish

  Scenario: Publishing again after an unpublish is announced under the same event id so the function can dedupe it
    Given the editor publishes an article
    When the editor unpublishes the article and publishes it again
    Then the notifications function was told about 2 publishes
    And both announcements carry the same event id

  Scenario: A projection failure holds the announcement until the retry succeeds
    Given the site cannot write its pages
    When the editor publishes an article
    Then the publish is recorded but not live
    And the notifications function was told about 0 publishes
    When the site can write its pages again and the scheduled retry runs
    Then the notifications function was told about 1 publish

  Scenario: A retry that fails again announces nothing
    Given the site cannot write its pages
    And the editor publishes an article
    When the scheduled retry runs and fails
    Then the notifications function was told about 0 publishes

  Scenario: A site without the plugin invokes nothing and publishes normally
    Given a site whose notifications plugin is off
    When the editor publishes an article
    Then the publish succeeds
    And the notifications function was told about 0 publishes

  Scenario: A notifications problem never fails the publish
    Given invoking the notifications function is refused
    When the editor publishes an article
    Then the publish succeeds and the page is live
    And the problem is logged without its detail
    And the newsletter was still told about 1 publish

  Scenario: A bulk import must not alert
    When 5 articles are imported as drafts and the whole site is reprojected
    Then the notifications function was told about 0 publishes

  Scenario: Unpublishing and editing a live article announce nothing
    Given the editor publishes an article
    When the editor edits the live article and then unpublishes it
    Then the notifications function was told about 1 publish
