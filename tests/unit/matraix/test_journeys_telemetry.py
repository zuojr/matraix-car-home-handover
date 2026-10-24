"""Memory instrumentation, credential-safe headers and eight-worker guards."""

import json
import time
from pathlib import Path

import httpx
import pytest

from matraix.journeys.api import APIClient, ModelConfig, ModelFailure
from matraix.journeys.launch import configure
from matraix.journeys.telemetry import MemorySampler, descendants, process_sample


def test_process_tree_excludes_other_roots_and_cycles():
    table = {1: (0, 10), 2: (1, 20), 3: (2, 30), 4: (0, 40), 5: (6, 50), 6: (5, 60)}
    assert descendants(table, 1) == {1, 2, 3}
    assert descendants(table, 99) == set()


def test_real_current_process_memory_is_measured():
    result = process_sample()
    assert result["rss_sum_bytes"] > 0
    assert result["processes"] >= 1
    assert result["host_available_bytes"] > 0


def test_sampler_persists_nonzero_peak_and_stops_thread(tmp_path):
    out = tmp_path / "run"
    with MemorySampler(out, interval=0.02) as sampler:
        out.mkdir()
        time.sleep(0.06)
    row = json.loads((out / "memory.json").read_text())
    assert row["sampled_peak_rss_sum_bytes"] > 0
    assert row["minimum_host_available_bytes"] > 0
    assert len(row["samples"]) >= 2
    assert not row["measurement_errors"] and row["sampler_thread_stopped"]
    assert not sampler.thread.is_alive()


def test_observer_failure_is_unknown_not_zero_and_existing_bundle_untouched(
    tmp_path, monkeypatch
):
    from matraix.journeys import telemetry

    def unavailable():
        raise OSError("offline instrumentation failure")

    monkeypatch.setattr(telemetry, "process_sample", unavailable)
    out = tmp_path / "new"
    with MemorySampler(out):
        out.mkdir()
    row = json.loads((out / "memory.json").read_text())
    assert row["sampled_peak_rss_sum_bytes"] is None and row["measurement_errors"]
    before = (out / "memory.json").read_bytes()
    with MemorySampler(out):
        pass
    assert (out / "memory.json").read_bytes() == before


@pytest.mark.parametrize("status", [200, 429])
def test_rate_headers_whitelisted_even_for_failure(tmp_path, monkeypatch, status):
    monkeypatch.setenv("OFFLINE_HEADER_KEY", "offline-secret")

    def handler(req):
        return httpx.Response(
            status,
            headers={
                "x-ratelimit-limit-tokens": "1000000",
                "x-ratelimit-remaining-tokens": "800000",
                "retry-after": "2",
                "set-cookie": "offline-secret",
                "authorization": "offline-secret",
            },
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"act":"continue"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    client = APIClient(
        ModelConfig("put", "https://offline.invalid", "mock", "OFFLINE_HEADER_KEY"),
        tmp_path / "wire",
        transport=httpx.MockTransport(handler),
    )
    try:
        if status == 429:
            with pytest.raises(ModelFailure):
                client.call([{"role": "user", "content": "offline"}])
        else:
            client.call([{"role": "user", "content": "offline"}])
    finally:
        client.close()
    receipt = json.loads((tmp_path / "wire/0001/receipt.json").read_text())
    assert receipt["rate_limit_headers"] == {
        "x-ratelimit-limit-tokens": "1000000",
        "x-ratelimit-remaining-tokens": "800000",
        "retry-after": "2",
    }
    assert "offline-secret" not in json.dumps(receipt)


def test_eight_worker_config_preserves_model_and_episode_budgets():
    repo = Path(__file__).resolve().parents[3]
    configs, limits = configure(
        repo / "configs/journeys/sol61-8.example.json", need_credentials=False
    )
    assert limits["concurrency"] == 8
    assert limits["max_total_api_requests"] == 2000
    assert limits["max_sut_calls_per_case"] == 160 and limits["max_persona_turns"] == 64
    assert configs["sut"].model == configs["put"].model == "gpt-6.1-sol"
    assert json.loads(configs["sut"].options_json)["reasoning_effort"] == "medium"
    assert json.loads(configs["put"].options_json)["reasoning_effort"] == "low"
