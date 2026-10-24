"""Mixed-provider wire format, explicit identity routing and usage repricing."""

import json

import httpx
import pytest

from matraix.journeys.api import APIClient, ModelConfig, ModelFailure, load_secret
from matraix.journeys.launch import configure
from matraix.journeys.pricing import pricing_for, usage_cost


def test_two_key_file_routes_each_provider_without_logging(tmp_path, monkeypatch):
    keys = tmp_path / "private.txt"
    keys.write_text("deepseek-offline-only\n\nopenai-offline-only\n")
    for role, host, expected in (
        ("sut", "api.openai.com", "openai-offline-only"),
        ("put", "api.deepseek.com", "deepseek-offline-only"),
    ):
        monkeypatch.delenv("JOURNEY_" + role.upper() + "_API_KEY", raising=False)
        monkeypatch.setenv("JOURNEY_" + role.upper() + "_API_KEY_FILE", str(keys))
        monkeypatch.setenv("JOURNEY_" + role.upper() + "_BASE_URL", "https://" + host)
        name = load_secret(role)
        import os

        assert os.environ[name] == expected


def test_mixed_provider_single_key_fails_before_dispatch(tmp_path):
    key = tmp_path / "key"
    key.write_text("single-key-only")
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "sut": {"base_url": "https://api.openai.com/v1"},
                "put": {"base_url": "https://api.deepseek.com"},
            }
        )
    )
    with pytest.raises(ValueError, match="Mixed-provider"):
        configure(config, key_file=key)


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6.1-sol"])
def test_sol_responses_wire_and_reasoning_history_are_preserved(
    model, tmp_path, monkeypatch
):
    monkeypatch.setenv("OFFLINE_ONLY_KEY", "offline-key")
    seen = []

    def handler(req):
        body = json.loads(req.content)
        assert body["model"] == model
        assert req.url.path == "/v1/responses"
        assert body["max_output_tokens"] == 16384 and "max_tokens" not in body
        assert body["reasoning"] == {"effort": "medium", "context": "all_turns"}
        assert body["parallel_tool_calls"] is True and body["store"] is False
        assert body["tools"][0]["strict"] is False
        if seen:
            assert any(
                i.get("encrypted_content") == "opaque-reasoning" for i in body["input"]
            )
            assert any(
                i.get("type") == "function_call_output" and i["call_id"] == "a"
                for i in body["input"]
            )
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "id": "rs",
                        "type": "reasoning",
                        "summary": [],
                        "encrypted_content": "opaque-reasoning",
                    },
                    {
                        "id": "fc",
                        "type": "function_call",
                        "call_id": "a",
                        "name": "get_home_state",
                        "arguments": "{}",
                    },
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 30,
                    "total_tokens": 130,
                    "output_tokens_details": {"reasoning_tokens": 20},
                },
            },
        )

    client = APIClient(
        ModelConfig(
            "sut",
            "https://api.openai.com/v1",
            model,
            "OFFLINE_ONLY_KEY",
            max_tokens=16384,
            options_json='{"reasoning_effort":"medium"}',
        ),
        tmp_path / "wire",
        transport=httpx.MockTransport(handler),
    )
    messages = [{"role": "user", "content": "offline"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_home_state",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    message = client.call(messages, tools=tools)
    messages += [message, {"role": "tool", "tool_call_id": "a", "content": "{}"}]
    client.call(messages, tools=tools)
    client.close()
    assert len(seen) == 2
    receipt = json.loads((tmp_path / "wire/0002/receipt.json").read_text())
    assert receipt["usage"]["completion_tokens"] == 30
    assert receipt["usage"]["completion_tokens_details"]["reasoning_tokens"] == 20


def test_sol_reasoning_setting_cannot_silently_default():
    with pytest.raises(ValueError, match="explicit"):
        ModelConfig("sut", "https://api.openai.com/v1", "gpt-5.6-sol", "KEY").validate()


@pytest.mark.parametrize(
    "content",
    [
        '{"act":',
        "[]",
        '{"act":"approve"}',
        '{"act":"continue","target_soc":0}',
        '{"act":"continue","style":"angry"}',
    ],
)
def test_http200_stop_is_not_accepted_as_valid_put_json(content, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PUT_KEY", "offline-only")
    sent = []

    def handler(req):
        sent.append(req)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 3,
                    "total_tokens": 103,
                },
            },
        )

    client = APIClient(
        ModelConfig("put", "https://offline.invalid", "mock", "SYNTHETIC_PUT_KEY"),
        tmp_path / "wire",
        transport=httpx.MockTransport(handler),
    )
    for _ in range(2):
        with pytest.raises(ModelFailure):
            client.call([{"role": "user", "content": "offline"}])
    client.close()
    assert len(sent) == 1
    receipt = json.loads((tmp_path / "wire/0001/receipt.json").read_text())
    assert receipt["status"] == "failed" and receipt["usage_unknown"] is False
    assert receipt["usage"]["total_tokens"] == 103


def test_sol_cache_writes_are_not_double_billed_and_reasoning_not_added_again():
    prices = pricing_for(
        {"model": "gpt-5.6-sol", "base_url": "https://api.openai.com/v1"}
    )
    usage = {
        "prompt_tokens": 12000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 4000, "cache_write_tokens": 7000},
        "completion_tokens_details": {"reasoning_tokens": 80},
    }
    cost = usage_cost(usage, prices, "off_peak")
    assert (
        cost["lower"]
        == cost["upper"]
        == pytest.approx((4000 * 0.4 + 7000 * 5 + 1000 * 4 + 100 * 20) / 1e6)
    )
    del usage["prompt_tokens_details"]["cache_write_tokens"]
    bounded = usage_cost(usage, prices, "off_peak")
    assert bounded["lower"] < cost["lower"] < bounded["upper"]


def test_mixed_role_pricing_and_unknown_usage_stay_explicit():
    ds = pricing_for(
        {"model": "deepseek-flash", "base_url": "https://api.deepseek.com"}
    )
    assert usage_cost({}, ds, "peak") is None
    u = {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 900, "completion_tokens": 10}
    assert usage_cost(u, ds, "peak")["lower"] == pytest.approx(
        2 * usage_cost(u, ds, "off_peak")["lower"]
    )
    assert (
        pricing_for({"model": "gpt-5.6-sol", "base_url": "https://unverified.invalid"})
        is None
    )


def test_resource_report_prices_each_role_from_its_own_provider(tmp_path):
    from matraix.journeys.cohort import write_new
    from matraix.journeys.resources import report

    write_new(
        tmp_path / "plan/plan.json",
        {
            "purpose": "pilot",
            "planned_episodes": 1,
            "cases": [
                {
                    "id": "case",
                    "domain": "car",
                    "task": "J1",
                    "source_persona_id": "fixture",
                    "block": 1,
                    "cohort": "C1",
                    "boundary": False,
                }
            ],
        },
    )
    write_new(
        tmp_path / "completion.json",
        {"status": "stopped", "concurrency": 2, "ledger": {}},
    )
    write_new(
        tmp_path / "settings.json",
        {
            "sut": {"base_url": "https://api.openai.com/v1", "model": "gpt-5.6-sol"},
            "put": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
        },
    )
    write_new(
        tmp_path / "records/sid/binding.json",
        {"sessionId": "sid", "case": {"id": "case"}},
    )
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 50},
    }
    write_new(
        tmp_path / "sut-api-records/sid/0001/receipt.json",
        {"role": "sut", "usage": usage},
    )
    write_new(
        tmp_path / "actor/case/put/0001/receipt.json", {"role": "put", "usage": usage}
    )
    result = report(tmp_path)
    group = result["task_groups"][0]
    expected = sum(
        usage_cost(usage, result["pricing_scenarios"][role], "off_peak")["lower"]
        for role in ("sut", "put")
    )
    assert group["reported_usage_cost_scenarios_usd"]["off_peak"][
        "lower"
    ] == pytest.approx(expected)
    assert group["api_requests_sent"] == 2 and "planning_scenarios" not in result


@pytest.mark.parametrize(
    "model,effort",
    [("gpt-5.6-sol", "none"), ("gpt-6.1-sol", "low")],
)
@pytest.mark.parametrize(
    "content,valid",
    [
        ('{"act":"continue","style":"balanced"}', True),
        ('{"act":"continue"}', False),
        ('{"act":', False),
    ],
)
def test_all_sol_put_strict_schema_and_no_thinking(
    model, effort, content, valid, tmp_path, monkeypatch
):
    from matraix.journeys.put_protocol import SOL_PUT_FORMAT

    monkeypatch.setenv("OFFLINE_SOL_KEY", "offline-only")

    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/v1/responses"
        assert body["model"] == model
        assert body["reasoning"] == (
            {"effort": "none"}
            if effort == "none"
            else {"effort": effort, "context": "all_turns"}
        )
        assert body["text"]["format"] == SOL_PUT_FORMAT
        assert "tools" not in body and body["store"] is False
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "id": "msg",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 10,
                    "total_tokens": 1010,
                },
            },
        )

    config = ModelConfig(
        "put",
        "https://api.openai.com/v1",
        model,
        "OFFLINE_SOL_KEY",
        max_tokens=512,
        options_json=json.dumps(
            {"reasoning_effort": effort, "response_format": SOL_PUT_FORMAT}
        ),
    )
    client = APIClient(
        config, tmp_path / "wire", transport=httpx.MockTransport(handler)
    )
    if valid:
        assert (
            client.call([{"role": "user", "content": "json act"}])["content"] == content
        )
    else:
        with pytest.raises(ModelFailure):
            client.call([{"role": "user", "content": "json act"}])
    client.close()


@pytest.mark.parametrize("role", ["sut", "put"])
@pytest.mark.parametrize("effort", [None, "none", "minimal"])
def test_sol61_rejects_unsupported_effort_before_dispatch(role, effort):
    with pytest.raises(ValueError, match="explicit supported"):
        ModelConfig(
            role,
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            "OFFLINE_KEY",
            options_json=json.dumps({"reasoning_effort": effort}) if effort else "{}",
        ).validate()


def test_sol61_usage_prices_cache_read_write_and_reasoning_once():
    prices = pricing_for(
        {"model": "gpt-6.1-sol", "base_url": "https://api.openai.com/v1"}
    )
    u = {
        "prompt_tokens": 12000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 4000, "cache_write_tokens": 7000},
        "completion_tokens_details": {"reasoning_tokens": 80},
    }
    c = usage_cost(u, prices, "off_peak")
    assert (
        c["lower"]
        == c["upper"]
        == pytest.approx((4000 * 0.1 + 7000 * 2.5 + 1000 * 2 + 100 * 10) / 1e6)
    )
    u["prompt_tokens"] = 300000
    long = usage_cost(u, prices, "peak")
    assert long["lower"] == pytest.approx(
        ((4000 * 0.1 + 7000 * 2.5 + 289000 * 2) * 2 + 100 * 10 * 1.5) / 1e6
    )


def test_openai_put_selects_second_key_from_explicit_provider_file(
    tmp_path, monkeypatch
):
    keys = tmp_path / "keys"
    keys.write_text("deepseek-offline\n\nopenai-offline\n")
    monkeypatch.delenv("JOURNEY_PUT_API_KEY", raising=False)
    monkeypatch.setenv("JOURNEY_PUT_API_KEY_FILE", str(keys))
    monkeypatch.setenv("JOURNEY_PUT_BASE_URL", "https://api.openai.com/v1")
    import os

    assert load_secret("put") == "JOURNEY_PUT_API_KEY"
    assert os.environ["JOURNEY_PUT_API_KEY"] == "openai-offline"
