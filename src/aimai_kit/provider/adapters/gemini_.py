"""Gemini adapter — google-genai.

Three traps, all normalized here:

1. The assistant role is called "model", not "assistant". Without the
   translation the API rejects the role and conversation history breaks
   quietly.
2. The system instruction is not top level; it lives inside `config`
   (`system_instruction`).
3. Messages are not plain strings but
   `{"role": ..., "parts": [{"text": ...}]}`.

Also, the timeout is in MILLISECONDS while the others take seconds. Passing
`timeout_s=60` straight through would set a 60-millisecond timeout — the kind
of bug that costs hours ("every call times out"). The multiplication happens
here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ..errors import AuthError, InvalidRequest, LLMError, RateLimited, TransientError
from ..types import ChatRequest, ChatResult, Role, ToolCall, Usage

__all__ = ["GeminiAdapter"]

_ROLE_MAP = {Role.USER: "user", Role.ASSISTANT: "model", Role.TOOL: "user"}


class GeminiAdapter:
    provider = "gemini"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        client: Any = None,
    ) -> None:
        self.model = model
        self.timeout_s = timeout_s
        if client is not None:
            self._client = client
        else:
            from google import genai

            self._client = genai.Client(
                api_key=api_key,
                # MILLISECONDS. Seconds everywhere else.
                http_options={"timeout": int(timeout_s * 1000)},
            )

    def _contents(self, req: ChatRequest) -> list[dict[str, Any]]:
        return [
            {"role": _ROLE_MAP[m.role], "parts": [{"text": m.content}]}
            for m in req.messages
            if m.role is not Role.SYSTEM
        ]

    def _config(self, req: ChatRequest) -> dict[str, Any]:
        config: dict[str, Any] = {"max_output_tokens": req.max_output_tokens}
        if req.system:
            # inside config, not at the top level
            config["system_instruction"] = req.system
        if req.temperature is not None:
            config["temperature"] = req.temperature
        if req.stop:
            config["stop_sequences"] = list(req.stop)
        if req.tools:
            config["tools"] = [{"function_declarations": list(req.tools)}]
        if req.json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = dict(req.json_schema.schema)
        config.update(req.extra.get("gemini", {}))
        return config

    def _translate_error(self, error: Exception) -> LLMError:
        from google.genai import errors as genai_errors

        common = {"provider": self.provider, "model": self.model, "cause": error}
        status = getattr(error, "code", None) or getattr(error, "status_code", None)

        if isinstance(error, genai_errors.APIError):
            if status == 429:
                return RateLimited(str(error), status_code=status, **common)
            if status in (401, 403):
                return AuthError(str(error), status_code=status, **common)
            if status and status >= 500:
                return TransientError(str(error), status_code=status, **common)
            return InvalidRequest(str(error), status_code=status, **common)
        if isinstance(error, TimeoutError | ConnectionError):
            return TransientError(str(error), **common)
        return LLMError(str(error), **common)

    @staticmethod
    def _tool_calls(response: Any) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for index, part in enumerate(getattr(content, "parts", None) or []):
                fn = getattr(part, "function_call", None)
                if fn is None:
                    continue
                args = getattr(fn, "args", {}) or {}
                calls.append(
                    ToolCall(
                        id=getattr(fn, "id", "") or f"call_{index}",
                        name=getattr(fn, "name", ""),
                        arguments=json.dumps(args, ensure_ascii=False),
                    )
                )
        return calls

    def complete(self, req: ChatRequest) -> ChatResult:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=self._contents(req),
                config=self._config(req),
            )
        except Exception as error:
            raise self._translate_error(error) from error

        usage = response.usage_metadata
        # Field names differ again: prompt_token_count / candidates_token_count.
        cached = getattr(usage, "cached_content_token_count", 0) or 0
        return ChatResult(
            text=response.text or "",
            usage=Usage(
                input_tokens=usage.prompt_token_count or 0,
                output_tokens=usage.candidates_token_count or 0,
                cached_input_tokens=cached,
                reasoning_tokens=getattr(usage, "thoughts_token_count", 0) or 0,
            ),
            provider=self.provider,
            model=self.model,
            finish_reason=str(
                getattr(response.candidates[0], "finish_reason", "STOP")
                if response.candidates
                else "STOP"
            ),
            prompt_ref=req.prompt_ref,
            tool_calls=self._tool_calls(response),
            raw=response,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        try:
            stream = self._client.models.generate_content_stream(
                model=self.model,
                contents=self._contents(req),
                config=self._config(req),
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except Exception as error:
            raise self._translate_error(error) from error
