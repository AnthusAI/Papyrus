Feature: An announcement is posted through Caducus's x channel and recorded, once
  The site's X account is a Caducus recipient of class broadcast. When the deliver side sends an X Delivery it hands Caducus one story.announce event naming the account; Caducus
  queues it on the site's x queue and the x queue's consumer posts it, claims it before the request, records the post id and what the call cost, and charges the account's budget. Papyrus
  learns the result only by reading Caducus's record. A post whose outcome is unknown is never repeated blindly: the account's recent posts are read first. Taking the post down is
  Caducus's delete, never blocked by the pause or the budget. These specs run Caducus's own router, delivery log and x channel against a fake X server on localhost, so the whole
  path is real except X itself, and nothing is ever posted to the real X.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars, in Dry run
    And the site's X channel is the released Caducus, with X itself a fake server on localhost

  Scenario: The site's own notification kinds register the announcement as a broadcast on X
    Then the kind story.announce is a broadcast to the channel x in the site's own kinds

  Scenario: Sending hands Caducus one event and the queue's consumer posts it
    Given the mode is On
    And a 5-star Article is published
    When the deliver side sends the X Delivery
    Then the X Delivery reads "Sending"
    And the x queue holds 1 message
    And the fake X server holds 0 posts
    And the account key Caducus posts to is CHANNELACCT#x# followed by the connected account's id

  Scenario: The post is made, recorded with its id and cost, and charged to the budget
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    When the x queue runs
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Sent"
    And the X Delivery has a post id and a cost of 0.200
    And the account's spend this cycle is $0.200
    And the fake X server holds 1 post
    And every request to the fake X server carried the account's access token

  Scenario: Sending the same Delivery again posts once
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And the x queue runs
    And the deliver side reads what Caducus recorded
    When the deliver side sends the X Delivery
    Then the deliver side says the Delivery is not waiting to be sent
    And the fake X server holds 1 post

  Scenario: A pause refuses the post before any request is made
    Given the mode is On
    And announcements are paused
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    When the x queue runs
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Blocked: paused"
    And the fake X server holds 0 posts
    And the account's spend this cycle is $0

  Scenario: A refusal by X is kept in X's own words
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And X refuses the next post with "Forbidden"
    When the x queue runs
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Failed"
    And the Delivery's last attempt says "Refused" with the code "403 Forbidden"

  Scenario: An unknown outcome is checked before it is tried again
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And X accepts the post but its answer never arrives
    When the x queue runs
    Then the message goes back to the queue
    When the x queue runs again
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Sent"
    And the account's recent posts were read once and none was posted again
    And the fake X server holds 1 post

  Scenario: X asks us to wait and the post goes out afterwards
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And X answers that the rate limit is reached until 600 seconds from now
    When the x queue runs
    And the deliver side reads what Caducus recorded
    Then the X Delivery reads "Sent"
    And Caducus waited about 600 seconds
    And the fake X server holds 1 post

  Scenario: Withdrawing deletes the post through Caducus and records who did it
    Given the mode is On
    And a 5-star Article is published
    And the deliver side sends the X Delivery
    And the x queue runs
    And the deliver side reads what Caducus recorded
    When the person "ada" withdraws the X Delivery through the site's own X channel
    Then the fake X server holds 0 posts
    And the X Delivery's history says it was withdrawn by "ada"
    And the X Delivery's cost is 0.210

  Scenario: An announcement for an account that is not the connected one is refused
    When Caducus is handed an announcement for an account that is not the connected one
    Then the hand-over is refused saying "no audience"
    And nothing was queued on the x queue

  Scenario: A site turned On without a Caducus x channel refuses to run
    Given the mode is On
    And the site is On and has no Caducus x channel
    When the deliver side is built for the site
    Then the site refuses with ChannelNotAvailable saying "no Caducus x channel"

  Scenario: A site that is not On needs no channel
    Given the site is On and has no Caducus x channel
    When the deliver side is built for the site
    Then the site has no deliver side and nothing to send
