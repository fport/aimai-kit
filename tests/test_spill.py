"""Spill: big output leaves the context but stays reachable."""

from __future__ import annotations

import pytest

from aimai_kit.harness.spill import SPILL_SCHEME, SpillStore, build_spill_tools
from aimai_kit.tools import ToolExecutor, ToolRegistry


@pytest.fixture
def store(tmp_path) -> SpillStore:
    return SpillStore(tmp_path / "run-1", threshold_chars=500, head_chars=200)


BIG = "\n".join(f"line {i}: content for line {i}" for i in range(900))


def test_threshold_decides_what_spills(store) -> None:
    assert store.should_spill(BIG)
    assert not store.should_spill("short output")


def test_summary_is_small(store) -> None:
    summary = store.spill("find_orders", BIG)
    assert len(summary) < len(BIG) / 10


def test_summary_states_what_was_stored(store) -> None:
    """A reference with no summary forces a read just to decide to read."""
    summary = store.spill("find_orders", BIG)
    assert "900 lines" in summary
    assert str(len(BIG)) in summary
    assert SPILL_SCHEME in summary


def test_full_content_is_reachable_by_reference(store) -> None:
    summary = store.spill("find_orders", BIG)
    ref = SPILL_SCHEME + summary.split(SPILL_SCHEME)[1][:12]
    body = store.read(ref, 400, 402)
    assert "line 399" in body and "line 401" in body
    assert "line 800" not in body


def test_line_range_is_clamped(store) -> None:
    summary = store.spill("t", BIG)
    ref = SPILL_SCHEME + summary.split(SPILL_SCHEME)[1][:12]
    body = store.read(ref, 890, 99_999)
    assert "line 899" in body


def test_unknown_reference_is_explained_not_raised(store) -> None:
    assert "not a valid spill reference" in store.read("nonsense")
    assert "another run" in store.read(f"{SPILL_SCHEME}aaaaaaaaaaaa")


def test_identical_content_reuses_one_file(store) -> None:
    store.spill("a", BIG)
    store.spill("b", BIG)
    assert len(list(store.root.glob("*.txt"))) == 1


def test_spill_tools_are_registrable(store) -> None:
    registry = ToolRegistry(build_spill_tools(store))
    assert registry.names() == ["read_notes", "read_spill", "write_note"]


def test_scratchpad_round_trips(store) -> None:
    """The other half of the idea: somewhere to put findings that is not the
    context window."""
    tools = {t.tool_spec.name: t for t in build_spill_tools(store)}
    executor = ToolExecutor(ToolRegistry(list(tools.values())))

    executor.call("write_note", '{"text": "order ORD-88421 must not be cancelled"}')
    executor.call("write_note", '{"text": "cap is 125,000"}')
    result = executor.call("read_notes", "{}")

    assert "ORD-88421" in result.content
    assert "125,000" in result.content


def test_empty_scratchpad_says_so(store) -> None:
    tools = build_spill_tools(store)
    executor = ToolExecutor(ToolRegistry(tools))
    assert "empty" in executor.call("read_notes", "{}").content


def test_read_spill_through_the_executor(store) -> None:
    summary = store.spill("find_orders", BIG)
    ref = SPILL_SCHEME + summary.split(SPILL_SCHEME)[1][:12]
    executor = ToolExecutor(ToolRegistry(build_spill_tools(store)))
    result = executor.call(
        "read_spill", f'{{"ref": "{ref}", "start_line": 1, "end_line": 3}}'
    )
    assert result.ok
    assert "line 0" in result.content


def test_clear_removes_the_run_directory_contents(store) -> None:
    store.spill("t", BIG)
    store.clear()
    assert not list(store.root.glob("*.txt"))
