Feature: An editor reviews References by voice
  A signed-in editor reviews the newsroom's unrated References one at a time. Alexa reads each one's title, where it is from, its
  subtitle and summary, and the Echo Show shows it with Accept, Reject and Skip buttons. The editor says accept, or reject and why,
  or skip; the answer is recorded exactly as the web newsroom records it, as the editor's own human vote, so it trains the site's
  Cyclotron. There are two lists: best bets (the Cyclotron's P(accept), highest first) and needs my help (the References it is least
  sure about). These scenarios run the real intent handlers against a fake newsroom; nothing is deployed and no account is used.

  Scenario: The two lists have the newsroom's own order
    Given unrated References with different predictions, and one with none
    Then best bets puts the highest P(accept) first and counts no prediction as a coin toss
    And needs my help puts the guesses closest to a coin toss first

  Scenario: Reviewing the best bets one by one
    Given a linked editor on an Echo Show
    When they say "review the best bets" and then accept the first one and reject the second because it's off topic
    Then each Reference is read and shown with its place in the list
    And each answer is recorded under the editor's own sign-in with their name, the Cyclotron decision it answers, and for a rejection the reason in their words and its reason code
    And the next Reference follows each answer, with a short prompt once the full one has been heard

  Scenario: A rejection always has a reason
    Given a linked editor reviewing a Reference
    When they say just "reject"
    Then Alexa asks why and records nothing until they answer "because ..."
    And a stray "because ..." outside that question checks what they meant

  Scenario: Starting without naming a list
    When a linked editor says "show me references"
    Then the review starts with what needs their help and says best bets is a word away

  Scenario: Moving around without losing the place
    Given a linked editor reviewing the best bets
    When they skip, say next, accept, undo, repeat and go back
    Then skip and next move on without an answer, undo reopens the last answer and reads that Reference again, and repeat and previous read again

  Scenario: Asking about the Reference under review
    Given a linked editor reviewing the best bets
    When they ask how many are left, why this one, who published it, for more, for help, or to send it to their phone, or say accept all
    Then each question gets a plain answer and the same short prompt, the link goes to the Alexa app, and accept all is kindly refused

  Scenario: Why a Reference needs help
    Given a linked editor reviewing what needs their help
    When they ask why this one
    Then Alexa says the Cyclotron's guess in percent and that it is close to a coin toss

  Scenario: The buttons on the card
    Given a linked editor reviewing on an Echo Show
    When they touch Accept, Reject and Skip
    Then each does what the word does, and Reject still asks why

  Scenario: The end of a list
    Given a short list
    When the editor answers the last Reference
    Then Alexa says the round is over and offers the other list, and an empty newsroom says nothing is waiting

  Scenario: A long list
    Given more unrated References than one session carries
    Then the editor hears how many are waiting in all and their place among them

  Scenario: Not linked, or not an editor
    When someone who has not linked their account asks to review
    Then Alexa asks them to link and sends a LinkAccount card, which an Echo Show shows as a QR code
    And a linked reader who is not an editor hears that review is for editors

  Scenario: A vote the newsroom does not take
    When the newsroom refuses the sign-in or cannot be reached while recording an answer
    Then nothing is recorded and the editor is told so, with a way forward

  Scenario: Review words outside a review, the fallback during one, and stopping
    Then accept outside a review says how to start one, a misheard answer during a review gets the short choices instead of the headlines, and stopping says unanswered References will still be waiting

  Scenario: A linked editor opens the skill
    When a linked editor opens the skill
    Then they are offered needs my help, best bets and headlines

  Scenario: The newsroom is read and written with the editor's own token
    Then the client reads the corpus's unrated feed index, each Reference's preview, curation card and current Cyclotron decision, and votes through reviewReferenceCuration with the editor's access token
    And an AppSync authorization error is a refusal, never a crash
