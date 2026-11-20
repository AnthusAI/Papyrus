Feature: Owners and agents see the account's pace, its blocked Stories, and can retry a failed post
  The announcements account status shows the spend against the budget, our own count of the posts the account sent this billing cycle, and a budget suggestion drawn from the
  site's own pace over the last two months. The pace is a suggestion and never a limit. A person can list the Stories that qualified and are waiting, each with its reason in
  words, and can try a failed Delivery again. Connecting the X account is a browser step: the command line prints where, and never accepts a secret.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On

  Scenario: The status says how many posts went out this cycle and what the site's pace suggests
    Given the account sent 2 X posts this cycle, each for a different Announcement
    When a person types "papyrus announcements account status"
    Then the announcement command succeeds
    And the status counts 2 posts this cycle
    And the status suggests "At your pace, about 1 posts and $0.20 per month"

  Scenario: A deleted post still counts, because X charged for it
    Given the account sent 1 X posts this cycle, each for a different Announcement
    And that post was deleted afterwards
    When a person types "papyrus announcements account status"
    Then the status counts 1 posts this cycle

  Scenario: A post from an earlier cycle is not counted this cycle
    Given the account sent 1 X posts in the cycle before this one
    When a person types "papyrus announcements account status"
    Then the status counts 0 posts this cycle

  Scenario: The suggestion waits for the prices
    Given the site has entered no prices
    When a person types "papyrus announcements account status"
    Then the announcement command succeeds
    And the status has no suggestion

  Scenario: Blocked Stories are listed with the reason
    Given announcements are paused
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And Caducus posts it for $0.20
    And the deliver side reads what Caducus recorded
    When a person types "papyrus announcements blocked"
    Then the announcement command succeeds
    And the blocked list has the Article with the words "Blocked: paused"

  Scenario: Nothing waiting is an empty list
    When a person types "papyrus announcements blocked"
    Then the announcement command succeeds
    And the blocked list is empty

  Scenario: A failed Delivery is tried again by a person
    Given a failed X Delivery
    When a person retries that Delivery
    Then the announcement command succeeds
    And the retried Delivery is ready and keeps its attempt in the log

  Scenario: An agent does not retry a failed post
    Given a failed X Delivery
    When an AI agent retries that Delivery
    Then the announcement command fails with "human_required"

  Scenario: Only a failed Delivery is retried
    Given a 5-star Article is published
    When a person retries that Delivery
    Then the announcement command fails with "constraint_conflict"

  Scenario: Retrying a Delivery that does not exist
    When a person types "papyrus announcements retry nothing#x#mom#g1"
    Then the announcement command fails with "not_found"

  Scenario: Connecting the account points at the browser
    Given the console address is "https://news.example.test/newsroom"
    When a person types "papyrus announcements account connect"
    Then the announcement command succeeds
    And the announcement answer's address is "https://news.example.test/newsroom/administration/announcements"

  Scenario: Without a console address nothing is guessed
    Given the console address is unknown
    When a person types "papyrus announcements account connect"
    Then the announcement command fails with "service_unavailable"
