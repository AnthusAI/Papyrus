Feature: An email to the newsroom is handled according to what the sender wrote
  An authorized person can mail a link, a paper or a question to the newsroom's address, and can answer the
  receipt Papyrus sends back. Papyrus reads the message itself to decide what to do with it: a bare link is
  filed as a Reference without calling a model, a message that needs reading is handed to the email agent,
  and an answer to a receipt continues the earlier submission instead of starting a new one. Only the words
  the sender typed count, never the earlier mail their program quoted underneath.

  Scenario Outline: A first email is routed by its links, attachments and prose
    Given a first email to the newsroom with <links> links, <papers> attached papers and <prose>
    When Papyrus decides how to handle the email
    Then Papyrus decides the email is to be <handling>

    Examples:
      | links | papers | prose             | handling                                 |
      | 1     | 0      | no prose          | filed directly as a Reference            |
      | 1     | 0      | a short note      | filed directly as a Reference            |
      | 1     | 0      | a long commentary | handed to the email agent                |
      | 3     | 0      | no prose          | handed to the email agent                |
      | 0     | 1      | no prose          | filed directly as an attached paper      |
      | 0     | 1      | a long commentary | handed to the email agent                |
      | 0     | 2      | no prose          | handed to the email agent                |
      | 1     | 1      | no prose          | handed to the email agent                |
      | 0     | 0      | a long commentary | treated as a submission with no sources  |

  Scenario Outline: An answer to a receipt is recognised by the mail headers the sender's program sets
    Given the receipt for submission "message-email-submission-0123456789abcdef0123" was mailed from "newsroom.example.org"
    And an answer whose "<header>" header is "<value>"
    When Papyrus decides how to handle the email
    Then the email continues submission "<continues>"

    Examples:
      | header      | value                                                                           | continues                                     |
      | In-Reply-To | <message-email-submission-0123456789abcdef0123@newsroom.example.org>            | message-email-submission-0123456789abcdef0123 |
      | References  | <other@mail.example> <message-email-submission-0123456789abcdef0123@newsroom.example.org> | message-email-submission-0123456789abcdef0123 |
      | In-Reply-To | <unrelated-thread@mail.example>                                                 | nothing                                       |

  Scenario Outline: An answer to a receipt is routed by what the sender added
    Given an answer to a receipt in which the sender typed "<typed>" above the quoted receipt
    And the answer carries <papers> attached papers
    When Papyrus decides how to handle the email
    Then Papyrus decides the email is to be <handling>

    Examples:
      | typed                                   | papers | handling                                      |
      | Which of these is the most cited?       | 0      | continued as a conversation with the agent    |
      | Here is the full text, what do you think | 1      | continued as a conversation with the agent    |
      |                                         | 1      | filed as the paper for the earlier submission |
      |                                         | 0      | ignored as an empty answer                    |

  Scenario Outline: Text the sender's mail program quoted is not read as the sender's words
    Given an answer to a receipt in which the sender typed "Please add this one too" above a quotation that begins "<quotation>"
    When Papyrus reads what the sender wrote
    Then the sender's words are exactly "Please add this one too"

    Examples:
      | quotation                                         |
      | On Tue, 3 Nov 2026 at 09:14, Papyrus wrote:       |
      | -----Original Message-----                        |
      | From: Papyrus <newsroom@newsroom.example.org>     |
      | > We filed 2 References from your message.        |
