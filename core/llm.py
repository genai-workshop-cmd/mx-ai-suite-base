"""Model access for every agent.

Three providers behind one interface:

  anthropic -> Claude API (the blueprint default)
  openai    -> any OpenAI-compatible /chat/completions endpoint
  offline   -> no model available; callers fall back to deterministic templates

`complete()` never raises for a missing provider. It returns an `LLMReply` with
`ok=False`, so an agent can degrade to its deterministic path instead of
crashing the pipeline. Genuine transport failures after all retries do raise.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig, SuiteConfig
from .errors import LLMError
from .logging import get

log = get("suite.llm")

#: Errors worth another attempt.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class LLMReply:
    text: str = ""
    ok: bool = False
    provider: str = "offline"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient:
    """Thin, retrying wrapper. One instance per process is plenty."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._client: Any = None
        self._calls = 0
        self._tokens = 0

    # -- public ------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.cfg.available

    @property
    def usage(self) -> dict[str, int]:
        return {"calls": self._calls, "tokens": self._tokens}

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMReply:
        """Single-turn completion. Returns ok=False when no provider is set."""
        if not self.available:
            return LLMReply(
                ok=False,
                reason="No model configured - running in offline mode.",
                provider="offline",
            )

        max_tokens = max_tokens or self.cfg.max_tokens
        temperature = self.cfg.temperature if temperature is None else temperature

        last_error: Exception | None = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                if self.cfg.provider == "anthropic":
                    reply = self._anthropic(system, user, max_tokens, temperature)
                else:
                    reply = self._openai(system, user, max_tokens, temperature)
                self._calls += 1
                self._tokens += reply.tokens
                return reply
            except _Retryable as exc:
                last_error = exc
                if attempt == self.cfg.max_retries:
                    break
                delay = min(2 ** attempt + random.random(), 20.0)
                log.warning(
                    "model call failed (%s), retry %d/%d in %.1fs",
                    exc, attempt, self.cfg.max_retries, delay,
                )
                time.sleep(delay)
            except Exception as exc:  # non-retryable
                raise LLMError(f"{self.cfg.provider} call failed: {exc}") from exc

        raise LLMError(
            f"{self.cfg.provider} call failed after {self.cfg.max_retries} attempts: {last_error}"
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
    ) -> tuple[dict | list | None, LLMReply]:
        """Completion that must yield JSON. Returns (parsed_or_None, reply)."""
        reply = self.complete(
            system + "\n\nRespond with JSON only. No prose, no markdown fence.",
            user,
            max_tokens=max_tokens,
        )
        if not reply.ok:
            return None, reply
        parsed = extract_json(reply.text)
        if parsed is None:
            log.warning("model returned unparseable JSON (%d chars)", len(reply.text))
        return parsed, reply

    # -- providers ---------------------------------------------------------
    def _anthropic(self, system: str, user: str, max_tokens: int, temperature: float) -> LLMReply:
        import anthropic

        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self.cfg.api_key, "timeout": self.cfg.timeout_seconds}
            if self.cfg.base_url:
                kwargs["base_url"] = self.cfg.base_url
            self._client = anthropic.Anthropic(**kwargs)

        try:
            msg = self._client.messages.create(
                model=self.cfg.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:
            if _is_retryable(exc):
                raise _Retryable(str(exc)) from exc
            raise

        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return LLMReply(
            text=text,
            ok=True,
            provider="anthropic",
            model=self.cfg.model,
            input_tokens=getattr(msg.usage, "input_tokens", 0),
            output_tokens=getattr(msg.usage, "output_tokens", 0),
        )

    def _openai(self, system: str, user: str, max_tokens: int, temperature: float) -> LLMReply:
        import httpx

        url = self.cfg.base_url
        if not url:
            raise LLMError("MODEL_URL1 is not set.")
        # Accept either a base URL or the full endpoint.
        if not url.rstrip("/").endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"

        payload = {
            "model": self.cfg.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.cfg.timeout_seconds,
            )
        except httpx.TransportError as exc:
            raise _Retryable(f"transport: {exc}") from exc

        if resp.status_code in _RETRYABLE_STATUS:
            raise _Retryable(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code} from model endpoint: {resp.text[:400]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"Model returned no choices: {str(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return LLMReply(
            text=_strip_reasoning(text),
            ok=True,
            provider="openai",
            model=self.cfg.model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


class _Retryable(Exception):
    """Internal marker for a failure worth retrying."""


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _RETRYABLE_STATUS:
        return True
    name = type(exc).__name__
    return name in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "OverloadedError",
    }


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Reasoning models (e.g. Nemotron) emit <think> blocks we do not want."""
    return _THINK_RE.sub("", text).strip()


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict | list | None:
    """Best-effort JSON recovery from a model reply."""
    text = _strip_reasoning(text).strip()
    if not text:
        return None

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    candidates.extend(block.strip() for block in fenced)
    candidates.append(text)

    # Fall back to the outermost brace/bracket span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


_client: LLMClient | None = None


def client(cfg: SuiteConfig) -> LLMClient:
    """Process-wide client for the given config."""
    global _client
    if _client is None or _client.cfg is not cfg.llm:
        _client = LLMClient(cfg.llm)
    return _client
