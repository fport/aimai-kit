"""Azure OpenAI variant.

One real difference, but an expensive one: the `model` parameter takes the
DEPLOYMENT NAME, not the model name. On Azure the same model can exist as
"gpt4o-prod" and "gpt4o-test"; writing "gpt-4o" in code does not produce a
working call.

So the deployment name comes from the environment and is never hardcoded.
`self.model` holds the deployment name — that is what should show up in
telemetry too, because billing and quota are per deployment.

Everything else matches the OpenAI adapter; inheritance only replaces client
construction. Here inheritance is the right tool: same behavior, different
connection.
"""

from __future__ import annotations

import os
from typing import Any

from .openai_ import OpenAIAdapter

__all__ = ["DEFAULT_API_VERSION", "AzureOpenAIAdapter"]

DEFAULT_API_VERSION = "2025-04-01-preview"


class AzureOpenAIAdapter(OpenAIAdapter):
    provider = "azure_openai"

    def __init__(
        self,
        deployment: str | None = None,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        timeout_s: float = 60.0,
        client: Any = None,
    ) -> None:
        deployment = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        if not deployment:
            raise ValueError(
                "An Azure deployment name is required. Set "
                "AZURE_OPENAI_DEPLOYMENT or pass deployment=."
            )
        # Deliberate: OpenAIAdapter.__init__ is not called, because client
        # construction is entirely different. The fields are set here.
        self.model = deployment  # what shows up in telemetry
        if client is not None:
            self._client = client
            return

        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=endpoint or os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=api_key or os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=api_version
            or os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION),
            max_retries=0,
            timeout=timeout_s,
        )
