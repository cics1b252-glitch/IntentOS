"""Google Gemini implementation of the canonical Provider Port."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from intent_kernel.providers.base import LLMProvider
from intent_kernel.types import CompletionResult, Message


class GeminiProviderError(RuntimeError):
    """Safe, classified Gemini failure without credentials or raw payloads."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


class GeminiProvider(LLMProvider):
    """Gemini Developer API provider using the official API-key contract."""

    name = "gemini"
    models = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
    api_root = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gemini-2.5-flash-lite",
        transport: Transport | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.default_model = default_model
        self._transport = transport or self._http_transport

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        use_model = model or self.default_model
        contents = [
            {
                "role": "model" if item.role == "assistant" else "user",
                "parts": [{"text": item.content}],
            }
            for item in messages
            if item.content
        ]
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        _, data = await asyncio.to_thread(
            self._request,
            "POST",
            f"models/{use_model}:generateContent",
            payload,
        )
        try:
            candidate = data["candidates"][0]
            answer = "".join(
                part.get("text", "")
                for part in candidate["content"]["parts"]
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiProviderError("invalid_response") from exc
        usage = data.get("usageMetadata", {})
        return CompletionResult(
            text=answer,
            model=data.get("modelVersion", use_model),
            usage={
                "prompt_tokens": int(usage.get("promptTokenCount", 0)),
                "completion_tokens": int(usage.get("candidatesTokenCount", 0)),
                "total_tokens": int(usage.get("totalTokenCount", 0)),
            },
            finish_reason=str(candidate.get("finishReason", "STOP")).lower(),
        )

    async def diagnose(self) -> dict[str, Any]:
        """Validate the key and return a user-safe connection state."""
        try:
            await asyncio.to_thread(self._request, "GET", "models", None)
            return {"ok": True, "status": "connected", "error_code": None}
        except GeminiProviderError as exc:
            return {"ok": False, "status": exc.code, "error_code": exc.code}

    async def health_check(self) -> bool:
        return bool((await self.diagnose())["ok"])

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        if not self.api_key:
            raise GeminiProviderError("invalid_key")
        return self._transport(method, path, payload)

    def _http_transport(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.api_root}/{path}",
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key or "",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS API root
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            code = {
                400: "invalid_request",
                401: "invalid_key",
                403: "invalid_key",
                429: "quota_reached",
                500: "unavailable",
                503: "unavailable",
                504: "unavailable",
            }.get(exc.code, "provider_error")
            raise GeminiProviderError(code, exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise GeminiProviderError("unavailable") from exc
