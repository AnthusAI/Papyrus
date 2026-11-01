Feature: A site writes about the items its monitors find
  A Papyrus site can have monitors: collectors that watch a source (a news feed, a model hub, an inbox) and deliver what they find as
  pending References in the site's knowledge corpus, each with a provenance record that names the monitor. Most of what they deliver
  is never written about. This feature picks the few most worth a story and drafts one short story for each, for any monitor, with no
  code that knows a source. The relevance Cyclotron has already judged each delivered item, and its verdict (a label and a score)
  is the only ranking signal that every source has. A source's own numbers, such as likes or downloads, only break a tie between
  items the Cyclotron scored the same. For each chosen item the command reads the linked page (HTML, or a PDF such as a decision or a paper, directly or through a short page that links to it), asks the repository's default model
  (GPT-6 Luna) once for a story written as single sentences, and runs the same deterministic citation check as Cited Trends: every
  sentence must cite the source, and every number and date in it must appear in what the source says. A draft that fails is not
  filed. A draft that passes is filed as an idea at the idea stage, proposed by AI, with the source's address in its
  body and the monitor named as its provenance. A Reference is never drafted twice. Every undrafted item is considered, however old: there is no default window, and an older item is only ranked lower, by a freshness weight learned from how quickly the site's editors accepted items. Nothing is approved, moved or published by the run;
  one soft review request covers the batch. Turning a draft into a story is a later step.

  Background:
    Given a site "example-site" with the sections "Analysis" and "Tools"

  Scenario: Items from every kind of monitor are read, whatever their source
    Given the monitors of the site delivered these items:
      | monitor     | title                     | verdict      | days ago |
      | hn          | A tool that checks claims | include 0.80 | 1        |
      | huggingface | A small coding model      | include 0.70 | 1        |
      | email       | A reader's tip            | include 0.60 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then 3 stories are drafted
    And the drafted stories name the monitors "hn", "huggingface" and "email"

  Scenario: A site whose References live in a differently named corpus is read from that corpus
    Given the site keeps its References in the knowledge corpus "ai-ml-research"
    And the monitors of the site delivered these items:
      | monitor | title                  | verdict      | days ago |
      | hn      | A paper worth a story  | include 0.80 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories from the corpus "ai-ml-research"
    Then the stories drafted are "A paper worth a story"

  Scenario: Without a corpus key the site's own key names the corpus, so another corpus is not read
    Given the site keeps its References in the knowledge corpus "ai-ml-research"
    And the monitors of the site delivered these items:
      | monitor | title                  | verdict      | days ago |
      | hn      | A paper worth a story  | include 0.80 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then 0 stories are drafted

  Scenario: Only current, accepted items are candidates, monitored or not
    Given the monitors of the site delivered these items:
      | monitor | title                  | verdict       | days ago | status   |
      | hn      | Pending and recent     | include 0.80  | 1        | pending  |
      | hn      | Accepted and recent    | include 0.70  | 2        | accepted |
      | hn      | Rejected by an editor  | include 0.99  | 1        | rejected |
      | hn      | Old but still wanted   | include 0.99  | 30       | accepted |
      | hn      | Judged not relevant    | exclude 0.05  | 1        | accepted |
    And a Reference that no monitor delivered arrived 1 day ago
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then the three stories drafted are "Old but still wanted", "Accepted and recent" and "Added by hand"
    And the run record counts 1 item judged not relevant
    And the run record counts 1 pending item that was not read because it was not accepted

  Scenario: Pending items are not written about by default, however confident the Cyclotron is
    Given the monitors of the site delivered these items:
      | monitor | title                | verdict      | days ago | status  |
      | hn      | Sure but unreviewed  | include 0.99 | 1        | pending |
      | hn      | Also unreviewed      | include 0.95 | 2        | pending |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then 0 stories are drafted
    And the run record counts 2 pending items that were not read because they were not accepted

  Scenario: An item the Cyclotron accepted automatically is drafted like one an editor accepted
    Given the monitors of the site delivered these items:
      | monitor | title                 | verdict      | days ago | status   | accepted by    |
      | hn      | Accepted by the system | include 0.97 | 3        | accepted | auto:cyclotron |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then the stories drafted are "Accepted by the system"

  Scenario: Pending items are never candidates, even when the status option names them
    Given the monitors of the site delivered these items:
      | monitor | title                  | verdict      | days ago | status   |
      | hn      | Pending and recent     | include 0.80 | 1        | pending  |
      | hn      | Accepted and recent    | include 0.70 | 2        | accepted |
      | hn      | Rejected by an editor  | include 0.99 | 1        | rejected |
    And every linked page can be read
    When the operator drafts monitor stories reading the statuses "accepted,pending"
    Then the stories drafted are "Accepted and recent"
    And the run record counts 0 pending items that were not read because they were not accepted

  Scenario: There is no default window, so an old, highly relevant item is still considered
    Given the monitors of the site delivered these items:
      | monitor | title                | verdict      | days ago |
      | hn      | A year old and great | include 0.99 | 400      |
      | hn      | New and fine         | include 0.60 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 1
    Then the stories drafted are "A year old and great"
    And the run record has no window

  Scenario: A window is only an optional filter
    Given the monitors of the site delivered these items:
      | monitor | title                | verdict      | days ago |
      | hn      | A year old and great | include 0.99 | 400      |
      | hn      | New and fine         | include 0.60 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 1 and a window of "7d"
    Then the stories drafted are "New and fine"

  Scenario: Freshness is learned from how long the editors took to accept items
    Given the monitors of the site delivered these items:
      | monitor | title                | verdict      | days ago | status   | days to accept |
      | hn      | Accepted 1           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 2           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 3           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 4           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 5           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 6           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 7           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 8           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 9           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 10          | include 0.10 | 20       | accepted | 2              |
      | hn      | Old and relevant     | include 0.90 | 40       | accepted |                |
      | hn      | Fresh and decent     | include 0.60 | 1        | accepted |                |
    And every linked page can be read
    When the operator drafts monitor stories as a dry run with a limit of 1
    Then the stories drafted are "Fresh and decent"
    And the run record learned a freshness of 2.885 days from 10 examples

  Scenario: With too few accepted examples nothing is guessed and the score alone ranks
    Given the monitors of the site delivered these items:
      | monitor | title                | verdict      | days ago | status   | days to accept |
      | hn      | Accepted 1           | include 0.10 | 20       | accepted | 2              |
      | hn      | Accepted 2           | include 0.10 | 20       | accepted | 2              |
      | hn      | Old and relevant     | include 0.90 | 40       | accepted |                |
      | hn      | Fresh and decent     | include 0.60 | 1        | accepted |                |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 1
    Then the stories drafted are "Old and relevant"
    And the run record has no freshness weight

  Scenario: The Cyclotron's score ranks the items and only the best few are drafted
    Given the monitors of the site delivered these items:
      | monitor | title        | verdict      | days ago |
      | hn      | Third best   | include 0.60 | 1        |
      | hn      | Best         | include 0.95 | 3        |
      | hn      | Fourth best  | include 0.30 | 1        |
      | hn      | Second best  | include 0.80 | 2        |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 2
    Then the stories drafted are "Best" and "Second best"
    And the model was asked exactly 2 times

  Scenario: An item the Cyclotron did not judge ranks after the items it scored
    Given the monitors of the site delivered these items:
      | monitor | title            | verdict      | days ago |
      | hn      | Not yet judged   |              | 1        |
      | hn      | Scored low       | include 0.20 | 2        |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 1
    Then the stories drafted are "Scored low"

  Scenario: A source's own numbers only break a tie in the Cyclotron's score
    Given the monitors of the site delivered these items:
      | monitor     | title                    | verdict      | days ago | likes |
      | huggingface | Many likes, lower score  | include 0.70 | 1        | 9000  |
      | huggingface | Few likes, higher score  | include 0.90 | 1        | 3     |
      | huggingface | Some likes, same score   | include 0.90 | 1        | 40    |
    And every linked page can be read
    When the operator drafts monitor stories with a limit of 2
    Then the stories drafted are "Some likes, same score" and "Few likes, higher score"

  Scenario: The story is written from the linked page
    Given the monitors of the site delivered these items:
      | monitor | title                     | verdict      | days ago |
      | hn      | A tool that checks claims | include 0.80 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then the model was shown the text of the linked page as the source
    And the model was told the source is from the "hn" monitor and was not shown the relevance score

  Scenario: A page that cannot be read leaves the story to the details the monitor stored
    Given the monitors of the site delivered these items:
      | monitor | title                     | verdict      | days ago | summary                                                                                                  |
      | hn      | A tool that checks claims | include 0.80 | 1        | Foo is an open tool that checks claims against sources. It was released on 2026-10-20 and has 42 contributors. |
    And the linked page of "A tool that checks claims" cannot be read
    When the operator drafts monitor stories with the default limit
    Then 1 story is drafted from the stored details

  Scenario: A source that is a PDF document is read as text and drafted with citations
    Given the monitors of the site delivered these items:
      | monitor | title                  | verdict      | days ago |
      | hn      | A decision in PDF form | include 0.80 | 1        |
    And the linked address of "A decision in PDF form" is a PDF document
    When the operator drafts monitor stories with the default limit
    Then 1 story is drafted
    And the model was shown the text of the PDF as the source

  Scenario: A short page that links to the PDF of the same document leads to that PDF
    Given the monitors of the site delivered these items:
      | monitor | title                 | verdict      | days ago |
      | hn      | A decision on a page  | include 0.80 | 1        |
    And the linked page of "A decision on a page" is a short page that links to its PDF
    When the operator drafts monitor stories with the default limit
    Then 1 story is drafted
    And the model was shown the text of the PDF as the source

  Scenario: A PDF that cannot be read is skipped like any unreadable source
    Given the monitors of the site delivered these items:
      | monitor | title             | verdict      | days ago |
      | hn      | A broken document | include 0.80 | 1        |
    And the linked address of "A broken document" is a PDF that cannot be read
    When the operator drafts monitor stories with the default limit
    Then the model was asked exactly 0 times
    And "A broken document" is skipped because there is no source text

  Scenario: An item with nothing but a title is skipped without asking the model
    Given the monitors of the site delivered these items:
      | monitor | title             | verdict      | days ago |
      | hn      | Only a headline   | include 0.80 | 1        |
    And the linked page of "Only a headline" cannot be read
    When the operator drafts monitor stories with the default limit
    Then the model was asked exactly 0 times
    And "Only a headline" is skipped because there is no source text

  Scenario: A sentence that does not cite the source fails the citation check and nothing is filed
    Given the monitors of the site delivered these items:
      | monitor | title        | verdict      | days ago |
      | hn      | Uncited      | include 0.80 | 1        |
    And every linked page can be read
    And the model writes a story for "Uncited" whose dek cites nothing
    When the operator drafts monitor stories and files them as ideas with a limit of 1
    Then no idea is filed
    And the run record says the dek failed with "no_citation"

  Scenario Outline: A sentence that states something the source does not say fails the citation check
    Given the monitors of the site delivered these items:
      | monitor | title        | verdict      | days ago |
      | hn      | Unsupported  | include 0.80 | 1        |
    And every linked page can be read
    And the model writes a story for "Unsupported" with the body sentence "<sentence>"
    When the operator drafts monitor stories and files them as ideas with a limit of 1
    Then no idea is filed
    And the run record says a sentence failed with "<reason>"

    Examples:
      | sentence                                     | reason                          |
      | The tool has 7 users.                        | number_not_in_cited_signals     |
      | The tool shipped on 2026-01-01.              | number_not_in_cited_signals     |
      | It was made for the news desk.               | banned_word                     |
      | It is new. It is fast.                       | several_sentences_in_one_entry  |

  Scenario: A draft that fails the check is replaced by the next item
    Given the monitors of the site delivered these items:
      | monitor | title            | verdict      | days ago |
      | hn      | Fails the check  | include 0.90 | 1        |
      | hn      | Passes the check | include 0.80 | 1        |
    And every linked page can be read
    And the model writes a story for "Fails the check" whose dek cites nothing
    When the operator drafts monitor stories and files them as ideas with a limit of 1
    Then the ideas filed are for "Passes the check"

  Scenario: A passing story is filed as an idea that cites its source and names the monitor
    Given the monitors of the site delivered these items:
      | monitor     | title                     | verdict      | days ago |
      | huggingface | A tool that checks claims | include 0.80 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories and files them as ideas with a limit of 1
    Then 1 idea is filed and it is proposed by AI and still at the idea stage
    And the idea body cites the address of the item
    And the idea evidence names the "huggingface" monitor and the address of the item
    And the idea targets the Reference it is about
    And model "gpt-6-luna" was the only model asked
    And one soft review request covers the run

  Scenario: A Reference is never drafted twice
    Given the monitors of the site delivered these items:
      | monitor | title      | verdict      | days ago |
      | hn      | First item | include 0.80 | 1        |
      | hn      | Next item  | include 0.70 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories and files them as ideas with a limit of 1
    And the operator drafts monitor stories and files them as ideas with a limit of 1
    And the operator drafts monitor stories and files them as ideas with a limit of 1
    Then the ideas filed are for "First item" and "Next item"
    And the model was asked exactly 2 times in all

  Scenario: The same address delivered as two References is drafted once
    Given the monitors of the site delivered these items:
      | monitor | title             | verdict      | days ago |
      | hn      | Shared item       | include 0.80 | 1        |
      | email   | Shared item again | include 0.70 | 1        |
    And "Shared item again" links to the same address as "Shared item"
    And every linked page can be read
    When the operator drafts monitor stories and files them as ideas with a limit of 3
    And the operator drafts monitor stories and files them as ideas with a limit of 3
    Then the ideas filed are for "Shared item"
    And the model was asked exactly 1 times in all
    And the run record counts 1 item skipped for sharing an address with a drafted one

  Scenario: A Reference that another run drafted while this one was working is not filed again
    Given the monitors of the site delivered these items:
      | monitor | title      | verdict      | days ago |
      | hn      | First item | include 0.80 | 1        |
    And every linked page can be read
    And another run files an idea for "First item" after this run has read the existing ones
    When the operator drafts monitor stories and files them as ideas with a limit of 3
    Then no idea is filed by this run
    And the run record says "First item" was already drafted

  Scenario: A draft an editor declined is not drafted again
    Given the monitors of the site delivered these items:
      | monitor | title      | verdict      | days ago |
      | hn      | First item | include 0.80 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories and files them as ideas with a limit of 3
    And an editor declines the idea
    And the operator drafts monitor stories and files them as ideas with a limit of 3
    Then the model was asked exactly 1 times in all

  Scenario: An item an editor already promoted to a draft item is not drafted
    Given the monitors of the site delivered these items:
      | monitor | title             | verdict      | days ago |
      | hn      | Already promoted  | include 0.90 | 1        |
      | hn      | Not promoted      | include 0.80 | 1        |
    And every linked page can be read
    And an item already carries the Reference of "Already promoted"
    When the operator drafts monitor stories with the default limit
    Then the stories drafted are "Not promoted"

  Scenario: Three stories are drafted by default and the number is a choice
    Given the monitors of the site delivered these items:
      | monitor | title  | verdict      | days ago |
      | hn      | One    | include 0.90 | 1        |
      | hn      | Two    | include 0.80 | 1        |
      | hn      | Three  | include 0.70 | 1        |
      | hn      | Four   | include 0.60 | 1        |
      | hn      | Five   | include 0.50 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with the default limit
    Then 3 stories are drafted

  Scenario: A dry run asks the model and shows the stories but files and stores nothing
    Given the monitors of the site delivered these items:
      | monitor | title  | verdict      | days ago |
      | hn      | One    | include 0.90 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories as a dry run
    Then 1 story is drafted
    And no idea is filed
    And no review was requested

  Scenario: The cost cap stops the run before a call that would pass it
    Given the monitors of the site delivered these items:
      | monitor | title  | verdict      | days ago |
      | hn      | One    | include 0.90 | 1        |
    And every linked page can be read
    When the operator drafts monitor stories with a cost cap of 0.0000001 dollars
    Then the model was asked exactly 0 times
    And the run record says it stopped for cost

  Scenario: The model has to be reached with the site's key
    When the operator drafts monitor stories without an OpenAI key
    Then the operator is told the command needs OPENAI_API_KEY
