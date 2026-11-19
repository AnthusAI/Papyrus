Feature: A Story's page going live and its rating changing reach the announce agent durably, and a publish tells no one
  Two facts start an Announcement: a Story's page is live, and a Story's rating changed (PPY-e3bb2b, design section 13.3 change A). Both are changes to the Story's own
  record, so the Item change feed delivers them to the announce agent as wakes on the site's wake queue, and nothing else does. The record that marks "the page is live"
  is the Story's Item row entering the published stage: the publish writes that stage in the same update that makes the version the lineage's current one, so the feed
  sees it whoever published. A rating is made in place on the same record, so a rating change is a change of its star field. A publish writes only its own records, so
  its latency does not change; it no longer invokes the newsletter or the notifications function, and the best-effort call with its swallowed error is gone.

  A wake only says that something happened. The announce agent re-reads the Story as it is now (is its page live, what is its rating) and re-checks every list's rule and
  the site policy's rung before it decides anything. What it makes is one Announcement for the Story, whose once-only key is story-published and the Story, and one email
  Delivery for the every-item lists that carry it. A wake delivered twice, a republish, a rating changed again and a retry after a crash all find that Announcement and
  make no second one. The wake key makes a duplicate stream record one run; the once-only key is the second line of defence for the decision itself. This feature runs
  the shipped definition, the listener index written from it, the feed, the queue message and the worker over the real records; nothing is sent.

  Background:
    Given the site "sample" with its wake queue, its schedule group, its list settings and its announcement records
    And the every-item list "everything" with a minimum of 3 stars
    And the shipped announce agent is deployed with its wake queue and its listener index

  Scenario: The shipped announce agent is a listener of the page going live and of a rating change
    Then the announce agent is listed under "Item/stage_entered" and "Item/rated"

  Scenario: A publish wakes the announce agent once, from the Story's own record
    Given the Story "story-1" is a draft that nobody has rated
    When a person publishes the Story "story-1"
    Then the feed queue holds 1 wake for the agent "announce"
    And the feed queue's wake key is "announce|story-1|story-1-v3|stage_entered.published"

  Scenario: A publish whose first trigger fails is still announced once
    Given the Story "story-1" is live and rated 4 stars
    And the queue refuses the first wake it is given
    When a person publishes the Story "story-1"
    Then the batch reports the record as failed
    And the feed queue holds no wake
    And the catalog holds no Announcement
    When the queue accepts wakes again and the stream record is delivered again
    Then the batch reports nothing failed
    And the feed queue holds 1 wake for the agent "announce"
    When the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made the Announcement "story-published:story-1" because the page went live
    And the catalog holds 1 Announcements and 1 Deliveries
    When the stream record is delivered a second time after the queue's window
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent ran 1 time
    And the other wakes were duplicates and started nothing
    And the catalog holds 1 Announcements and 1 Deliveries

  Scenario: A rating change reaches the announce agent and makes an unrated Story eligible
    Given the Story "story-1" is a draft that nobody has rated
    When a person publishes the Story "story-1"
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made nothing and gave the reason code "no_list_carries_story"
    And the catalog holds no Announcement
    When a person rates the live Story "story-1" 4 stars
    Then the feed queue holds 2 wakes for the agent "announce"
    When the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made the Announcement "story-published:story-1" because the rating changed
    And the catalog holds 1 Announcements and 1 Deliveries

  Scenario: A rating change that leaves the Story under the list's bar makes nothing
    Given the Story "story-1" is live and rated 2 stars
    When a person rates the live Story "story-1" 1 stars
    Then the feed queue holds 1 wake for the agent "announce"
    When the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made nothing and gave the reason code "no_list_carries_story"
    And the catalog holds no Announcement

  Scenario: A rating changed again finds the Announcement already made
    Given the Story "story-1" is live and rated 4 stars
    When a person publishes the Story "story-1"
    And a person rates the live Story "story-1" 3 stars
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent ran 2 times
    And the announce agent's last run found the Announcement "story-published:story-1" already decided and made no other
    And the catalog holds 1 Announcements and 1 Deliveries

  Scenario: The agent decides from the Story as it is now, not from the wake
    Given the Story "story-1" is live and rated 4 stars
    When a person publishes the Story "story-1"
    And the Story "story-1" is unpublished before the agent wakes
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made nothing and gave the reason code "story_not_published"
    And the catalog holds no Announcement

  Scenario: The edit window of the channel gives the alert its release and lock times
    Given the Story "story-1" is live and rated 4 stars
    And the announcement settings give the email channel a window of 60 minutes with a lock lead of 10 minutes for a Story that went live
    When a person publishes the Story "story-1"
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the email Delivery is released at "2026-11-16T15:00:00Z" and locks at "2026-11-16T14:50:00Z", and so is the Announcement

  Scenario: At the observe rung the agent makes nothing and says why
    Given the Story "story-1" is live and rated 4 stars
    And the site's agent policy has the lists at the rung "observe"
    When a person publishes the Story "story-1"
    And the runner takes every wake on the queue and the announce agent runs each one
    Then the announce agent's last run made nothing and gave the reason code "no_list_carries_story"
    And the catalog holds no Announcement

  Scenario: A rating on a Story that is not published wakes nobody
    Given the Story "story-1" is a draft that nobody has rated
    When a person rates the draft Story "story-1" 4 stars
    Then the feed queue holds no wake

  Scenario: A publish writes only its own records and calls no other function
    Given a site whose content-actions function publishes pages, with the old call's environment still set
    When the editor publishes an article
    Then the publish succeeded and the page is live
    And the publish invoked neither the newsletter function nor the notifications function
    And the publish wrote only the Story's own records and its published copy

  Scenario: The best-effort call and its swallowed error are gone
    Then the content-actions function has no call to the newsletter or the notifications function and no swallowed error for one
    And the newsletter and notifications plugins give the content-actions function no name and no grant to invoke them
