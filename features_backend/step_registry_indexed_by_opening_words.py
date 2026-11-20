"""Find a step's definition by its opening words instead of trying every definition in turn.

behave keeps step definitions in a list. Registering one tries it against every definition before it, and running a step
tries every definition until one matches. With about fifteen thousand definitions that was some thirty-eight million
pattern matches, and half a minute, before the first scenario of any run.

A parse pattern can only match a step that begins with the pattern's own text up to its first placeholder, so definitions
are kept by that opening text and only those whose opening text begins the step are tried. A definition that opens with a
placeholder, or that is not a parse pattern, is tried for every step, exactly as before. The answer is always the one
behave itself would give: the same ambiguity errors when a step is registered, and the earliest registered match when a
step runs.
"""
from __future__ import annotations

from behave.matchers import ParseMatcher
from behave.step_registry import AmbiguousStep, StepRegistry, _text, make_step_matcher

NO_OPENING_TEXT = ""


def opening_text_every_matching_step_begins_with(step_matcher) -> str:
    if not isinstance(step_matcher, ParseMatcher):
        return NO_OPENING_TEXT
    text_before_the_first_placeholder = step_matcher.pattern.split("{", 1)[0].split("}", 1)[0]
    plain_characters = []
    for character in text_before_the_first_placeholder:
        if not character.isascii():
            break
        plain_characters.append(character.lower())
    return "".join(plain_characters)


class StepRegistryIndexedByOpeningWords(StepRegistry):
    def index_the_definitions_registered_so_far(self) -> None:
        self.definitions_by_type_and_opening_text = {}
        self.opening_text_lengths_by_type = {}
        self.definition_count = 0
        for step_type, step_matchers in self.steps.items():
            for step_matcher in step_matchers:
                self.remember(step_type, step_matcher)

    def index_is_current(self) -> bool:
        return getattr(self, "definition_count", None) == sum(len(step_matchers) for step_matchers in self.steps.values())

    def remember(self, step_type: str, step_matcher) -> None:
        opening_text = opening_text_every_matching_step_begins_with(step_matcher)
        self.definitions_by_type_and_opening_text.setdefault((step_type, opening_text), []).append(
            (self.definition_count, step_matcher)
        )
        self.opening_text_lengths_by_type.setdefault(step_type, set()).add(len(opening_text))
        self.definition_count += 1

    def definitions_that_could_match(self, step_type: str, step_text: str) -> list:
        if not self.index_is_current():
            self.index_the_definitions_registered_so_far()
        lower_case_step_text = step_text.lower()
        numbered = []
        for length in self.opening_text_lengths_by_type.get(step_type, ()):
            if length <= len(lower_case_step_text):
                numbered += self.definitions_by_type_and_opening_text.get((step_type, lower_case_step_text[:length]), [])
        return [step_matcher for _, step_matcher in sorted(numbered, key=lambda numbered_matcher: numbered_matcher[0])]

    def add_step_definition(self, keyword, step_text, func) -> None:
        new_step_type = keyword.lower()
        step_text = _text(step_text)
        new_step_matcher = make_step_matcher(func, step_text, new_step_type)
        if not self.is_good_step_definition(new_step_matcher):
            return
        for existing in self.definitions_that_could_match(new_step_type, step_text):
            if self.same_step_matcher(existing, new_step_matcher):
                return
            if existing.matches(step_text):
                message = "%s has already been defined in\n  existing step %s"
                raise AmbiguousStep(message % (new_step_matcher.describe(), existing.describe(existing.SCHEMA_AT_LOCATION)))
        self.steps[new_step_type].append(new_step_matcher)
        self.remember(new_step_type, new_step_matcher)

    def definitions_to_try_in_behave_order(self, step) -> list:
        candidates = self.definitions_that_could_match(step.step_type, step.name)
        if step.step_type != "step":
            candidates += self.definitions_that_could_match("step", step.name)
        return candidates

    def find_step_definition(self, step):
        for step_definition in self.definitions_to_try_in_behave_order(step):
            if step_definition.match(step.name):
                return step_definition
        return None

    def find_match(self, step):
        for step_definition in self.definitions_to_try_in_behave_order(step):
            result = step_definition.match(step.name)
            if result:
                return result
        return None


METHODS_EVERY_REGISTRY_TAKES_OVER = (
    "index_the_definitions_registered_so_far",
    "index_is_current",
    "remember",
    "definitions_that_could_match",
    "add_step_definition",
    "definitions_to_try_in_behave_order",
    "find_step_definition",
    "find_match",
)


def look_steps_up_by_opening_words() -> None:
    """behave makes its registry before any project code runs, so the lookup is given to every registry there is or will be."""
    for method_name in METHODS_EVERY_REGISTRY_TAKES_OVER:
        setattr(StepRegistry, method_name, StepRegistryIndexedByOpeningWords.__dict__[method_name])
