Feature: Notifications send as the site, through the newsletter's identity and configuration set
  A site's notifications function sends from the SES identity and the configuration set papyrus-<site> that the site's
  newsletter sending stack already created, so one reputation and one pause cover both. Every message is tagged with the
  site, the kind and the delivery, so each consumer of the set's events knows its own mail and ignores the rest. A
  paused set is a failed delivery with a reason, public mail never leaves without the sender's postal address, and what
  SES later says about a message reaches the delivery log.

  Background:
    Given a site "alpha" with the notifications plugin and one operator

  Scenario: Mail is tagged and sent through the site's configuration set
    When the story "Rates held steady" is published in the "news" section
    And the email queue is played through the sender
    Then the email is tagged with the site "alpha", the kind "story.published" and its delivery
    And the site's configuration set is "papyrus-alpha"

  Scenario: A send on a paused configuration set is a failed delivery with a reason
    Given the site's configuration set is paused
    When the story "Rates held steady" is published in the "news" section
    And the email queue is played through the sender
    Then the site sent no mail
    And the delivery is "failed" because "sending is paused for configuration set papyrus-alpha"

  Scenario: Public mail is refused without a postal address
    Given the site has no postal address
    When the story "Rates held steady" is published in the "news" section
    And the delivery is marketing mail
    And the email queue is played through the sender
    Then the site sent no mail
    And the delivery is "failed" because "postal address missing"

  Scenario: Public mail carries the postal address in its footer
    Given the site has the postal address "1 Example Way"
    When the story "Rates held steady" is published in the "news" section
    And the delivery is marketing mail
    And the email queue is played through the sender
    Then the email footer shows "1 Example Way"

  Scenario Outline: What SES reports about a message reaches the delivery log
    Given the story "Rates held steady" was sent
    When SES reports "<event>" for the message
    Then the delivery is "<status>"

    Examples:
      | event               | status     |
      | Delivery            | delivered  |
      | Permanent bounce    | bounced    |
      | Transient bounce    | delayed    |
      | Complaint           | complained |

  Scenario: Events that are not this site's notification mail change nothing
    Given the story "Rates held steady" was sent
    When SES reports a bounce for the message tagged with another site
    And SES reports a bounce for a newsletter subscriber's message
    Then the delivery is "sent"

  Scenario: The newsletter ignores notification mail on the shared set
    When SES reports a permanent bounce for notification mail on the shared configuration set
    Then the newsletter function ignores the event

  Scenario: A site without the newsletter pauses on a rate alarm
    When the site's bounce rate alarm enters ALARM
    Then sending is turned off for the configuration set "papyrus-alpha"

  Scenario: A recovered alarm or another site's alarm pauses nothing
    When the site's bounce rate alarm returns to OK
    And another site's complaint rate alarm enters ALARM
    Then sending is not turned off
