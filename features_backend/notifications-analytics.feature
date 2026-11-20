Feature: Subscription and notification analytics events
  A site with a Google Analytics 4 measurement id learns which pages convert readers. The subscribe form and the manage pages send a
  small, fixed set of events from the page, through the site's own gtag, so Consent Mode decides what leaves the browser: a reader who
  accepted analytics is measured, a reader who declined sends only the cookieless pings Consent Mode allows, and the script stores
  nothing either way. The server never sends an analytics event, because it has neither a client id nor the reader's consent choice.
  The events are subscribe_start, subscribe_submitted, subscribe_confirmed, preferences_changed, unsubscribe and subscribe_error, with
  only the parameters kind (the list ids), form (the signup placement) and page_type. No address, token or query string is ever sent,
  and every event records the page's address without its query. There is no issue_open event: opening an email needs a tracking
  pixel, which the email renderer forbids, so visits to the archive are measured by their own page views instead. A site without a
  measurement id loads no event script, and every page works the same when analytics is blocked.

  Scenario: A site without a measurement id loads no event script
    Given a projected site with the notifications plugin enabled
    Then no notifications page loads the analytics event script

  Scenario: A site with a measurement id loads the event script first, from an external file
    Given a projected site with the notifications plugin and a measurement id
    Then every notifications page loads the analytics event script before the pages script
    And the event script comes after the Consent Mode defaults
    And the notifications pages have no inline script beyond the chrome's

  Scenario: A staging build counts nobody
    Given a projected staging site with the notifications plugin and a measurement id
    Then no notifications page loads the analytics event script

  Scenario: Consent given
    Given a projected site with the notifications plugin and a measurement id
    And a reader who accepted analytics
    When they submit the subscribe form for the weekly list placed as "footer"
    Then subscribe_start and subscribe_submitted are sent with kind "weekly", form "footer" and page_type "subscribe"
    And no event carries an address

  Scenario: Consent denied
    Given a projected site with the notifications plugin and a measurement id
    And a reader who declined analytics
    When they submit the subscribe form for the weekly list placed as "footer"
    Then the events go only through gtag, where Consent Mode makes them cookieless pings
    And nothing is written to a cookie or to browser storage
    And no event sets a client id or a user id

  Scenario: Starting a subscription is counted once
    Given a projected site with the notifications plugin and a measurement id
    When a reader focuses the subscribe form twice and then submits it
    Then subscribe_start is sent once

  Scenario: A failed subscription
    Given a projected site with the notifications plugin and a measurement id
    When a reader submits the subscribe form and the service asks them to slow down
    Then subscribe_error is sent with form "notifications" and page_type "subscribe"
    And subscribe_submitted is not sent

  Scenario: No token in the event
    Given a projected site with the notifications plugin and a measurement id
    When a reader lands on a confirm link that carries a token, a list and a message
    Then subscribe_confirmed is sent with kind "stories" and page_type "confirmed"
    And the recorded page location is the page address with no query string
    And no parameter of any event contains the token

  Scenario: Confirmed once
    Given a projected site with the notifications plugin and a measurement id
    When the confirmed page is reloaded
    Then subscribe_confirmed is not sent a second time

  Scenario: Returning to the confirmed page with the back button
    Given a projected site with the notifications plugin and a measurement id
    When the confirmed page is reached with the back button
    Then subscribe_confirmed is not sent a second time

  Scenario: Changing what they get
    Given a projected site with the notifications plugin and a measurement id
    When a reader saves their choices and lands on the manage page
    Then preferences_changed is sent with kind "stories" and page_type "preferences"

  Scenario: Unsubscribe
    Given a projected site with the notifications plugin and a measurement id
    When a reader lands on the unsubscribed page
    Then unsubscribe is sent with kind "stories" and page_type "unsubscribed"

  Scenario: Unsubscribing from everything on the manage page
    Given a projected site with the notifications plugin and a measurement id
    When a reader lands on the manage page after unsubscribing from everything
    Then unsubscribe is sent with kind "all" and page_type "preferences"

  Scenario: The pages work when analytics is blocked
    Given a projected site with the notifications plugin and a measurement id
    And analytics is blocked in the reader's browser
    When a reader lands on the unsubscribed page
    Then the page still names what they unsubscribed from and offers the manage link
    And no analytics event is sent

  Scenario: The service is down
    Given a projected site with the notifications plugin and a measurement id
    When a reader opens a manage link while the service answers that notifications are not available
    Then subscribe_error is sent with page_type "preferences"

  Scenario: Only the named events and parameters can be sent
    Given a projected site with the notifications plugin and a measurement id
    When the page asks to send an event that is not one of the six, and one of them with an address, a token and an extra parameter
    Then only the allowed event is sent and only with its allowed parameters

  Scenario: No issue_open event
    Given a projected site with the notifications plugin and a measurement id
    Then the notifications scripts contain no issue_open event and no tracking pixel
