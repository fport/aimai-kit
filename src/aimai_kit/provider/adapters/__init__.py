"""Vendor SDKs are imported ONLY inside this package.

`test_no_vendor_leak.py` enforces that statically. The rule is not a style
preference: the moment an SDK import enters a file, that file is bound to
that provider and "switch the model" becomes a find-and-replace job. With the
boundary held here, swapping providers stays a one-line configuration change
even from inside the agent loop.

Imports are LAZY (inside functions) so the package can be imported without
the `providers` extra installed. A user who only installs Anthropic simply
never imports the OpenAI adapter.
"""

from __future__ import annotations

__all__ = ["make_adapter"]


def make_adapter(spec: str, **kwargs):
    """Build a client from a spec like 'anthropic:claude-opus-5'.

    The CLI and the eval harness take model lists as text; keeping the
    parsing in one place stops every caller from writing its own if/elif
    chain.
    """
    if ":" not in spec:
        raise ValueError(
            f"Model spec must look like 'provider:model', got: {spec!r}. "
            "Example: anthropic:claude-opus-5"
        )
    provider, model = spec.split(":", 1)
    provider = provider.strip().lower()

    if provider == "openai":
        from .openai_ import OpenAIAdapter

        return OpenAIAdapter(model=model, **kwargs)
    if provider == "anthropic":
        from .anthropic_ import AnthropicAdapter

        return AnthropicAdapter(model=model, **kwargs)
    if provider == "gemini":
        from .gemini_ import GeminiAdapter

        return GeminiAdapter(model=model, **kwargs)
    if provider in ("azure", "azure_openai"):
        from .azure_openai import AzureOpenAIAdapter

        return AzureOpenAIAdapter(deployment=model, **kwargs)

    raise ValueError(f"Unknown provider: {provider!r}")
