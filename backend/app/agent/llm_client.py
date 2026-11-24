import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings


class LLMClientError(RuntimeError):
    """Erro de comunicação ou contrato inválido do fornecedor LLM."""


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", "ollama", "host.docker.internal"}


class OpenAICompatibleLLMClient:
    """
    Cliente agnóstico para qualquer API compatível com OpenAI Chat Completions + Tool Calling
    (OpenAI, Ollama local, vLLM, OpenRouter, Gemini OpenAI-compat, Azure).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._external_client = http_client

    @property
    def is_ready(self) -> bool:
        if self.settings.llm_provider != "openai_compatible":
            return False
        if not self.settings.llm_model.strip():
            return False
        key = self.settings.llm_api_key.strip()
        if not _is_local_url(self.settings.llm_base_url):
            return bool(key) and "CHANGE_ME" not in key.upper()
        return True

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if not self.is_ready:
            raise LLMClientError("Fornecedor LLM não está configurado ou pronto.")

        base = self.settings.llm_base_url.rstrip("/")
        url = f"{base}/chat/completions"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.settings.llm_api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key.strip()}"

        body: dict[str, Any] = {
            "model": self.settings.llm_model.strip(),
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
        }

        try:
            if self._external_client is not None:
                resp = self._external_client.post(url, headers=headers, json=body)
            else:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Falha ao contactar o fornecedor LLM: {exc}") from exc

        if resp.status_code >= 400:
            raise LLMClientError(f"Fornecedor LLM devolveu HTTP {resp.status_code}.")

        try:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("Resposta inesperada do fornecedor LLM.") from exc

        parsed_calls: list[LLMToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (ValueError, TypeError):
                args = {}
            parsed_calls.append(
                LLMToolCall(
                    id=str(tc.get("id") or f"call_{len(parsed_calls)}"),
                    name=str(fn.get("name") or ""),
                    arguments=args if isinstance(args, dict) else {},
                )
            )

        return LLMResponse(
            content=msg.get("content"),
            tool_calls=parsed_calls,
            finish_reason=choice.get("finish_reason"),
        )
