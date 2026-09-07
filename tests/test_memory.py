"""Memory store: the write gate and the staleness filter."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from aimai_kit.harness.memory import (
    MemoryKind,
    MemoryStore,
    WriteRefused,
)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


def test_a_plain_fact_is_stored(store) -> None:
    record = store.write(
        MemoryKind.SEMANTIC,
        "Customer c-100 is on the enterprise tier.",
        source="crm",
    )
    assert record.id is not None
    assert len(store) == 1


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("Card 4111111111111111 is on file for this account", "credential"),
        ("Their contact address is buyer@example.com for billing", "credential"),
        ("The api_key: abc123def456 was rotated last night", "credential"),
        ("The customer is probably unhappy about the delay", "speculation"),
        ("The account is suspended right now pending review", "only true right now"),
        ("ok", "too short"),
    ],
)
def test_write_gate_refuses(store, content: str, reason: str) -> None:
    """The gate is deterministic; the model is never asked."""
    with pytest.raises(WriteRefused, match=reason.split()[0]):
        store.write(MemoryKind.EPISODIC, content, source="chat")
    assert len(store) == 0


def test_refusal_explains_itself(store) -> None:
    with pytest.raises(WriteRefused) as excinfo:
        store.write(MemoryKind.EPISODIC, "The token: xyz9876543210", source="chat")
    assert "credential" in str(excinfo.value)


def test_recall_filters_expired_records(store) -> None:
    store.write(
        MemoryKind.SEMANTIC,
        "Customer c-101 is on a trial plan.",
        source="crm",
        valid_until=date.today() - timedelta(days=1),
    )
    store.write(
        MemoryKind.SEMANTIC, "Customer c-100 is on the enterprise tier.", source="crm"
    )
    contents = [r.content for r in store.recall()]
    assert len(contents) == 1
    assert "enterprise" in contents[0]


def test_expired_records_can_be_asked_for_explicitly(store) -> None:
    store.write(
        MemoryKind.SEMANTIC,
        "Customer c-101 is on a trial plan.",
        source="crm",
        valid_until=date.today() - timedelta(days=1),
    )
    assert len(store.recall(include_stale=True)) == 1


def test_future_validity_is_not_stale(store) -> None:
    store.write(
        MemoryKind.SEMANTIC,
        "The renewal window opens in spring.",
        source="crm",
        valid_until=date.today() + timedelta(days=30),
    )
    assert len(store.recall()) == 1


def test_stale_ratio_makes_decay_visible(store) -> None:
    """A store where half the recalls drop expired records is not working."""
    for i in range(3):
        store.write(
            MemoryKind.SEMANTIC,
            f"Old fact number {i} about the account.",
            source="crm",
            valid_until=date.today() - timedelta(days=1),
        )
    store.write(MemoryKind.SEMANTIC, "A fact that does not expire.", source="crm")
    assert store.stale_ratio() == 0.75


def test_recall_filters_by_kind(store) -> None:
    store.write(MemoryKind.SEMANTIC, "Tier is enterprise for c-100.", source="crm")
    store.write(MemoryKind.PROCEDURAL, "Cancellations need a reason.", source="policy")
    assert len(store.recall(kind=MemoryKind.PROCEDURAL)) == 1


def test_recall_matches_content(store) -> None:
    store.write(MemoryKind.SEMANTIC, "Tier is enterprise for c-100.", source="crm")
    store.write(MemoryKind.SEMANTIC, "Region is EU for c-100.", source="crm")
    assert len(store.recall("enterprise")) == 1


def test_store_persists_to_a_file(tmp_path) -> None:
    path = tmp_path / "memory.sqlite3"
    first = MemoryStore(path)
    first.write(MemoryKind.SEMANTIC, "A durable fact about the account.", source="crm")
    first.close()

    second = MemoryStore(path)
    assert len(second) == 1
