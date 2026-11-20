Feature: A correction on X deletes the old post and records what the deletion cost
  A corrected re-send is a new Delivery that names the one it replaces, and its text is checked again. Where the channel can remove the old one, which X can, the old post is
  deleted as part of the correction and the deletion cost is written on the old Delivery, which stays superseded. Where it cannot, an email, nothing is deleted: the corrected
  Delivery goes out as the next one, in words that say what changed. The site's own X channel makes the deletion when the correction is made. The signed-in command line holds no rights on Caducus, so it writes the
  correction and the deliver side deletes the old post just before it sends the new one, so the account never carries both. Both ways delete a post once, and either is
  safe to repeat after a crash. Nothing here reaches X: the channel is a stand-in that behaves as Caducus's contract says.

  Background:
    Given a site whose quality floor is 3 stars
    And an X account "mom" is connected to the site
    And the announce agent may act without a person's release
    And the site announces Articles rated 5 stars with a budget of $10.00, in Dry run
    And the mode is On
    And a 5-star Article is published
    And the X Delivery was sent and Caducus posted it for $0.20

  Scenario: The old post is deleted as part of the correction and its cost is recorded on the old Delivery
    When the person "ada" corrects the X Delivery with the words "A look at secrets, corrected." through the site's own X channel
    Then the post was deleted at X once
    And generation 1 of the X Delivery is superseded by generation 2
    And generation 1 of the X Delivery has the cost 0.210
    And generation 2 of the X Delivery has these words in S3 "A look at secrets, corrected."
    And generation 2 of the X Delivery is "Ready"

  Scenario: The signed-in command line writes the correction and leaves the post for the deliver side
    When the person "ada" corrects the X Delivery with the words "A look at secrets, corrected." from the signed-in command line
    Then no post was deleted
    And generation 1 of the X Delivery is superseded by generation 2

  Scenario: The deliver side deletes the old post before it sends the new one
    Given the person "ada" corrected the X Delivery with the words "A look at secrets, corrected." from the signed-in command line
    When the deliver side sends the X Delivery
    Then the post was deleted at X once
    And the old post was deleted before the new event was handed over
    And generation 1 of the X Delivery has the cost 0.210

  Scenario: A second try after a crash deletes nothing twice
    Given the person "ada" corrected the X Delivery with the words "A look at secrets, corrected." from the signed-in command line
    And the channel deleted the old post but the old Delivery was not written
    When the deliver side sends the X Delivery
    Then the post was deleted at X once
    And generation 1 of the X Delivery has the cost 0.210

  Scenario: Correcting twice with the same words deletes once
    Given the person "ada" corrected the X Delivery with the words "A look at secrets, corrected." through the site's own X channel
    When the person "ada" corrects the X Delivery again with the words "A look at secrets, corrected." through the site's own X channel
    Then the post was deleted at X once
    And the live Delivery of the X channel is generation 2

  Scenario: A correction of an email is not deleted anywhere
    Given an email Delivery on the same Announcement was sent
    When the person "ada" corrects the email Delivery with the words "Corrected: the first version had an error." through the site's own X channel
    Then the post was deleted at X 0 times
    And the email Delivery generation 1 is superseded by generation 2
    And the live Delivery of the email channel is generation 2

  Scenario: A correction that fails its checks deletes nothing
    When the person "ada" corrects the X Delivery with the words "The first proof ever that a system can keep a secret." through the site's own X channel and the fact check supports nothing
    Then the correction is refused as "checks_failed" saying "This claim is not in the Story"
    And no post was deleted
    And the live Delivery of the X channel is generation 1
