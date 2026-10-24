"""Per-episode stateless Responses history, including encrypted reasoning items."""

from copy import deepcopy
import json


class ResponsesHistory:
    def __init__(self):
        self.items = []
        self.chat_prefix = []
        self.expected_assistant = None

    def payload(self, messages, config, tools):
        if messages[: len(self.chat_prefix)] != self.chat_prefix:
            raise ValueError("Episode response history changed")
        delta = messages[len(self.chat_prefix) :]
        if self.expected_assistant is not None:
            if not delta or delta[0] != self.expected_assistant:
                raise ValueError("Response output linkage changed")
            delta = delta[1:]
        new = []
        for message in delta:
            if message["role"] == "tool":
                new.append(
                    {
                        "type": "function_call_output",
                        "call_id": message["tool_call_id"],
                        "output": message["content"],
                    }
                )
            elif message["role"] in {"system", "user"}:
                new.append(
                    {
                        "role": "developer" if message["role"] == "system" else "user",
                        "content": message["content"],
                    }
                )
            else:
                raise ValueError("Unexpected unlinked assistant message")
        options = json.loads(config.options_json)
        payload = {
            "model": config.model,
            "input": deepcopy(self.items) + new,
            "max_output_tokens": config.max_tokens,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {
                "effort": options["reasoning_effort"],
                "context": "all_turns",
            },
        }
        if options["reasoning_effort"] == "none":
            payload["reasoning"].pop("context")
        if tools:
            payload.update(
                tools=[
                    {"type": "function", **t["function"], "strict": False}
                    for t in tools
                ],
                tool_choice="required",
                parallel_tool_calls=True,
            )
        if options.get("response_format"):
            payload["text"] = {"format": options["response_format"]}
        return payload

    def accept(self, body, payload, messages):
        if (
            body.get("status") != "completed"
            or body.get("error")
            or body.get("incomplete_details")
        ):
            raise ValueError("Incomplete Responses output")
        output = body.get("output")
        if not isinstance(output, list):
            raise ValueError("Missing Responses items")
        calls, text = [], []
        for item in output:
            if item["type"] == "function_call":
                calls.append(
                    {
                        "id": item["call_id"],
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": item["arguments"],
                        },
                    }
                )
            elif item["type"] == "message":
                text.extend(
                    c["text"] for c in item["content"] if c["type"] == "output_text"
                )
            elif item["type"] != "reasoning":
                raise ValueError("Unexpected Responses item type")
        message = {"role": "assistant", "content": "\n".join(text)}
        if calls:
            message["tool_calls"] = calls
        if not calls and not text:
            raise ValueError("Missing assistant output")
        self.items = deepcopy(payload["input"]) + deepcopy(output)
        self.chat_prefix = deepcopy(messages)
        self.expected_assistant = deepcopy(message)
        return message


def normalized_usage(usage):
    if not usage:
        return usage
    result = deepcopy(usage)
    for original, normalized in (
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
        ("input_tokens_details", "prompt_tokens_details"),
        ("output_tokens_details", "completion_tokens_details"),
    ):
        if original in usage:
            result[normalized] = deepcopy(usage[original])
    return result
