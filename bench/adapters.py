from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ModelReply:
    message: dict[str, Any]
    raw: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Adapter(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply: ...

    def list_models(self) -> list[str]: ...


def request_json(
    url: str, payload: dict[str, Any] | None, headers: dict[str, str], timeout: int
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from model endpoint: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"model endpoint unavailable: {exc.reason}") from exc


THINK_CHOICES = ["default", "off", "on", "low", "medium", "high"]


def think_value(think: str | None) -> bool | str | None:
    """Map the CLI --think choice onto Ollama's `think` field.

    `default` (or None) omits the field so the model's own default applies. `off`/`on` map to
    booleans; `low`/`medium`/`high` are effort levels for models such as gpt-oss that cannot
    disable thinking and ignore `false`. Models without effort levels treat a level as `true`.
    """
    if think in (None, "default"):
        return None
    if think == "off":
        return False
    if think == "on":
        return True
    if think in ("low", "medium", "high"):
        return think
    raise ValueError(f"unknown think setting: {think}")


SAMPLING_KEYS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty", "seed")


def sampling_options(sampling: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only sampling keys that were explicitly set. Unset keys are not sent, so the model's
    Modelfile default applies; set keys are sent and recorded so a run is reproducible even if
    the Modelfile changes."""
    return {key: value for key, value in (sampling or {}).items() if key in SAMPLING_KEYS and value is not None}


class OllamaAdapter:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout: int = 600,
        context_window: int = 32768,
        think: str | None = None,
        max_output_tokens: int = 24576,
        sampling: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.options = {
            **sampling_options(sampling),
            "num_ctx": context_window,
            # Bound one turn's generation. Unbounded, a reasoning loop runs until the context is
            # full or the request times out, and either kills the whole run.
            "num_predict": max_output_tokens,
        }
        self.think = think_value(think)

    def list_models(self) -> list[str]:
        response = request_json(f"{self.base_url}/api/tags", None, {}, self.timeout)
        return [item["name"] for item in response.get("models", []) if "name" in item]

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        ollama_messages = []
        for message in messages:
            cleaned = {key: value for key, value in message.items() if key != "tool_call_id"}
            ollama_messages.append(cleaned)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "tools": tools,
            "stream": False,
            "options": self.options,
        }
        if self.think is not None:
            payload["think"] = self.think
        response = request_json(f"{self.base_url}/api/chat", payload, {}, self.timeout)
        return ModelReply(
            message=response.get("message", {}),
            raw=response,
            prompt_tokens=response.get("prompt_eval_count"),
            completion_tokens=response.get("eval_count"),
        )


class OpenAIAdapter:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:1234/v1",
        timeout: int = 600,
        api_key_env: str | None = None,
        max_output_tokens: int = 24576,
        sampling: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Chat Completions knows temperature / top_p / presence_penalty / seed; the rest are
        # server-specific and dropped here.
        self.sampling = {
            key: value for key, value in sampling_options(sampling).items()
            if key in ("temperature", "top_p", "presence_penalty", "seed")
        }
        self.max_output_tokens = max_output_tokens
        self.api_key = os.environ.get(api_key_env, "") if api_key_env else ""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def list_models(self) -> list[str]:
        response = request_json(f"{self.base_url}/models", None, self.headers(), self.timeout)
        return [item["id"] for item in response.get("data", []) if "id" in item]

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        response = request_json(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                **self.sampling,
                "max_tokens": self.max_output_tokens,
            },
            self.headers(),
            self.timeout,
        )
        choices = response.get("choices", [])
        if not choices:
            raise RuntimeError("model endpoint returned no choices")
        usage = response.get("usage", {})
        return ModelReply(
            message=choices[0].get("message", {}),
            raw=response,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )


def make_adapter(
    kind: str,
    model: str,
    base_url: str | None,
    timeout: int,
    api_key_env: str | None = None,
    think: str | None = None,
    context_window: int = 32768,
    max_output_tokens: int = 24576,
    sampling: dict[str, Any] | None = None,
) -> Adapter:
    if kind == "ollama":
        return OllamaAdapter(
            model=model,
            base_url=base_url or "http://127.0.0.1:11434",
            timeout=timeout,
            context_window=context_window,
            think=think,
            max_output_tokens=max_output_tokens,
            sampling=sampling,
        )
    if kind == "openai":
        return OpenAIAdapter(
            model=model,
            base_url=base_url or "http://127.0.0.1:1234/v1",
            timeout=timeout,
            api_key_env=api_key_env,
            max_output_tokens=max_output_tokens,
            sampling=sampling,
        )
    raise ValueError(f"unknown adapter: {kind}")

