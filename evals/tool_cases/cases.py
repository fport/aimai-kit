"""Golden cases for tool selection.

Twenty-two cases, and three of them expect NO tool call at all. Those three
matter more than they look: a model that reaches for a tool on every input is
not a well-behaved agent, it is an expensive one, and a golden set without
negative cases cannot see that behavior at all.

The forbidden lists are narrow on purpose. `cancel_order` is forbidden on any
read-only question, because the failure mode there is not a wrong answer but a
cancelled order.
"""

from __future__ import annotations

from aimai_kit.tools.evaluation import ToolCase

CANCEL = ("cancel_order",)

CASES: list[ToolCase] = [
    ToolCase(
        id="tc-01",
        query="fetch order 1002 by its id",
        expected_tools=("get_order",),
        forbidden_tools=CANCEL,
        arguments={"get_order": {"order_id": "1002"}},
    ),
    ToolCase(
        id="tc-02",
        query="list every order for customer c-100",
        expected_tools=("find_orders",),
        forbidden_tools=CANCEL,
        arguments={"find_orders": {"customer_id": "c-100"}},
    ),
    ToolCase(
        id="tc-03",
        query="what service tier is customer c-101 on",
        expected_tools=("get_customer",),
        forbidden_tools=CANCEL,
        arguments={"get_customer": {"customer_id": "c-101"}},
    ),
    ToolCase(
        id="tc-04",
        query="aggregate order totals grouped by status",
        expected_tools=("build_report",),
        forbidden_tools=CANCEL,
        arguments={"build_report": {"group_by": "status"}},
    ),
    ToolCase(
        id="tc-05",
        query="cancel order 1003, the customer changed their mind",
        expected_tools=("cancel_order",),
        arguments={"cancel_order": {"order_id": "1003", "reason": "customer request"}},
        note="the only case where the side-effecting tool is correct",
    ),
    ToolCase(
        id="tc-06",
        query="search orders for customer c-101 with status open",
        expected_tools=("find_orders",),
        forbidden_tools=CANCEL,
        arguments={"find_orders": {"customer_id": "c-101", "status": "open"}},
    ),
    ToolCase(
        id="tc-07",
        query="get order 1005",
        expected_tools=("get_order",),
        forbidden_tools=CANCEL,
        arguments={"get_order": {"order_id": "1005"}},
    ),
    ToolCase(
        id="tc-08",
        query="summary of totals grouped by currency",
        expected_tools=("build_report",),
        forbidden_tools=CANCEL,
        arguments={"build_report": {"group_by": "currency"}},
    ),
    ToolCase(
        id="tc-09",
        query="profile of customer c-102",
        expected_tools=("get_customer",),
        forbidden_tools=CANCEL,
        arguments={"get_customer": {"customer_id": "c-102"}},
    ),
    ToolCase(
        id="tc-10",
        query="orders placed since 2026-08-01 for customer c-100",
        expected_tools=("find_orders",),
        forbidden_tools=CANCEL,
        arguments={"find_orders": {"customer_id": "c-100", "since": "2026-08-01"}},
    ),
    ToolCase(
        id="tc-11",
        query="thanks, that is all I needed",
        forbidden_tools=CANCEL,
        note="negative case: no tool should be called",
    ),
    ToolCase(
        id="tc-12",
        query="what is your name",
        forbidden_tools=CANCEL,
        note="negative case: no tool should be called",
    ),
    ToolCase(
        id="tc-13",
        query="explain what an invoice is in general terms",
        forbidden_tools=CANCEL,
        note="negative case: general knowledge, no data lookup",
    ),
    ToolCase(
        id="tc-14",
        query="fetch order 1001 by id",
        expected_tools=("get_order",),
        forbidden_tools=CANCEL,
        arguments={"get_order": {"order_id": "1001"}},
    ),
    ToolCase(
        id="tc-15",
        query="list cancelled orders for customer c-101",
        expected_tools=("find_orders",),
        forbidden_tools=CANCEL,
        arguments={"find_orders": {"customer_id": "c-101", "status": "cancelled"}},
    ),
    ToolCase(
        id="tc-16",
        query="aggregate totals across the tenant",
        expected_tools=("build_report",),
        forbidden_tools=CANCEL,
    ),
    ToolCase(
        id="tc-17",
        query="which tier is customer c-100",
        expected_tools=("get_customer",),
        forbidden_tools=CANCEL,
        arguments={"get_customer": {"customer_id": "c-100"}},
    ),
    ToolCase(
        id="tc-18",
        query="cancel order 1002 because it was a duplicate",
        expected_tools=("cancel_order",),
        arguments={"cancel_order": {"order_id": "1002", "reason": "duplicate"}},
    ),
    ToolCase(
        id="tc-19",
        query="get order 1004",
        expected_tools=("get_order",),
        forbidden_tools=CANCEL,
        arguments={"get_order": {"order_id": "1004"}},
    ),
    ToolCase(
        id="tc-20",
        query="list orders for customer c-102",
        expected_tools=("find_orders",),
        forbidden_tools=CANCEL,
        arguments={"find_orders": {"customer_id": "c-102"}},
    ),
    ToolCase(
        id="tc-21",
        query="report grouped by status please",
        expected_tools=("build_report",),
        forbidden_tools=CANCEL,
    ),
    ToolCase(
        id="tc-22",
        query="fetch order 1003 by id",
        expected_tools=("get_order",),
        forbidden_tools=CANCEL,
        arguments={"get_order": {"order_id": "1003"}},
    ),
]
