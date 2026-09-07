"""Has a vendor SDK leaked outside `adapters/`?

This is the machine-checkable answer to "did you write your own abstraction,
or did you scatter the SDK everywhere?". It uses AST rather than regex, so
comments like `# import openai` and occurrences inside strings do not raise
false alarms, and forms like `from openai import x as y` do not slip through.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "aimai_kit"
ADAPTERS_DIR = PACKAGE / "provider" / "adapters"

FORBIDDEN_ROOTS = {"openai", "anthropic", "google", "litellm", "langchain"}


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import (`from ..types import X`) has level > 0.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _source_files() -> list[Path]:
    return [p for p in PACKAGE.rglob("*.py") if ADAPTERS_DIR not in p.parents]


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_vendor_sdk_does_not_leak_outside_adapters(path: Path) -> None:
    roots = _import_roots(ast.parse(path.read_text(encoding="utf-8")))
    leaked = roots & FORBIDDEN_ROOTS
    assert not leaked, (
        f"{path.relative_to(PACKAGE)} imports a vendor SDK: {sorted(leaked)}. "
        "Vendor SDKs may only be imported under provider/adapters/."
    )


def test_adapters_actually_use_the_sdk() -> None:
    """Is the test itself meaningful — do the adapters really import an SDK?

    Without this inverse check, deleting the SDK calls by accident would leave
    the suite green and "no leakage" would be an empty guarantee.
    """
    found: set[str] = set()
    for path in ADAPTERS_DIR.rglob("*.py"):
        found |= _import_roots(ast.parse(path.read_text(encoding="utf-8")))
    assert found & FORBIDDEN_ROOTS, "no vendor imports found under adapters/"
