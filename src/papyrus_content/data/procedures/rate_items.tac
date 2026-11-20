-- papyrus-procedure-kind: rate_items
-- The rating agent's daily run (slice L1, PPY-d85860; definition src/papyrus_content/agent_definitions/core/rate.yaml).
--
-- The site's schedule puts one wake a day on its queue and the procedure runner starts this. It reads the published Stories nobody has rated, by the site's
-- head stage index, newest first, and asks the bulk-tier model about each one: three stars (the default), four (clearly better than the usual Story) or
-- five, which is never a rating: a five is listed as a candidate for a person. What it may write is the site's agent policy, answered by the one gate: at the
-- rung observe it writes nothing, files no review request and records what it would rate and why; at the rung draft the same run writes the threes and fours.
-- It never replaces a rating, never gives a five and never publishes. The run ends `acted` (with the counts) or `nothing` (reason nothing_unrated).
--
-- It runs only on an agent's wake adopted as the responsibility "rate": `papyrus automations adopt --id rate --responsibility rate`. The model work is in the
-- tool (papyrus_content/rating_agent.py), which reports each call's usage to the run, so the run's cost counts it.
-- Specs: features_backend/agents/rating-agent.feature

Toolset "papyrus_rate_items" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {},
    output = {
        summary = field.string{required = true, description = "One sentence: how many Stories it looked at, what it proposed and wrote"},
        result = field.object{required = true, description = "The counts, each proposal with its reason, the five-star candidates, what could not be judged and the gate's answers"},
        run_outcome = field.string{description = "acted, or nothing when no Story waits for a rating; the runner records it"},
        run_outcome_reason = field.string{description = "proposed, rated or nothing_unrated"}
    },
    function(input)
        local rate = Tool.get("papyrus_rate_items")
        local result = rate({})
        return {summary = result.summary, result = result, run_outcome = result.run_outcome, run_outcome_reason = result.run_outcome_reason}
    end
}
