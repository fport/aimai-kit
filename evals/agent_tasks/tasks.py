"""Twenty scripted agent tasks.

Each task is a model script: the sequence of turns a model would produce for
that request. Scripting the model rather than calling one makes the loop's
behavior measurable — the same twenty tasks under two configurations differ
only by the configuration.

Five of the tasks are stuck runs: the script repeats the same call. Those are
the ones that make loop detection measurable at all. Without them, "loop
detection on" and "loop detection off" produce identical numbers and the
feature looks free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["AgentTask", "TASKS"]


@dataclass(frozen=True)
class AgentTask:
    id: str
    request: str
    script: list = field(default_factory=list)
    expect_stuck: bool = False
    note: str = ""


def _repeat(call: tuple[str, str], times: int) -> list:
    return [[call] for _ in range(times)]


TASKS: list[AgentTask] = [
    AgentTask(
        id="at-01",
        request="What is the status of order 1002?",
        script=[[("get_order", '{"order_id": "1002"}')], "Order 1002 is open."],
    ),
    AgentTask(
        id="at-02",
        request="List the orders for customer c-100.",
        script=[[("find_orders", '{"customer_id": "c-100"}')], "Two orders."],
    ),
    AgentTask(
        id="at-03",
        request="Which tier is customer c-101 on?",
        script=[[("get_customer", '{"customer_id": "c-101"}')], "Standard tier."],
    ),
    AgentTask(
        id="at-04",
        request="Summarize order totals by status.",
        script=[[("build_report", '{"group_by": "status"}')], "Three statuses."],
    ),
    AgentTask(
        id="at-05",
        request="What does an invoice mean?",
        script=["An invoice is a request for payment."],
        note="no tool needed",
    ),
    AgentTask(
        id="at-06",
        request="Status of order 1001 and the customer's tier.",
        script=[
            [
                ("get_order", '{"order_id": "1001"}'),
                ("get_customer", '{"customer_id": "c-100"}'),
            ],
            "Shipped, enterprise tier.",
        ],
        note="two calls in one turn",
    ),
    AgentTask(
        id="at-07",
        request="Find open orders for c-101 then get the details of the first.",
        script=[
            [("find_orders", '{"customer_id": "c-101", "status": "open"}')],
            [("get_order", '{"order_id": "1003"}')],
            "Order 1003 is open for USD 965.00.",
        ],
        note="sequential dependency",
    ),
    AgentTask(
        id="at-08",
        request="Report totals by currency.",
        script=[[("build_report", '{"group_by": "currency"}')], "USD and EUR."],
    ),
    AgentTask(
        id="at-09",
        request="Get order 1005.",
        script=[[("get_order", '{"order_id": "1005"}')], "Not in your tenant."],
    ),
    AgentTask(
        id="at-10",
        request="Look up order 9999.",
        script=[[("get_order", '{"order_id": "9999"}')], "No such order."],
        note="tool returns a not-found result, not an error",
    ),
    AgentTask(
        id="at-11",
        request="Check order 1002 repeatedly.",
        script=_repeat(("get_order", '{"order_id": "1002"}'), 6) + ["giving up"],
        expect_stuck=True,
    ),
    AgentTask(
        id="at-12",
        request="Keep listing orders for c-100.",
        script=_repeat(("find_orders", '{"customer_id": "c-100"}'), 6) + ["giving up"],
        expect_stuck=True,
    ),
    AgentTask(
        id="at-13",
        request="Keep building the same report.",
        script=_repeat(("build_report", '{"group_by": "status"}'), 6) + ["giving up"],
        expect_stuck=True,
    ),
    AgentTask(
        id="at-14",
        request="Keep asking for customer c-102.",
        script=_repeat(("get_customer", '{"customer_id": "c-102"}'), 6) + ["giving up"],
        expect_stuck=True,
    ),
    AgentTask(
        id="at-15",
        request="Keep checking order 1004.",
        script=_repeat(("get_order", '{"order_id": "1004"}'), 6) + ["giving up"],
        expect_stuck=True,
    ),
    AgentTask(
        id="at-16",
        request="Call a tool that does not exist, then recover.",
        script=[
            [("fetch_order", '{"order_id": "1002"}')],
            [("get_order", '{"order_id": "1002"}')],
            "Order 1002 is open.",
        ],
        note="recovery from no_such_tool",
    ),
    AgentTask(
        id="at-17",
        request="Send malformed arguments, then recover.",
        script=[
            [("get_order", "{broken")],
            [("get_order", '{"order_id": "1002"}')],
            "Order 1002 is open.",
        ],
        note="recovery from bad_json",
    ),
    AgentTask(
        id="at-18",
        request="Omit a required field, then recover.",
        script=[
            [("get_order", "{}")],
            [("get_order", '{"order_id": "1001"}')],
            "Order 1001 shipped.",
        ],
        note="recovery from bad_args",
    ),
    AgentTask(
        id="at-19",
        request="Orders for c-100 placed since August.",
        script=[
            [("find_orders", '{"customer_id": "c-100", "since": "2026-08-01"}')],
            "One order in August.",
        ],
    ),
    AgentTask(
        id="at-20",
        request="Thanks, nothing else.",
        script=["You are welcome."],
        note="no tool needed",
    ),
]
