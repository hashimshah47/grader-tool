"""Thin wrapper around the Anthropic Messages API.

Two calls are all the agent needs:
- ``tool_json``: force the model to answer through one tool, returning its
  validated JSON input (used for rubric parsing, judging, reviews).
- ``text``: free-form answer (used for code generation).
Both stream, so long generations don't hit HTTP timeouts.
"""
from __future__ import annotations

import base64
import re
import time

from . import config


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key if api_key is not None else config.ANTHROPIC_API_KEY
        self.model = model or config.MODEL
        self.client = None
        if key and not config.DEMO_ONLY:
            import anthropic
            self.client = anthropic.Anthropic(api_key=key, max_retries=3)
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    @property
    def live(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------
    @staticmethod
    def _system(system: str) -> list[dict]:
        # Cache the long, stable system prompt (API reference + example) across calls.
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _track(self, msg) -> None:
        u = getattr(msg, "usage", None)
        if u:
            self.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0

    def _create(self, **kw):
        if not self.live:
            raise LLMError("No ANTHROPIC_API_KEY configured (demo mode).")
        last = None
        for attempt in range(3):
            try:
                with self.client.messages.stream(**kw) as stream:
                    msg = stream.get_final_message()
                self._track(msg)
                return msg
            except Exception as e:  # network / overload: retry with backoff
                last = e
                name = type(e).__name__
                if name in ("AuthenticationError", "PermissionDeniedError", "BadRequestError", "NotFoundError"):
                    raise LLMError(f"{name}: {e}") from e
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"LLM request failed: {last}")

    def text(self, system: str, messages: list[dict], max_tokens: int = 16000,
             model: str | None = None) -> str:
        msg = self._create(model=model or self.model, max_tokens=max_tokens,
                           system=self._system(system), messages=messages)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def tool_json(self, system: str, messages: list[dict], tool_name: str, description: str,
                  schema: dict, max_tokens: int = 8000, model: str | None = None) -> dict:
        tool = {"name": tool_name, "description": description, "input_schema": schema}
        msg = self._create(model=model or self.model, max_tokens=max_tokens,
                           system=self._system(system), messages=messages, tools=[tool],
                           tool_choice={"type": "tool", "name": tool_name})
        for b in msg.content:
            if getattr(b, "type", "") == "tool_use" and b.name == tool_name:
                return dict(b.input)
        raise LLMError("Model did not return the expected tool call")


def pdf_block(data: bytes) -> dict:
    return {"type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(data).decode()}}


def extract_python(text: str) -> str:
    """Pull the (last, longest) ```python block out of a reply."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"
