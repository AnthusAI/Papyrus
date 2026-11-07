"""The lint that keeps style out of code: every string in the prompt skeleton must be one of the skeleton's own words.

``style_wording_in(source)`` returns the strings in a piece of Python source that are not on the allowed list; the build test applies it to
``prompt_skeleton.py`` (which must give none) and to a sample with style wording in it (which must give some). A new literal in the skeleton is a
deliberate edit of ``ALLOWED`` here, reviewed as a change to the prompt's shape, never as a change of style.
"""
from __future__ import annotations

import ast

# The slot names, their labels and the joining words: the skeleton, and nothing about how a picture should look.
SLOTS = {"style", "treatment", "image type", "constraints", "subject", "composition", "colours", "section", "story", "avoid"}
LABELS = {"Subject:", "Composition:", "Colours:", "Avoid:", "Subject: ", "Composition: ", "Colours: ", "Avoid: "}
JOINERS = {"", " ", ", ", "\n", ":", ".", "(", ")", "x", " by ", " (", ").", "]"}
# Names of fields in the plan and in the resolved style, plus the labels of where a segment came from.
FIELDS = {"effective", "fieldSources", "constraints", "guidance", "avoid", "palette", "sizes", "safeZones", "promptAvoid", "promptDirective", "id", "name", "hex",
          "instruction", "aspectRatio", "width", "height", "masterPrompt", "imageType", "profile", "resolutionHash", "slot", "source", "text", "segments",
          "settings", "planVersion", "image-prompt/v2", "guidance["}
PROVENANCE = {"publication", "request", "image-type", "treatment:", "use:", "image-type:", "section:", "story:", "constraint:"}
ALLOWED = SLOTS | LABELS | JOINERS | FIELDS | PROVENANCE


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _literals(tree: ast.AST) -> list[str]:
    """Every string in the source, including the fixed pieces of an f-string, in the order they appear."""
    skip = _docstrings(tree)
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip]


def style_wording_in(source: str, allowed: set[str] = ALLOWED) -> list[str]:
    """Every string literal (not a docstring) in ``source`` that is not one of the skeleton's allowed words."""
    return [text for text in _literals(ast.parse(source)) if text not in allowed]
