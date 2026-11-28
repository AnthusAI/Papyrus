/** The rating agent's daily review, answered row by row (lib/rating-review.ts): what each row says and the updates a row answer and a dismissal make. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { isRatingsReview, ratingDismissUpdate, ratingRowUpdate, ratingRows, ratingRowsSummary } from "../lib/rating-review";
import { applyReviewUpdate, type ReviewRequest } from "../lib/review-requests";

const NOW = new Date("2026-11-27T12:00:00Z");

function review(): ReviewRequest {
  return {
    id: "rr-ratings-2026-11-27", subject: { type: "batch", id: "ratings-2026-11-27" }, mode: "soft_review", reason: "1 rating suggested, 1 five-star candidate", ask: null,
    raisedBy: "agent:rate", raisedAt: "2026-11-27T08:30:00Z", deadline: null, state: "open", answer: null, history: [], appliedIn: null, updatedAt: "2026-11-27T08:30:00Z",
    links: [
      { type: "story", id: "story-a", label: "Slow water: 4 stars suggested", rating: { title: "Slow water", stars: 4, candidate: false, reason: "Better sourced than usual." } },
      { type: "story", id: "story-c", label: "Deep sea: five-star candidate", rating: { title: "Deep sea", stars: 5, candidate: true, reason: "New documents." } },
    ],
  };
}

test("a ratings review is recognised by its id and its batch subject", () => {
  assert.ok(isRatingsReview(review()));
  assert.ok(!isRatingsReview({ ...review(), id: "rr-batch-ideas" }));
});

test("each row names the Story, its suggested stars and the reason", () => {
  assert.deepEqual(ratingRows(review()), [
    { story: "story-a", title: "Slow water", stars: 4, candidate: false, reason: "Better sourced than usual.", answer: null },
    { story: "story-c", title: "Deep sea", stars: 5, candidate: true, reason: "New documents.", answer: null },
  ]);
  assert.equal(ratingRowsSummary(review()), "Slow water (4 stars suggested); Deep sea (five-star candidate)");
});

test("a row raised before the reason was kept reads its stars from the label and says no reason", () => {
  const old = { ...review(), links: [{ type: "story", id: "story-z", label: "Old story: 3 stars suggested" }] };
  assert.deepEqual(ratingRows(old), [{ story: "story-z", title: "Old story", stars: 3, candidate: false, reason: null, answer: null }]);
});

test("answering a row records the choice; the last row answers the review", () => {
  const first = applyReviewUpdate(review(), ratingRowUpdate(review(), "story-a", "used", 4, "Ed Itor", NOW));
  assert.equal(first.state, "open");
  assert.deepEqual(ratingRows(first)[0].answer, { choice: "used", stars: 4, by: "Ed Itor", at: NOW.toISOString() });
  assert.equal(ratingRowsSummary(first), "Deep sea (five-star candidate)");
  const update = ratingRowUpdate(first, "story-c", "left", null, "Ed Itor", NOW);
  const done = applyReviewUpdate(first, update);
  assert.equal(done.state, "answered");
  assert.equal(update.reviewStateKey, "review#answered");
  assert.equal(done.answer?.decision, "approve");
  assert.deepEqual(ratingRows(done)[1].answer, { choice: "left", stars: null, by: "Ed Itor", at: NOW.toISOString() });
});

test("a row answer is refused on a closed review, for a Story not in it, and for stars outside 1 to 5", () => {
  assert.throws(() => ratingRowUpdate({ ...review(), state: "answered" }, "story-a", "used", 4, "Ed", NOW), /no longer open/);
  assert.throws(() => ratingRowUpdate(review(), "story-x", "used", 4, "Ed", NOW), /not in this review/);
  assert.throws(() => ratingRowUpdate(review(), "story-a", "rated", 6, "Ed", NOW), /1 to 5/);
  assert.throws(() => ratingRowUpdate(review(), "story-a", "rated", null, "Ed", NOW), /1 to 5/);
});

test("dismissing answers the review and says how many suggestions stay unrated", () => {
  const update = ratingDismissUpdate(review(), "Ed Itor", NOW);
  const done = applyReviewUpdate(review(), update);
  assert.equal(done.state, "answered");
  assert.equal(done.answer?.feedback, "Dismissed; 2 suggestions stay on the Stories, unrated.");
  assert.ok(ratingRows(done).every((row) => row.answer === null), "dismissing records no row answer and rates nothing");
});
