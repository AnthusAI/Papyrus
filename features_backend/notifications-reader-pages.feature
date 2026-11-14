Feature: Notification pages for readers, on the site
  A reader subscribes to a site's notifications, confirms, and manages what they get on real pages of the site, in its own header,
  theme and footer, in light and dark. The pages live under /notifications/ and are never an /api address: the machine routes
  only redirect to them. The pages are noindex, are not in any sitemap, feed or llms.txt, have no Markdown twin, and work under a
  strict content security policy, so the only scripts are external files. Every choice is a button, never a dropdown; every state
  is said in words as well as shown with a mark; icons are Lucide and fills are flat, with no borders. A site that does not enable
  the notifications plugin gets none of it.

  Scenario: The pages exist only when the plugin is enabled
    Given a projected site with the notifications plugin enabled
    Then the site has the notifications pages "index", "confirm", "confirmed", "preferences", "unsubscribe", "unsubscribed" and "expired"
    And the subscribe page is at "notifications/index.html"
    Given a projected site with no notifications plugin
    Then the site has no page under "notifications/"
    And the site has no notifications scripts

  Scenario: The pages are real pages of the site that nobody is asked to find or index
    Given a projected site with the notifications plugin enabled
    Then every notifications page has the site's header, stylesheet and footer
    And every notifications page is noindex and sends the same-origin referrer
    And no notifications page is in the sitemap, the feeds, llms.txt or a Markdown twin
    And no notifications page links to an "/api/" address

  Scenario: The pages work under a strict content security policy
    Given a projected site with the notifications plugin enabled
    Then every notifications page loads its scripts from external files and has no inline script or style
    And only the subscribe page loads the web component

  Scenario: Buttons, Lucide icons and flat fills
    Given a projected site with the notifications plugin enabled
    Then no notifications page has a dropdown
    And every notifications button carries a Lucide icon
    And the notifications stylesheet rules draw no borders

  Scenario: Subscribing on the site
    Given a site with notifications on that offers one list
    When a reader opens its notifications page and enters an address
    Then the page says to check their email, in the site's own design
    And the subscription request goes to the site's own subscribe address and not to a page address

  Scenario: Choosing among several lists while subscribing
    Given a site with notifications on that offers two lists
    When a reader opens its notifications page and enters an address
    Then each list is a button that says Off until it is pressed
    And pressing Subscribe without choosing a list asks them to choose at least one

  Scenario: The form shows the site's own consent wording, which is what the server records
    Given a site with notifications on that offers one list
    When a reader opens its notifications page and enters an address
    Then the form shows exactly the site's consent wording
    And the subscription request carries that wording

  Scenario: Too many signups from one network are said in words
    Given a site with notifications on that offers one list
    When the service answers that the reader's network should slow down
    Then the subscribe page says in words to try again later

  Scenario: The service cannot be reached
    Given a site with notifications on that offers one list
    When the service answers that notifications are not available
    Then the subscribe page says in words that notifications are not available right now

  Scenario: Managing
    Given a confirmed subscriber follows the manage link
    When they turn new-story email off and save
    Then each list on the page says On or Off in words and with a bell mark
    And the page confirms in words that the new-story email is off

  Scenario: A bad link
    When someone opens a manage link that is no good
    Then they land on the site's expired page, not an /api address

  Scenario: The service cannot be reached from a manage link
    Given a confirmed subscriber follows the manage link
    When the service answers that notifications are not available
    Then the page says in words that notifications are not available right now
    And the reader is not sent to the expired page

  Scenario: Deleting your data asks first
    Given a confirmed subscriber follows the manage link
    When they ask to delete their data
    Then the page asks them to confirm and offers a way back

  Scenario: Sites under a base path keep the pages under it
    Given a projected site under the base path "/posts" with the notifications plugin enabled
    Then the expired page links back to "/posts/notifications/"

  Scenario: Disabling the plugin lets the next projection remove the pages
    Given a projected site with the notifications plugin enabled
    Then the projector owns every notifications page
    And a reconcile treats "notifications/" as a plugin page prefix
