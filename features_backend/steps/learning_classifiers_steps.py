import json
import tempfile

from behave import given, then, when

from papyrus_content.learning_classifiers import (PromotedLinkCalibration, evaluate_link_fit, evaluate_pack_fit, is_promoted, link_examples,
                                                  order_packs, pack_examples, record_evaluation, split_chronologically, LearningExample)

PERSON = "user:sub-1"


def relation(identifier, decision, decided_by, reason_code=None, note=None, score=0.8):
    return {"id": identifier, "objectKind": "reference", "subjectLineageId": "a", "objectLineageId": "b", "score": score,
            "metadata": json.dumps({"provenance": "suggested", "decision": decision, "decidedBy": decided_by, "decidedAt": "2026-11-01T00:00:00Z",
                                    "reasonCode": reason_code, "note": note})}


REFERENCES = {"a": {"title": "A", "sourceUri": "https://x.example/a", "sourcePublishedAt": "2026-10-01"},
              "b": {"title": "B", "sourceUri": "https://x.example/b", "sourcePublishedAt": "2026-10-04"}}


@given('a person rejected a suggested link with the reason code "{code}" and the note "{note}"')
def step_person_link(context, code, note):
    context.ll_relations = [relation("r1", "rejected", PERSON, code, note)]


@given("automation accepted a suggested link")
def step_automation_link(context):
    context.ll_relations.append(relation("r2", "accepted", "auto:vector"))


@when("the reference-link-fit examples are built")
def step_build_links(context):
    context.ll_examples = link_examples(context.ll_relations, REFERENCES, {"a": {"c"}, "b": {"c"}})


@then("the learning example count is {count:d}")
def step_example_count(context, count):
    assert len(context.ll_examples) == count


@then('the example is labeled "{label}" with the explanation "{explanation}"')
def step_example_label(context, label, explanation):
    row = context.ll_examples[0].as_row("reference-link-fit", "fits", "does-not-fit")
    assert row["labels"]["reference-link-fit"] == {"label": label, "explanation": explanation}
    assert row["provenance"]["labeledBy"] == "editor" and row["provenance"]["modelMade"] is False


@then("the example carries the features similarity, shared concepts, shared host, publication-date gap and both human-accepted")
def step_features(context):
    assert set(context.ll_examples[0].features) == {"similarity", "sharedConcepts", "sharedHost", "publicationGapDays", "bothHumanAccepted"}


def idea(pack, by, destination, note=None):
    item = {"id": f"idea-{pack}", "lineageId": f"idea-{pack}", "stage": destination, "versionCreatedAt": "2026-11-01T00:00:00Z",
            "title": pack, "metadata": json.dumps({"stageMoves": [{"from": "idea", "to": destination, "by": by, "at": "2026-11-01T01:00:00Z", "reason": note or ""}]})}
    generated = {"evidence": {"packId": pack, "signal": "acceptance", "anchor": pack, "surprise": 3.0, "referenceLineageIds": ["a", "b"]}}
    return item, generated


@given('a person moved the idea from pack "{pack}" forward')
def step_forward(context, pack):
    context.ll_ideas = getattr(context, "ll_ideas", []) + [idea(pack, PERSON, "reporting")]


@given('a person spiked the idea from pack "{pack}" with the note "{note}"')
def step_person_spiked(context, pack, note):
    context.ll_ideas.append(idea(pack, PERSON, "spiked", note))


@given('automation spiked the idea from pack "{pack}"')
def step_automation_spiked(context, pack):
    context.ll_ideas.append(idea(pack, "automation:synthesis", "spiked"))


@when("the idea-pack-fit examples are built")
def step_build_packs(context):
    context.ll_examples = pack_examples(context.ll_ideas)


@then('the pack "{pack}" example has the label "{label}"')
def step_pack_label(context, pack, label):
    found = next(example for example in context.ll_examples if example.provenance["packId"] == pack)
    assert found.as_row("idea-pack-fit", "worth-an-idea", "not-worth-an-idea")["labels"]["idea-pack-fit"]["label"] == label


@then('the pack "{pack}" example is labeled "{label}" with the explanation "{explanation}"')
def step_pack_explained(context, pack, label, explanation):
    found = next(example for example in context.ll_examples if example.provenance["packId"] == pack)
    assert found.as_row("idea-pack-fit", "worth-an-idea", "not-worth-an-idea")["labels"]["idea-pack-fit"] == {"label": label, "explanation": explanation}


def link_example(index, similarity, positive, day):
    return LearningExample(f"link-{index}", f"2026-{day}", positive, "", {"similarity": similarity}, "t", "", "s")


def link_history(context, later_positive_similarity):
    train = [link_example(f"t{i}", 0.5, False, "09-01") for i in range(40)] + [link_example(f"u{i}", 0.8, True, "09-02") for i in range(40)]
    later = [link_example(f"l{i}", later_positive_similarity if i % 2 else 0.5, bool(i % 2), "10-01") for i in range(20)]
    context.ll_train, context.ll_held, context.ll_store = train, later, tempfile.mkdtemp()


@given("80 earlier and 20 later link decisions where the Wilson cut is right about every one")
def step_rule_right(context):
    link_history(context, 0.8)


@given("80 earlier and 20 later link decisions where the Wilson cut misses every acceptance")
def step_rule_misses(context):
    link_history(context, 0.6)


@given("a trained version that gets half the later decisions wrong")
def step_half_wrong(context):
    context.ll_probabilities = {e.example_id: (0.9 if e.positive else 0.1) if i % 2 else (0.1 if e.positive else 0.9) for i, e in enumerate(context.ll_held)}


@given("a trained version that gets every later decision right")
def step_all_right(context):
    context.ll_probabilities = {e.example_id: 0.9 if e.positive else 0.1 for e in context.ll_held}


@when("the trained link classifier is evaluated against the rule")
def step_evaluate_links(context):
    from papyrus_content.suggestion_calibration import SuggestionCalibration, calibrate_kind
    rule = SuggestionCalibration(calibrate_kind([(e.features["similarity"], e.positive) for e in context.ll_train], 0.9), calibrate_kind([], 0.9))
    context.ll_rule = rule
    context.ll_evaluation = evaluate_link_fit(context.ll_train, context.ll_held, context.ll_probabilities)
    context.ll_before = PromotedLinkCalibration(rule, is_promoted(context.ll_store, "reference-link-fit"), lambda candidate: 0.9)
    record_evaluation(context.ll_store, context.ll_evaluation, "2026-11-01T00:00:00Z")
    context.ll_after = PromotedLinkCalibration(rule, is_promoted(context.ll_store, "reference-link-fit"), lambda candidate: 0.9)


@then("the link classifier is not promoted")
def step_link_not_promoted(context):
    assert not context.ll_evaluation.promoted and not is_promoted(context.ll_store, "reference-link-fit")


@then("the link classifier is promoted")
def step_link_promoted(context):
    assert context.ll_evaluation.promoted and is_promoted(context.ll_store, "reference-link-fit")


@then("suggestions are marked by the trained version")
def step_trained_marks(context):
    assert context.ll_after.label_candidate("reference", {"similarity": 0.1}) == "likely"


@then("before the evaluation suggestions were marked by the rule")
def step_rule_marks(context):
    assert context.ll_before.label_candidate("reference", {"similarity": 0.1}) == "possible"


def pack_example(name, surprise, positive):
    return LearningExample(f"pack-{name}", "2026-11-01", positive, "", {"surprise": surprise}, name, "", "")


@given("held-out ideas where surprise already orders forwarded ideas first")
def step_surprise_right(context):
    context.ll_held = [pack_example("good", 5.0, True), pack_example("bad", 2.0, False)]


@given("held-out ideas where surprise orders spiked ideas first")
def step_surprise_wrong(context):
    context.ll_held = [pack_example(f"good{i}", 2.0, True) for i in range(6)] + [pack_example(f"bad{i}", 5.0, False) for i in range(6)]


@given("a trained version that orders them the other way")
def step_pack_reversed(context):
    context.ll_probabilities = {e.example_id: 0.1 if e.positive else 0.9 for e in context.ll_held}


@given("a trained version that orders forwarded ideas first")
def step_pack_ordered(context):
    context.ll_probabilities = {e.example_id: 0.9 if e.positive else 0.1 for e in context.ll_held}


@when("the trained pack classifier is evaluated against surprise ordering")
def step_evaluate_packs(context):
    context.ll_store = tempfile.mkdtemp()
    context.ll_evaluation = evaluate_pack_fit(context.ll_held, context.ll_probabilities)
    record_evaluation(context.ll_store, context.ll_evaluation, "2026-11-01T00:00:00Z")
    context.ll_packs = sorted(context.ll_held, key=lambda e: -e.features["surprise"])


def ordered(context):
    return [e.example_id for e in order_packs(context.ll_packs, is_promoted(context.ll_store, "idea-pack-fit"),
                                              lambda pack: context.ll_probabilities[pack.example_id])]


@then("the pack classifier is not promoted")
def step_pack_not_promoted(context):
    assert not context.ll_evaluation.promoted and not is_promoted(context.ll_store, "idea-pack-fit")


@then("the pack classifier is promoted")
def step_pack_promoted(context):
    assert context.ll_evaluation.promoted and is_promoted(context.ll_store, "idea-pack-fit")


@then("the packs stay in surprise order")
def step_surprise_order(context):
    assert ordered(context) == [e.example_id for e in context.ll_packs]


@then("the packs are in the trained version's order")
def step_trained_order(context):
    assert ordered(context)[:6] == sorted(e.example_id for e in context.ll_held if e.positive)
