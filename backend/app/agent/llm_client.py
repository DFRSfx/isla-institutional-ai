import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings, is_private_or_local_url

THINK_BLOCK_REGEX = re.compile(r"<think>.*?</think>\s*", flags=re.DOTALL | re.IGNORECASE)


def strip_reasoning_tags(text: str | None) -> str | None:
    if text is None:
        return None
    return THINK_BLOCK_REGEX.sub("", text).strip()


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


class OpenAICompatibleLLMClient:
    """
    Cliente agnóstico para qualquer API compatível com OpenAI Chat Completions + Tool Calling,
    orientado prioritariamente a LLMs locais/on-premise (Ollama, vLLM) por conformidade RGPD/NIS2.
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
        is_local = is_private_or_local_url(self.settings.llm_base_url)
        if not is_local and not self.settings.llm_allow_external_endpoints:
            return False
        key = self.settings.llm_api_key.strip()
        if not is_local:
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
            "temperature": 0.0,
            "max_tokens": self.settings.llm_max_tokens,
        }
        if self.settings.llm_reasoning_effort != "default":
            body["reasoning_effort"] = self.settings.llm_reasoning_effort

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
            content=strip_reasoning_tags(msg.get("content")),
            tool_calls=parsed_calls,
            finish_reason=choice.get("finish_reason"),
        )

    def stream_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
    ) -> Iterator[str]:
        """
        Faz streaming real token-a-token via SSE (`/v1/chat/completions` com `stream=True`),
        suprimindo eventuais blocos `<think>...</think>` em tempo real.
        """
        if not self.is_ready:
            raise LLMClientError("Fornecedor LLM não está configurado ou pronto.")

        base = self.settings.llm_base_url.rstrip("/")
        url = f"{base}/chat/completions"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.settings.llm_api_key.strip():
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key.strip()}"

        body: dict[str, Any] = {
            "model": self.settings.llm_model.strip(),
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": self.settings.llm_max_tokens,
            "stream": True,
        }
        if self.settings.llm_reasoning_effort != "default":
            body["reasoning_effort"] = self.settings.llm_reasoning_effort

        in_think = False
        buffer = ""

        def _consume_chunk(chunk: str) -> str:
            nonlocal in_think, buffer
            buffer += chunk
            emitted = ""
            while buffer:
                if in_think:
                    end_idx = buffer.lower().find("</think>")
                    if end_idx == -1:
                        # Mantém apenas últimos 8 chars para não partir tag de fecho
                        if len(buffer) > 8:
                            buffer = buffer[-8:]
                        break
                    buffer = buffer[end_idx + len("</think>") :].lstrip()
                    in_think = False
                else:
                    start_idx = buffer.lower().find("<think>")
                    if start_idx == -1:
                        # Evita emitir início parcial de "<think>"
                        safe_end = len(buffer)
                        for k in range(1, min(7, len(buffer)) + 1):
                            if "<think>".startswith(buffer[-k:].lower()):
                                safe_end = len(buffer) - k
                                break
                        if safe_end > 0:
                            emitted += buffer[:safe_end]
                            buffer = buffer[safe_end:]
                        break
                    if start_idx > 0:
                        emitted += buffer[:start_idx]
                    buffer = buffer[start_idx + len("<think>") :]
                    in_think = True
            return emitted

        try:
            with (
                httpx.Client(timeout=self.settings.llm_timeout_seconds) as client,
                client.stream("POST", url, headers=headers, json=body) as resp,
            ):
                if resp.status_code >= 400:
                    raise LLMClientError(f"Fornecedor LLM devolveu HTTP {resp.status_code}.")
                for raw_line in resp.iter_lines():
                    line = raw_line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        payload = json.loads(data_str)
                        choices = payload.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        token = delta.get("content")
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if isinstance(token, str) and token:
                        clean = _consume_chunk(token)
                        if clean:
                            yield clean
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Falha no streaming do fornecedor LLM: {exc}") from exc

        if not in_think and buffer:
            yield buffer
