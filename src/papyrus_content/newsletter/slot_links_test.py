from papyrus_content.newsletter.slot_links import link_problems, links_in

STORY = "https://news.example.com/articles/a.html"


def test_the_stories_own_page_is_allowed_however_it_is_written():
    assert link_problems(f"Read [it]({STORY}) or http://www.news.example.com/articles/a.html/", story_url=STORY) == []


def test_a_link_in_the_story_is_allowed_and_an_invented_one_is_refused():
    text = "See [the report](https://reports.example.org/x) for details."
    assert link_problems("Per https://reports.example.org/x/.", story_url=STORY, story_text=text) == []
    problems = link_problems("Buy at [shop](https://shop.example.net/deal) now, or www.elsewhere.example.com", story_url=STORY, story_text=text)
    assert [p.split()[2] for p in problems] == ["https://shop.example.net/deal", "www.elsewhere.example.com"]


def test_links_the_story_lists_separately_are_allowed_and_a_blurb_with_no_link_has_no_problem():
    assert link_problems("x https://a.example.org/p", story_url=STORY, story_links=["https://a.example.org/p"]) == []
    assert link_problems("Just words.", story_url=STORY) == [] and links_in("Just words.") == []
