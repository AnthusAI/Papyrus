Feature: X is one channel of an Announcement, and the channel's own rules decide whether it gets a Delivery
  Announcing on X is the most public thing a site does, so it is off until the owner turns it on, and the owner sets the bar. X is not a row shape of its own: when a Story's
  page goes live or its rating changes, the announce agent asks whether the Story qualifies on X, and if it does the Announcement is made together with its first Delivery
  for the channel x. A Story that qualifies nowhere leaves no row at all. A rating that reaches the floor later adds the X Delivery to the Announcement that already
  exists, and a second wake for the same Story finds both and makes nothing more. Under every setting a Story under three stars never qualifies, an unrated Story never
  qualifies, a model's prediction is not a rating, and a machine never supplies the five. Nothing here sends anything: these specs run the announce agent's decision over
  the real records, and X stays off everywhere until the owner says otherwise.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release

  Scenario: Nothing is announced until the owner turns announcements on
    Given the site never turned announcements on
    When a 5-star Article is published
    Then nothing is announced on X
    And the reason is "off"
    And the catalog holds no Announcement

  Scenario: Only the Stories that reach the bar get an X Delivery
    Given the site announces Articles rated 5 stars, in Dry run
    When a 4-star Article is published
    Then nothing is announced on X
    And the reason is "below_bar"
    And the catalog holds no Announcement

  Scenario: The Announcement is made together with its first Delivery
    Given the site announces Articles rated 5 stars, in Dry run
    When a person rates a Story 5 stars and it is published
    Then the catalog holds 1 Announcement and 1 Delivery
    And the Delivery is on the channel "x" for the account "mom"
    And the Announcement is linked to the Story

  Scenario: The bar cannot go below the quality floor
    When the owner sets the announcement minimum to 2 stars
    Then the announcement settings are refused with "Announcements can't go below your quality floor of 3 stars."

  Scenario: Unrated Stories never qualify
    Given the site announces Articles rated 3 stars, in Dry run
    When an unrated Article is published
    Then nothing is announced on X
    And the reason is "below_bar"

  Scenario: A model's prediction is not a rating
    Given the site announces Articles rated 3 stars, in Dry run
    When an unrated Article is published and a model predicts 5 stars for it
    Then nothing is announced on X
    And the catalog holds no Announcement

  Scenario: A five a machine gave is never announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a Story rated 5 stars by the machine "rating-agent" is published
    Then nothing is announced on X
    And the reason is "machine_five"

  Scenario: A five a person gave is announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a Story rated 5 stars by the person "ellie" is published
    Then the catalog holds 1 Announcement and 1 Delivery

  Scenario: Only the Story types the owner chose are announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a 5-star Post is published
    Then nothing is announced on X
    And the reason is "type_not_announced"

  Scenario: A section limit is respected
    Given the site announces Articles rated 5 stars in the "security" section, in Dry run
    When a 5-star Article in the "hardware" section is published
    Then nothing is announced on X
    And the reason is "section_not_announced"
    When a 5-star Article in the "security" section is published
    Then the X Delivery reads "Dry run: not sent"

  Scenario: A Story that is not published is not announced
    Given the site announces Articles rated 5 stars, in Dry run
    When a 5-star Article is saved as a draft
    Then nothing is announced on X
    And the catalog holds no Announcement

  Scenario: A retired Story is not announced
    Given the site announces Articles rated 5 stars, in Dry run
    And a retired 5-star Article
    When the announce agent wakes for the Article
    Then nothing is announced on X
    And the catalog holds no Announcement

  Scenario: A site with no connected account has no account to post from
    Given the site announces Articles rated 5 stars, in Dry run
    And no X account is connected to the site
    When a 5-star Article is published
    Then nothing is announced on X
    And the reason is "no_account"

  Scenario: A Story rated after it is published is added to the Announcement that already exists
    Given the site announces Articles rated 5 stars, in Dry run
    And a published 4-star Article that the announce agent already looked at
    And an Announcement for the Article that has an email Delivery
    When an editor rates the Article 5 stars
    And the announce agent wakes for the Article
    Then the catalog holds 1 Announcement and 2 Deliveries
    And the X Delivery reads "Dry run: not sent"
    And the run added the channel "x" to the Announcement that existed

  Scenario: A second wake for the same Story makes nothing more
    Given the site announces Articles rated 5 stars, in Dry run
    And a published 5-star Article that the announce agent already looked at
    When the announce agent wakes for the Article
    Then the catalog holds 1 Announcement and 1 Delivery
    And the model was asked once

  Scenario: A corrected version never announces again
    Given the site announces Articles rated 5 stars, in Dry run
    And an announced Article
    When the Article is announced again because a corrected version was published
    Then the catalog holds 1 Announcement and 1 Delivery

  Scenario: On needs the Automated label confirmed
    When the owner turns the mode On without confirming the Automated label
    Then the announcement settings are refused with "Confirm that the account shows X's Automated label before turning announcements on."

  Scenario: On needs a budget
    When the owner turns the mode On without a budget
    Then the announcement settings are refused with "Enter a budget per X billing cycle before turning announcements on."

  Scenario: A person must have reviewed the Story when the publication requires it
    Given the site announces Articles rated 5 stars, in Dry run
    And the publication wants a person's review of a Story before X announces it
    When a 5-star Article is published
    Then nothing is announced on X
    And the reason is "story_not_reviewed"

  Scenario: A rung that prepares nothing makes no Delivery
    Given the site announces Articles rated 5 stars, in Dry run
    And the announce agent is at the rung "observe"
    When a 5-star Article is published
    Then nothing is announced on X
    And the reason is "no_delivery"
    And the catalog holds no Announcement
