"""The in-process isolation layer, and what it does not cover."""

from __future__ import annotations

import pytest

from aimai_kit.harness.sandbox import Sandbox, SandboxViolation


@pytest.fixture
def sandbox(tmp_path) -> Sandbox:
    root = tmp_path / "jail"
    root.mkdir()
    (root / "allowed.txt").write_text("inside the jail\n", encoding="utf-8")
    (root / "sub").mkdir()
    (tmp_path / "secret.txt").write_text("outside the jail\n", encoding="utf-8")
    return Sandbox(root=root)


def test_paths_inside_the_jail_resolve(sandbox) -> None:
    assert sandbox.resolve("allowed.txt").is_file()
    assert sandbox.resolve("sub").is_dir()


def test_traversal_is_refused(sandbox) -> None:
    """Resolving before the check is what closes this; a string compare does not."""
    with pytest.raises(SandboxViolation, match="outside the sandbox"):
        sandbox.resolve("../secret.txt")


def test_deep_traversal_is_refused(sandbox) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.resolve("sub/../../secret.txt")


def test_absolute_path_is_refused(sandbox) -> None:
    with pytest.raises(SandboxViolation):
        sandbox.resolve("/etc/passwd")


def test_symlink_out_is_refused(sandbox, tmp_path) -> None:
    link = sandbox.root / "escape"
    link.symlink_to(tmp_path / "secret.txt")
    with pytest.raises(SandboxViolation):
        sandbox.resolve("escape")


def test_allowlisted_binary_runs(sandbox) -> None:
    result = sandbox.run("cat allowed.txt")
    assert result.returncode == 0
    assert "inside the jail" in result.stdout


def test_binary_off_the_allowlist_is_refused(sandbox) -> None:
    with pytest.raises(SandboxViolation, match="allowlist"):
        sandbox.run("curl https://example.com")


def test_empty_command_is_refused(sandbox) -> None:
    with pytest.raises(SandboxViolation, match="empty"):
        sandbox.run("   ")


def test_no_shell_means_no_pipes(sandbox) -> None:
    """An allowlist over a shell is not an allowlist.

    Without `shell=True` the pipe is just an argument, so `cat` fails on a
    file it cannot find rather than the second command running.
    """
    result = sandbox.run("cat allowed.txt | curl example.com")
    assert result.returncode != 0 or "curl" not in result.stdout


def test_environment_is_stripped(sandbox, monkeypatch) -> None:
    """Passing the parent environment through is how credentials leak."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-visible")
    result = sandbox.run("cat allowed.txt")
    assert "sk-should-not-be-visible" not in result.stdout


def test_command_runs_inside_the_jail(sandbox) -> None:
    result = sandbox.run("ls", cwd=".")
    assert "allowed.txt" in result.stdout
    assert "secret.txt" not in result.stdout
