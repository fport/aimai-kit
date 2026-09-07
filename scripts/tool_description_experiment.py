"""How much does tool-description quality change tool selection?

The claim is easy to state and usually left unmeasured: a description that
says only what a tool DOES leaves the model guessing between neighbours, while
one that also says when NOT to use it removes the ambiguity.

This script measures it over three variants of the SAME registry — identical
schemas, identical tools, only the description text differs:

    full            what ships: purpose + boundary sentence + side effect
    no_boundaries   the "use X instead" sentences removed
    one_line        only the first sentence of each description

The selector is a stub, not a model, so the absolute numbers are not a claim
about any provider. What transfers is the DIRECTION, and the fact that the
experiment is cheap enough to run on every description change.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from tool_cases.cases import CASES  # noqa: E402

from aimai_kit.tools import ToolExecutor, ToolRegistry  # noqa: E402
from aimai_kit.tools.evaluation import (  # noqa: E402
    StubToolSelector,
    evaluate_selection,
)
from aimai_kit.tools.examples.orders import build_registry, seed_database  # noqa: E402

OUTPUT = Path("evals/results/tool-selection.json")

# Sentences that tell the model when NOT to reach for a tool. Removing them
# leaves descriptions that are still accurate and still complete about what
# the tool does.
BOUNDARY_RE = re.compile(
    r"(To fetch [^.]*\.|For their [^.]*\.|For individual [^.]*\.|"
    r"Never call [^.]*\.|To search [^.]*\.)",
    re.IGNORECASE,
)


def strip_boundaries(registry: ToolRegistry) -> ToolRegistry:
    """Same tools, same schemas, boundary sentences removed."""
    weakened = ToolRegistry()
    for spec in registry.visible():
        weakened.register(
            replace(spec, description=BOUNDARY_RE.sub("", spec.description).strip())
        )
    return weakened


def first_sentence_only(registry: ToolRegistry) -> ToolRegistry:
    """Same tools, descriptions cut to their first sentence.

    This is what a description looks like when it is written as a label
    rather than as instructions: accurate, complete about purpose, and silent
    about everything the model has to decide.
    """
    trimmed = ToolRegistry()
    for spec in registry.visible():
        head = spec.description.split(".")[0].strip() + "."
        trimmed.register(replace(spec, description=head))
    return trimmed


def main() -> None:
    db = seed_database(Path(".aimai-experiment.sqlite3"))
    full = build_registry(db)

    variants = {
        "full": full,
        "no_boundaries": strip_boundaries(full),
        "one_line": first_sentence_only(full),
    }

    runs = {}
    for label, registry in variants.items():
        report = evaluate_selection(
            StubToolSelector(registry), CASES, ToolExecutor(registry)
        )
        runs[label] = {
            "cases": report.cases,
            "selection_accuracy": report.selection_accuracy,
            "argument_validity_rate": report.argument_validity_rate,
            "forbidden_call_rate": report.forbidden_call_rate,
            "no_tool_accuracy": report.no_tool_accuracy,
            "failures": report.failures,
        }

    width = max(len(k) for k in runs)
    print(f"{'variant'.ljust(width)}  selection  forbidden  no-tool")
    print("-" * (width + 30))
    for label, row in runs.items():
        print(
            f"{label.ljust(width)}  "
            f"{row['selection_accuracy']:>9.1%}  "
            f"{row['forbidden_call_rate']:>9.1%}  "
            f"{row['no_tool_accuracy']:>7.1%}"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON written: {OUTPUT}")
    db.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
