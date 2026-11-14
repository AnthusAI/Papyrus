"""The idea pipeline, first version (PPY-8ffc18): a digest of a site's recent references, and a synthesis of story ideas from it.

``papyrus ideas digest`` is deterministic and uses no model. ``papyrus ideas synthesize`` asks one model for story ideas that
combine several cited references, drops near-duplicates of what the site has already run or drafted, and stores each idea
privately (a JSON record on this machine, or a draft ``story_draft`` Proposal on a site that has the proposals model).
``papyrus ideas trends`` drafts cited trend stories from a weekly knowledge snapshot (``trends.py``). Nothing here publishes anything. See docs/idea-pipeline.md.
"""
