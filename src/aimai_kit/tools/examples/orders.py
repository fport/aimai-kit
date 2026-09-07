"""Five tools over a small orders database.

Every description carries three things, and the third is the one people
forget:

    1. what the tool does,
    2. when NOT to use it, pointing at the neighbouring tool,
    3. whether it has a side effect.

Point 2 is what makes tool selection measurable. With five tools whose
descriptions only say what they do, a model asked "what happened to order
1002?" will plausibly call `find_orders`, `get_order` or `get_customer`.
Adding "to fetch a single order by id use get_order" to `find_orders` removes
that ambiguity, and the eval in `evals/tool_cases.py` shows the difference as
a number.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ..decorator import tool
from ..executor import CallContext
from ..registry import ToolRegistry

__all__ = ["seed_database", "build_registry", "TOOL_NAMES"]

TOOL_NAMES = (
    "find_orders",
    "get_order",
    "get_customer",
    "build_report",
    "cancel_order",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    tenant_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    placed_on TEXT NOT NULL,
    total_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    tenant_id TEXT NOT NULL
);
"""

SEED_CUSTOMERS = [
    ("c-100", "Arcadia Technologies Ltd.", "enterprise", "t-1"),
    ("c-101", "Northwind Logistics Inc.", "standard", "t-1"),
    ("c-102", "Beacon Software AB", "standard", "t-2"),
]

SEED_ORDERS = [
    ("1001", "c-100", "shipped", "2026-07-14", 1_250_000, "USD", "t-1"),
    ("1002", "c-100", "open", "2026-08-02", 480_000, "USD", "t-1"),
    ("1003", "c-101", "open", "2026-08-11", 96_500, "USD", "t-1"),
    ("1004", "c-101", "cancelled", "2026-06-30", 210_000, "USD", "t-1"),
    ("1005", "c-102", "shipped", "2026-08-19", 75_000, "EUR", "t-2"),
]

_DB_PATH = Path(".aimai-orders.sqlite3")


def seed_database(path: Path | str | None = None) -> Path:
    """Create and populate the example database. Idempotent."""
    target = Path(path or _DB_PATH)
    with sqlite3.connect(target) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR REPLACE INTO customers VALUES (?, ?, ?, ?)", SEED_CUSTOMERS
        )
        conn.executemany(
            "INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", SEED_ORDERS
        )
    return target


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path or _DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def build_registry(db_path: Path | str | None = None) -> ToolRegistry:
    """Build a registry whose tools are bound to one database file.

    A closure rather than a module-level connection: tests get their own
    temporary database, and nothing depends on import order.
    """

    @tool
    def find_orders(
        ctx: CallContext,
        customer_id: Annotated[
            str, Field(description="Customer id, for example c-100.")
        ],
        status: Annotated[
            Literal["open", "shipped", "cancelled", "any"],
            Field(description="Filter by status; 'any' means no filter."),
        ] = "any",
        since: Annotated[
            date | None, Field(description="Only orders placed on or after this date.")
        ] = None,
        limit: Annotated[int, Field(description="Maximum rows to return.")] = 20,
    ) -> list[dict]:
        """List a customer's orders, most recent first.

        Use this when you need a LIST of orders or want to filter by status or
        date. To fetch ONE order whose id you already know, use get_order
        instead — it returns more detail and costs less.

        Read-only.
        """
        query = "SELECT * FROM orders WHERE customer_id = ? AND tenant_id = ?"
        params: list[object] = [customer_id, ctx.tenant_id]
        if status != "any":
            query += " AND status = ?"
            params.append(status)
        if since is not None:
            query += " AND placed_on >= ?"
            params.append(since.isoformat())
        query += " ORDER BY placed_on DESC LIMIT ?"
        params.append(limit)
        with _connect(db_path) as conn:
            return [dict(row) for row in conn.execute(query, params)]

    @tool
    def get_order(
        ctx: CallContext,
        order_id: Annotated[str, Field(description="Order id, for example 1002.")],
    ) -> dict:
        """Fetch a single order by its id.

        Use this when you already know the order id. To search for orders you
        do not have an id for, use find_orders.

        Read-only.
        """
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE id = ? AND tenant_id = ?",
                (order_id, ctx.tenant_id),
            ).fetchone()
        if row is None:
            return {"found": False, "order_id": order_id}
        return {"found": True, **dict(row)}

    @tool
    def get_customer(
        ctx: CallContext,
        customer_id: Annotated[str, Field(description="Customer id.")],
    ) -> dict:
        """Fetch a customer's profile: name and service tier.

        Use this for facts about the CUSTOMER. For their orders use
        find_orders; this tool returns no order data.

        Read-only.
        """
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM customers WHERE id = ? AND tenant_id = ?",
                (customer_id, ctx.tenant_id),
            ).fetchone()
        if row is None:
            return {"found": False, "customer_id": customer_id}
        return {"found": True, **dict(row)}

    @tool
    def build_report(
        ctx: CallContext,
        group_by: Annotated[
            Literal["status", "currency"],
            Field(description="Dimension to aggregate on."),
        ] = "status",
    ) -> list[dict]:
        """Aggregate order totals across the whole tenant.

        Use this for SUMMARY questions ("how much is open?"). For individual
        orders use find_orders or get_order; this tool returns no order ids.

        Read-only.
        """
        column = "status" if group_by == "status" else "currency"
        with _connect(db_path) as conn:
            rows = conn.execute(
                f"SELECT {column} AS key, COUNT(*) AS orders, "
                "SUM(total_minor) AS total_minor FROM orders WHERE tenant_id = ? "
                f"GROUP BY {column} ORDER BY {column}",
                (ctx.tenant_id,),
            )
            return [dict(row) for row in rows]

    @tool(side_effect=True, requires_approval=True)
    def cancel_order(
        ctx: CallContext,
        order_id: Annotated[str, Field(description="Order id to cancel.")],
        reason: Annotated[str, Field(description="Why the order is being cancelled.")],
    ) -> dict:
        """Cancel an order. THIS CHANGES DATA and requires human approval.

        Only use this when the user has explicitly asked to cancel a specific
        order. Never call it to 'check' whether cancellation is possible — use
        get_order for that.

        Has a side effect.
        """
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM orders WHERE id = ? AND tenant_id = ?",
                (order_id, ctx.tenant_id),
            ).fetchone()
            if row is None:
                return {"cancelled": False, "reason": "order not found"}
            if row["status"] == "cancelled":
                return {"cancelled": False, "reason": "already cancelled"}
            conn.execute(
                "UPDATE orders SET status = 'cancelled' WHERE id = ? AND tenant_id = ?",
                (order_id, ctx.tenant_id),
            )
        return {"cancelled": True, "order_id": order_id, "reason": reason}

    return ToolRegistry(
        [find_orders, get_order, get_customer, build_report, cancel_order]
    )
