"""Complete native identity coverage, stable prefixes and cross-thread stop/caps."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile

import pytest
import yaml

from matraix.journeys import cohort
from matraix.journeys.identity import complete_parts
from matraix.journeys.ledger import connect, reserve, finish, summary, is_stopped
from matraix.journeys.prompts import put_messages, public_view

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def complete_plan(tmp_path):
    (REPO / ".cache").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=REPO / ".cache", prefix="full-profile-"
    ) as directory:
        pool = Path(directory)
        source = REPO / "persona/datasets/matraix-persona-dev-sample/persona_0163.yaml"
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        (pool / source.name).write_bytes(source.read_bytes())
        cohort.write_new(
            pool / "manifest.json",
            {
                "kind": "offline-fixture-only",
                "personas": [
                    {
                        "persona_id": raw["persona_id"],
                        "source": raw["source"],
                        "path": (pool / source.name).relative_to(REPO).as_posix(),
                    }
                ],
            },
        )
        plan_path = tmp_path / "plan"
        cohort.prepare(
            REPO,
            {d: pool for d in cohort.DOMAINS},
            {d: [raw["persona_id"]] for d in cohort.DOMAINS},
            plan_path,
            purpose="validation",
            fixture=True,
        )
        yield cohort.load_plan(plan_path), plan_path


def test_complete_1290_identity_is_partitioned_once_and_prefix_is_condition_independent(
    complete_plan,
):
    plan, path = complete_plan
    cases = [
        next(
            c
            for c in plan["cases"]
            if c["domain"] == "car" and c["cohort"] == condition
        )
        for condition in cohort.CONDITIONS
    ]
    prefixes = []
    for case in cases:
        narrative, residual, coverage = complete_parts(case, plan, path)
        original = case["native_persona"]["dimensions"]
        assert len(original) == coverage["source_dimensions"] == 1290
        rendered = set(coverage["narrative_dimensions"])
        assert (
            rendered.isdisjoint(residual)
            and rendered | residual.keys() == original.keys()
        )
        assert residual == {k: original[k] for k in residual}
        messages, audit = put_messages(case, plan, path)
        assert len(messages) == 3 and "Who you are" in narrative
        card = json.loads(messages[2]["content"])
        assert card["current_facts"] == case["facts"]
        assert "attributes" not in card and "instruction" not in card
        assert audit["initial_prompt_characters"] < audit["previous_layout_characters"]
        assert audit["source_dimensions_sha256"] == cohort.digest(original)
        prefixes.append(audit["persona_prefix_sha256"])
    assert len(set(prefixes)) == 1


def test_persona_truncation_fails_before_any_model_call(complete_plan, monkeypatch):
    plan, path = complete_plan
    monkeypatch.setenv("MATRAIX_PERSONA_PROFILE_MAX_CHARS", "200")
    with pytest.raises(ValueError, match="Full persona"):
        put_messages(plan["cases"][0], plan, path)


def test_public_view_keeps_visible_feedback_without_duplicate_wire_turn():
    view = {
        "reply": "x",
        "pendingUserRequest": {"facts": {"soc": 60}},
        "terminal": False,
        "sessionId": "id",
        "turn": {"assistantReply": "x", "userMessage": "already in history"},
    }
    assert public_view(view) == {
        "reply": "x",
        "pendingUserRequest": {"facts": {"soc": 60}},
        "terminal": False,
    }


@pytest.mark.parametrize("threads", [4, 8])
def test_atomic_request_cap_under_four_or_eight_threads(tmp_path, threads):
    ledger = tmp_path / "ledger.sqlite3"
    connect(ledger).close()

    def attempt(n):
        try:
            return reserve(ledger, "sut", str(n), 7)
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=threads) as pool:
        ids = list(pool.map(attempt, range(20)))
    assert len([i for i in ids if i is not None]) == 7
    assert summary(ledger)["requests"] == 7


def test_failed_request_blocks_other_roles_without_cancelling_inflight_accounting(
    tmp_path,
):
    path = tmp_path / "ledger.sqlite3"
    a, b = reserve(path, "sut", "a", 10), reserve(path, "put", "b", 10)
    finish(
        path,
        a,
        {"role": "sut", "status": "failed", "usage": None, "usage_unknown": True},
    )
    assert is_stopped(path)
    with pytest.raises(RuntimeError, match="stopped"):
        reserve(path, "put", "not-sent", 10)
    finish(
        path,
        b,
        {
            "role": "put",
            "status": "accepted",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
            "usage_unknown": False,
        },
    )
    result = summary(path)
    assert result["requests"] == 2 and result["inflight_or_unknown"] == 0
    assert result["usage_unknown_requests"] == 1
    assert result["roles"]["put"]["cache_hit_tokens"] == 40
    assert result["roles"]["put"]["cache_miss_tokens"] == 60


def test_put_trace_ids_are_unique_without_adding_nonce_to_cacheable_input(
    tmp_path, monkeypatch
):
    import httpx
    from matraix.journeys.api import APIClient, ModelConfig

    monkeypatch.setenv("OFFLINE_KEY", "not-a-real-key")
    observed = []

    def handle(request):
        observed.append(
            (request.headers["X-Client-Request-Id"], json.loads(request.content))
        )
        return httpx.Response(
            200,
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
                "usage": {"total_tokens": 1},
            },
        )

    for name in ("first", "second"):
        client = APIClient(
            ModelConfig("put", "https://offline.invalid", "mock-put", "OFFLINE_KEY"),
            tmp_path / name / "put",
            transport=httpx.MockTransport(handle),
        )
        client.call([{"role": "system", "content": "identical reusable prefix"}])
        client.close()
    assert observed[0][0] != observed[1][0]
    assert observed[0][1] == observed[1][1]
