"""Single-attempt OpenAI-compatible HTTP model client. No CLI or Judge path."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import math
from pathlib import Path
import time
from uuid import uuid4

import httpx

from .cohort import digest, write_new

OPENAI_RESPONSES_MODELS = {"gpt-5.6-sol", "gpt-6.1-sol"}


class ModelFailure(RuntimeError):
    pass


def load_secret(role):
    """Read an explicitly configured local credential without logging its value."""
    name = "JOURNEY_" + role.upper() + "_API_KEY"
    if not os.getenv(name) and os.getenv(name + "_FILE"):
        values = [
            v.strip()
            for v in Path(os.environ[name + "_FILE"])
            .read_text(encoding="utf-8-sig")
            .splitlines()
            if v.strip()
        ]
        if len(values) == 2:
            # Explicit two-provider file: DeepSeek first, OpenAI second.
            host = httpx.URL(
                os.getenv("JOURNEY_" + role.upper() + "_BASE_URL", "")
            ).host
            if (
                host not in {"api.deepseek.com", "api.openai.com"}
                or values[0] == values[1]
            ):
                raise ValueError(
                    "Two-key file needs distinct DeepSeek/OpenAI keys and a known endpoint"
                )
            value = values[0 if host == "api.deepseek.com" else 1]
        elif len(values) == 1:
            value = values[0]
        else:
            raise ValueError(
                "Credential file must contain one key, or DeepSeek then OpenAI on separate lines"
            )
        if not value or any(c.isspace() for c in value):
            raise ValueError("Credential file must contain one bare key")
        os.environ[name] = value
    if not os.getenv(name):
        raise ValueError("Missing credential: " + name + " or " + name + "_FILE")
    return name


@dataclass(frozen=True)
class ModelConfig:
    role: str
    base_url: str
    model: str
    key_env: str
    timeout: float = 120
    max_tokens: int = 4096
    options_json: str = "{}"

    @classmethod
    def from_env(cls, role):
        if role not in {"sut", "put"}:
            raise ValueError("Only baseline SUT and Persona PUT; no Judge/review")
        prefix = "JOURNEY_" + role.upper() + "_"
        base, model = (
            os.getenv(prefix + "BASE_URL", ""),
            os.getenv(prefix + "MODEL", ""),
        )
        if not base or not model:
            raise ValueError(
                prefix
                + "BASE_URL and MODEL are required; native CLI aliases are not assumed API model IDs"
            )
        return cls(
            role,
            base.rstrip("/"),
            model,
            prefix + "API_KEY",
            float(os.getenv(prefix + "TIMEOUT", "120")),
            int(os.getenv(prefix + "MAX_TOKENS", "4096")),
            os.getenv(prefix + "OPTIONS_JSON") or "{}",
        )

    def public(self):
        return {
            "role": self.role,
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "options": json.loads(self.options_json),
            "key_env": self.key_env,
            "api_protocol": self.protocol,
        }

    @property
    def protocol(self):
        return (
            "responses"
            if httpx.URL(self.base_url).host == "api.openai.com"
            and self.model in OPENAI_RESPONSES_MODELS
            else "chat_completions"
        )

    def validate(self):
        url = httpx.URL(self.base_url)
        if (
            self.role not in {"sut", "put"}
            or not self.model
            or not 0 < self.timeout <= 600
            or type(self.max_tokens) is not int
            or self.max_tokens < 1
            or url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Invalid bounded API configuration or credential-bearing URL"
            )
        options = json.loads(self.options_json)
        if not isinstance(options, dict) or set(options) - {
            "temperature",
            "top_p",
            "reasoning_effort",
            "seed",
            "thinking",
            "response_format",
        }:
            raise ValueError(
                "Only declared sampling/reasoning/response options may be configured"
            )
        for name, maximum in (("temperature", 2), ("top_p", 1)):
            if name in options and (
                type(options[name]) not in {int, float}
                or not math.isfinite(options[name])
                or not 0 <= options[name] <= maximum
            ):
                raise ValueError("Invalid " + name)
        if "seed" in options and type(options["seed"]) is not int:
            raise ValueError("Seed must be an integer")
        if "reasoning_effort" in options and options["reasoning_effort"] not in {
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("Unknown reasoning effort")
        if url.host == "api.openai.com" and self.model in OPENAI_RESPONSES_MODELS:
            efforts = {
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
            }
            if self.model == "gpt-5.6-sol":
                efforts.add("none")
            if options.get("reasoning_effort") not in efforts:
                raise ValueError(
                    f"Freeze explicit supported {self.model} reasoning_effort"
                )
            if set(options) - {"reasoning_effort", "response_format"}:
                raise ValueError(
                    "Sol adapter supports explicit reasoning/response options only"
                )
        if url.scheme == "http" and url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Use HTTPS for remote model APIs")
        if "thinking" in options and options["thinking"] not in (
            {"type": "enabled"},
            {"type": "disabled"},
        ):
            raise ValueError(
                "Explicit enabled/disabled thinking configuration required"
            )
        from .put_protocol import SOL_PUT_FORMAT

        if "response_format" in options and options["response_format"] not in (
            {"type": "text"},
            {"type": "json_object"},
        ):
            if not (
                url.host == "api.openai.com"
                and self.model in OPENAI_RESPONSES_MODELS
                and self.role == "put"
                and options["response_format"] == SOL_PUT_FORMAT
            ):
                raise ValueError("Unsupported response format")
        # Current DeepSeek required tool choice rejects thinking-enabled calls.
        # Reject locally, before any paid request, rather than silently mutating it.
        if (
            self.role == "sut"
            and url.host == "api.deepseek.com"
            and options.get("thinking") != {"type": "disabled"}
        ):
            raise ValueError(
                "DeepSeek SUT requires explicit thinking.type=disabled for required tool choice"
            )
        return self


class APIClient:
    def __init__(
        self,
        config,
        directory,
        *,
        transport=None,
        cap=200,
        ledger_path=None,
        request_limit=None,
    ):
        config.validate()
        if (
            config.role not in {"sut", "put"}
            or not 0 < config.timeout <= 600
            or config.max_tokens < 1
        ):
            raise ValueError("Invalid bounded model configuration")
        url = httpx.URL(config.base_url)
        if url.scheme not in {"http", "https"} or url.userinfo or url.query:
            raise ValueError(
                "Use an explicit HTTP API base URL without embedded credentials/query"
            )
        self.config, self.directory, self.cap = config, Path(directory), cap
        self.ledger_path = ledger_path
        self.request_limit = request_limit
        self.http = httpx.Client(
            timeout=config.timeout, transport=transport, follow_redirects=False
        )
        self.calls = 0
        self.stopped = False
        self.trace_prefix = self.directory.name if config.role == "sut" else uuid4().hex
        from .responses_adapter import ResponsesHistory

        self.responses_history = (
            ResponsesHistory() if config.protocol == "responses" else None
        )

    def call(self, messages, *, tools=None):
        if self.stopped or self.calls >= self.cap:
            raise ModelFailure("Stopped or request cap reached; no retry")
        key = os.getenv(self.config.key_env, "")
        if not key:
            raise ValueError(
                "Missing credential environment variable: " + self.config.key_env
            )
        payload = {
            "model": self.config.model,
            "messages": messages,
        }
        openai = httpx.URL(self.config.base_url).host == "api.openai.com"
        payload["max_completion_tokens" if openai else "max_tokens"] = (
            self.config.max_tokens
        )
        extra = json.loads(self.config.options_json)
        if not isinstance(extra, dict) or set(extra) - {
            "temperature",
            "top_p",
            "reasoning_effort",
            "seed",
            "thinking",
            "response_format",
        }:
            raise ValueError(
                "Only declared sampling/reasoning options may be configured"
            )
        payload.update(extra)
        if tools:
            payload.update(
                tools=tools, tool_choice="required", parallel_tool_calls=True
            )
        if self.responses_history:
            payload = self.responses_history.payload(messages, self.config, tools)
        self.calls += 1
        folder = self.directory / f"{self.calls:04d}"
        try:
            write_new(
                folder / "request.json",
                {
                    "role": self.config.role,
                    "config": self.config.public(),
                    "body": payload,
                },
            )
        except FileExistsError:
            self.stopped = True
            raise ModelFailure(
                "Request already exists; no replay or continuation"
            ) from None
        started = time.monotonic()
        ledger = self.ledger_path or os.getenv("JOURNEY_REQUEST_LEDGER")
        request_id = None
        receipt = {
            "role": self.config.role,
            "request_sha256": digest(payload),
            "usage": None,
            "usage_unknown": True,
            "automatic_retry": False,
            "currency_cost_measured": False,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "request_sent": False,
            "api_protocol": self.config.protocol,
            "client_request_id": self.trace_prefix + "-" + str(self.calls),
            "input_cache_policy": "provider_prefix_cache_only; no saved answer reuse",
            "system_prefix_sha256": digest(
                [m for m in messages[:1] if m.get("role") == "system"]
            ),
            "tools_sha256": digest(tools) if tools else None,
        }
        try:
            if ledger:
                from .ledger import reserve

                request_id = reserve(
                    ledger,
                    self.config.role,
                    receipt["request_sha256"],
                    int(self.request_limit or os.environ["JOURNEY_REQUEST_LIMIT"]),
                )
            receipt["request_sent"] = True
            response = self.http.post(
                self.config.base_url
                + ("/responses" if self.responses_history else "/chat/completions"),
                json=payload,
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "X-Client-Request-Id": receipt["client_request_id"],
                },
            )
            receipt["http_status"] = response.status_code
            # Only diagnostic response headers; never persist auth/cookies.
            receipt["rate_limit_headers"] = {
                name: value.replace(key, "[REDACTED]")
                for name, value in response.headers.items()
                if name.lower() in {"retry-after", "retry-after-ms"}
                or name.lower().startswith("x-ratelimit-")
            }
            text = response.text.replace(key, "[REDACTED]")
            write_new(
                folder / "response.json",
                {"http_status": response.status_code, "body": text},
            )
            response.raise_for_status()
            body = json.loads(text)
            if self.responses_history:
                from .responses_adapter import normalized_usage

                receipt["usage"] = normalized_usage(body.get("usage"))
            else:
                receipt["usage"] = body.get("usage")
            receipt["usage_unknown"] = not bool(receipt["usage"])
            receipt.update(
                response_id=body.get("id"),
                response_model=body.get("model"),
                system_fingerprint=body.get("system_fingerprint"),
                created=body.get("created", body.get("created_at")),
            )
            if self.responses_history:
                message = self.responses_history.accept(body, payload, messages)
            else:
                choices = body.get("choices")
                if (
                    not isinstance(choices, list)
                    or len(choices) != 1
                    or choices[0].get("finish_reason") not in {"stop", "tool_calls"}
                ):
                    raise ValueError("Incomplete/ambiguous model completion")
                message = choices[0]["message"]
            if message.get("role") != "assistant" or not (
                message.get("content") or message.get("tool_calls")
            ):
                raise ValueError("Missing assistant response")
            if self.config.role == "put" and message.get("tool_calls"):
                raise ValueError("PUT must select a user act, not execute tools")
            if self.config.role == "put":
                from .put_protocol import parse_act, SOL_PUT_FORMAT

                receipt["response_validation"] = "finite_put_user_act_json"
                act = parse_act(message.get("content", ""))
                if json.loads(self.config.options_json).get(
                    "response_format"
                ) == SOL_PUT_FORMAT and set(act) != {"act", "style"}:
                    raise ValueError("Strict PUT schema requires both act and style")
            receipt["status"] = "accepted"
            return message
        except Exception as exc:
            self.stopped = True
            receipt.update(status="failed", error_type=type(exc).__name__)
            raise ModelFailure(
                "API request failed; inspect receipt; no retry: " + type(exc).__name__
            ) from None
        finally:
            receipt["duration_seconds"] = time.monotonic() - started
            receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
            write_new(folder / "receipt.json", receipt)
            if request_id is not None:
                from .ledger import finish

                finish(ledger, request_id, receipt)

    def close(self):
        self.http.close()
