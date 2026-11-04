Feature: A shared Story link on the console's origin
  A share link opens on the same origin as the newsroom, at /api/share/<token>, and shows the Story in the website's public layout, which the newsroom's
  function draws. The route only asks the function and passes its answer on. Every response, a page, a redirect, a picture or the plain refusal, carries
  X-Robots-Tag noindex, Cache-Control no-store and Referrer-Policy no-referrer. A link that is unknown, expired, revoked, ended or malformed is the same
  plain "This link is not available" page with the same status, so a stranger cannot tell which. A signed-in link sends a visitor with no session to the
  newsroom's sign-in and back. Pictures load for a visitor with no sign-in through the link's own route, only when the function approved that picture
  for that token, only as images, and never as something a browser could run. The Share a draft dialog offers who can open it, what it shows and
  7, 30 or 90 days with 30 chosen, never a link that does not expire. These scenarios run the real route helpers and client against stand-ins.

  Scenario: Every share response carries the three privacy headers
    Given a share route answers a page, a redirect, a published notice and a refusal
    When their headers are read
    Then each one says noindex, no-store and no-referrer

  Scenario: Every way a link can fail is one and the same page
    Given the newsroom's function answers unknown, expired, revoked, malformed or nothing at all
    When the share route builds its response
    Then the status, headers and body are identical and say only that the link is not available

  Scenario: A signed-in link sends a visitor with no session to sign in
    Given the newsroom's function answers that this link needs a sign-in
    When the share route builds its response
    Then the visitor is redirected to the newsroom's sign-in page for that link and no draft is sent

  Scenario: A published Story's old link points at the published page
    Given the newsroom's function answers that the Story was published
    When the share route builds its response
    Then a plain page links to the published address, and only an https address is accepted

  Scenario: Pictures are served only when approved, only as images
    Given the newsroom's function approves one picture and refuses another
    When the media route builds its responses, including pages, scripts and failures standing in for pictures
    Then only the approved image is sent, with a sandboxing policy, and everything else is the plain refusal

  Scenario: The dialog offers 7, 30 and 90 days and never forever
    Given the Share a draft client in the newsroom
    When a link is made, listed and revoked
    Then the newsroom is asked with the chosen expiry, the version only when pinned, and a refusal is shown in its own words
