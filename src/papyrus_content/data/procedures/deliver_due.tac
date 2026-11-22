-- papyrus-procedure-kind: deliver_due
-- The engine's run for a Delivery's due time: the scheduled send (PPY-e2829f).
--
-- A Delivery's earliest pending time (its lock or release time, or a named wait) has one follow-up timer (src/papyrus_content/announcements/delivery_timers.py). At
-- that time the timer puts one wake on the site's queue and the procedure runner starts this, with no adopted agent: the engine's own follow-ups are not an agent's
-- work, and only the site's pause stops them (src/papyrus_content/engine_follow_ups.py). It reads the Delivery again and, only if it still waits for exactly that
-- time, raises the lock when the lock time has come (soft review: the policy approves the current version when nobody acted; hard review with no approval: one flag,
-- nothing sent), then sends what is due through the announce agent's deliver steps with their guards (mode, account, pause, budget). The run ends `acted` (sent or
-- locked), `asked` (waiting_for_person) or `nothing` with the reason. It calls no model and decides nothing about what is announced.
-- Specs: features_backend/announcements/delivery-scheduled-send.feature

Toolset "papyrus_deliver_due" {
    type = "plugin",
    modules = {"papyrus_newsroom.tactus_tools"}
}

Procedure {
    input = {
        deliveryId = field.string{required = true, description = "The Delivery whose time came"},
        dueAt = field.string{required = true, description = "The time the wake was set for, a UTC instant"}
    },
    output = {
        summary = field.string{required = true, description = "One sentence: what was sent or locked, or why nothing was done"},
        result = field.object{required = true, description = "What the wake did and why"},
        run_outcome = field.string{description = "acted, asked when a person must approve, or nothing; the runner records it"},
        run_outcome_reason = field.string{description = "sent, locked, waiting_for_person, not_waiting, not_releasable or not_sent"}
    },
    function(input)
        local deliver = Tool.get("papyrus_deliver_due")
        local result = deliver({delivery_id = input.deliveryId, due_at = input.dueAt})
        return {summary = result.summary, result = result.result, run_outcome = result.run_outcome, run_outcome_reason = result.run_outcome_reason}
    end
}
