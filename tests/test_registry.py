"""Prompt registry: versioning, fingerprints, StrictUndefined."""

from __future__ import annotations

import pytest

from aimai_kit.prompts.registry import PromptRef, PromptRegistry, fingerprint


@pytest.fixture
def registry(tmp_path) -> PromptRegistry:
    (tmp_path / "summary@v1.md").write_text("Role: assistant.\n", encoding="utf-8")
    (tmp_path / "summary@v2.md").write_text(
        "Role: assistant.\nAt most {{ n }} words.\n", encoding="utf-8"
    )
    (tmp_path / "summary@v10.md").write_text("v10 text\n", encoding="utf-8")
    return PromptRegistry(tmp_path)


def test_prompt_ref_carries_three_parts(registry) -> None:
    _, ref = registry.render("summary@v2", n=100)
    assert ref.name == "summary" and ref.version == "v2"
    assert len(ref.fingerprint) == 8
    assert str(ref) == f"summary@v2+{ref.fingerprint}"


def test_ref_round_trips() -> None:
    ref = PromptRef.parse("extract_contract@v2+baad0c9b")
    assert (ref.name, ref.version, ref.fingerprint) == (
        "extract_contract",
        "v2",
        "baad0c9b",
    )


def test_fingerprint_changes_when_text_changes_without_a_version_bump(
    registry, tmp_path
) -> None:
    """People forget to bump versions; fingerprints do not."""
    _, before = registry.render("summary@v1")
    (tmp_path / "summary@v1.md").write_text("Role: CHANGED.\n", encoding="utf-8")
    _, after = PromptRegistry(tmp_path).render("summary@v1")
    assert before.name_version == after.name_version
    assert before.fingerprint != after.fingerprint


def test_line_endings_do_not_change_the_fingerprint() -> None:
    assert fingerprint("a\r\nb\r\n") == fingerprint("a\nb\n")


def test_versions_are_sorted_numerically(registry) -> None:
    """Alphabetical sorting would put v10 before v2."""
    assert registry.versions("summary") == [
        "summary@v1",
        "summary@v2",
        "summary@v10",
    ]
    assert registry.latest("summary") == "summary@v10"


def test_missing_variable_is_not_silently_blank(registry) -> None:
    """StrictUndefined: fail loudly rather than call a model with no context."""
    with pytest.raises(ValueError, match="failed to render"):
        registry.render("summary@v2")


def test_unknown_prompt_lists_available_ones(registry) -> None:
    with pytest.raises(FileNotFoundError, match="summary@v1"):
        registry.load("missing@v1")
