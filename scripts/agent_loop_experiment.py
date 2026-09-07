"""What does loop detection actually buy?

Twenty scripted tasks, five of which are stuck runs, executed under two
configurations that differ in exactly one way:

    detection_on    warn on the second repeat, stop on the third
    detection_off   never stop for repetition; only the budgets do

The claim being tested is not "loop detection is good" — it is that the
saving is measurable and comes out of the budget rather than out of quality.
A stuck run that is stopped at step 3 and one that is stopped at the step
budget produce the same (unfinished) outcome; the difference is what they
cost on the way there.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))

from agent_tasks.tasks import TASKS  # noqa: E402

from aimai_kit.agent import (  # noqa: E402
    Agent,
    Budgets,
    ScriptedClient,
    Thread,
    run_metrics,
)
from aimai_kit.agent.loopdetect import LoopDetector  # noqa: E402
from aimai_kit.tools import CallContext, ToolExecutor  # noqa: E402
from aimai_kit.tools.examples.orders import (  # noqa: E402
    build_registry,
    seed_database,
)

OUTPUT = Path("evals/results/agent-loop-detection.json")
BUDGETS = Budgets(max_steps=8, max_tokens=None, max_usd=None, max_seconds=None)


def run_configuration(*, detection: bool, registry) -> list[Thread]:
    executor = ToolExecutor(registry)
    ctx = CallContext(user_id="u-1", tenant_id="t-1")
    threads: list[Thread] = []

    for task in TASKS:
        thread = Thread()
        if not detection:
            # Off means "never stop for repetition"; the budgets still apply.
            thread.detector = LoopDetector(warn_at=10**6, stop_at=10**6)
        agent = Agent(
            ScriptedClient(list(task.script)),
            executor,
            system="You are an operations assistant.",
            budgets=BUDGETS,
        )
        agent.run(thread, task.request, ctx=ctx)
        threads.append(thread)

    return threads


def main() -> None:
    db = Path(tempfile.mkdtemp()) / "orders.sqlite3"
    seed_database(db)
    registry = build_registry(db)

    runs = {}
    for label, detection in (("detection_on", True), ("detection_off", False)):
        threads = run_configuration(detection=detection, registry=registry)
        runs[label] = run_metrics(threads).as_dict()

    columns = (
        "completion_rate",
        "steps_p50",
        "steps_p95",
        "loop_rate",
        "budget_stop_rate",
    )
    header = "config".ljust(15) + "".join(c.rjust(19) for c in columns)
    print(header)
    print("-" * len(header))
    for label, metrics in runs.items():
        row = "".join(str(metrics[c]).rjust(19) for c in columns)
        print(label.ljust(15) + row)

    saved = runs["detection_off"]["steps_p95"] - runs["detection_on"]["steps_p95"]
    print(f"\nsteps saved at p95 by loop detection: {saved:g}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON written: {OUTPUT}")


if __name__ == "__main__":
    main()
