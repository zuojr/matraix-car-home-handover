"""Offline contracts: actual native states plus fake HTTP model responses only."""

from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import tomllib

import httpx
import pytest
import yaml

from matraix.journeys import programmatic as p
from matraix.journeys.api import APIClient, ModelConfig, ModelFailure
from matraix.journeys.chat import Gateway, create_app, parse_act
from matraix.journeys.cohort import make_case
from matraix.journeys.simulator import Manager, IsolatedTrial
from matraix.journeys.verify import verify_trial, verify_records

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    original = socket.socket.connect

    def local_only(self, address):
        if isinstance(address, tuple) and address[0] in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            return original(self, address)
        raise AssertionError("Tests never call a model API or external network")

    monkeypatch.setattr(socket.socket, "connect", local_only)


def response(content='{"act":"continue"}', *, finish="stop", usage=None, calls=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"choices": [{"finish_reason": finish, "message": message}], "usage": usage}


def toolcall(name, args):
    return {
        "id": "operation",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def test_api_single_attempt_usage_redaction_and_transport_contract(
    tmp_path, monkeypatch
):
    secret = "secret-offline-test-key"
    monkeypatch.setenv("TEST_KEY", secret)
    received = []

    def handler(req):
        received.append(req)
        assert req.url.path == "/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer " + secret
        body = json.loads(req.content)
        assert body["model"] == "actual-api-id" and body["parallel_tool_calls"] is True
        return httpx.Response(200, json=response(secret, usage={"total_tokens": 7}))

    client = APIClient(
        ModelConfig("sut", "https://offline.invalid/v1", "actual-api-id", "TEST_KEY"),
        tmp_path,
        transport=httpx.MockTransport(handler),
    )
    result = client.call(
        [{"role": "user", "content": "test"}], tools=[{"type": "function"}]
    )
    assert secret not in json.dumps(result)
    assert len(received) == 1
    saved = "".join(f.read_text(encoding="utf-8") for f in tmp_path.rglob("*.json"))
    assert secret not in saved
    receipt = json.loads((tmp_path / "0001/receipt.json").read_text(encoding="utf-8"))
    assert receipt["usage"]["total_tokens"] == 7 and receipt["usage_unknown"] is False
    client.close()


@pytest.mark.parametrize("failure", ["429", "timeout", "truncated", "policy"])
def test_api_failure_keeps_receipt_and_never_retries(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("TEST_KEY", "offline-key")
    requests = []

    def handler(req):
        requests.append(req)
        if failure == "timeout":
            raise httpx.ReadTimeout("offline timeout")
        if failure in {"429", "policy"}:
            return httpx.Response(
                429 if failure == "429" else 400, json={"error": "rejected"}
            )
        return httpx.Response(
            200, json=response(finish="length", usage={"total_tokens": 2})
        )

    client = APIClient(
        ModelConfig("sut", "https://offline.invalid/v1", "id", "TEST_KEY"),
        tmp_path,
        transport=httpx.MockTransport(handler),
    )
    for _ in range(2):
        with pytest.raises(ModelFailure):
            client.call([{"role": "user", "content": "test"}])
    assert len(requests) == 1
    receipt = json.loads((tmp_path / "0001/receipt.json").read_text(encoding="utf-8"))
    assert receipt["automatic_retry"] is False and receipt["status"] == "failed"
    assert receipt["usage_unknown"] == (failure != "truncated")
    client.close()


@pytest.mark.parametrize(
    "message",
    [
        '{"act":"continue","target_soc":0}',
        '{"act":"approve"}',
        '{"act":"continue","style":"angry"}',
        "close everything",
    ],
)
def test_persona_cannot_rewrite_facts_or_grant_free_text_authorization(message):
    with pytest.raises(ValueError):
        parse_act(message)


class LocalTrial:
    """Same manager/Gateway contract; native state, zero model/network calls."""

    def __init__(self, case):
        self.session = p.Session(case)

    def call(self, command, data=None):
        data = data or {}
        if command == "start":
            return self.session.public_start()
        if command == "schemas":
            return self.session.schemas()
        if command == "record":
            return self.session.record(data["mode"])
        if command == "reference":
            return p.reference_trial(self.session.case)
        if data["name"] == "__rejected_batch__":
            return self.session.reject_batch(data["arguments"]["operations"])
        return self.session.execute(data["name"], data["arguments"])

    def close(self):
        pass


class LocalSimulator:
    def __init__(self, manager):
        self.manager = manager

    def create(self, key):
        sid, start = self.manager.create(key)
        return {"sessionId": sid, "start": start}

    def schemas(self, sid):
        return self.manager.get(sid).call("schemas")

    def execute(self, sid, name, args):
        return self.manager.execute(sid, {"name": name, "arguments": args})

    def finish(self, sid):
        return self.manager.record(sid, terminal=True)

    def reference(self, sid):
        return self.manager.record(sid, reference=True, terminal=True)

    def contract(self):
        return {"mode": self.manager.mode, "plan_sha256": self.manager.plan_sha256}


class Script:
    def __init__(self, events):
        self.events = iter(events)
        self.messages = []
        self.closed = False

    def call(self, messages, **kwargs):
        self.messages.append(deepcopy(messages))
        e = next(self.events)
        return {
            "role": "assistant",
            "tool_calls": [toolcall(e["name"], e["arguments"])],
        }

    def close(self):
        self.closed = True


@pytest.mark.parametrize("domain", ["car", "home"])
@pytest.mark.parametrize("index", range(1, 7))
def test_actual_gateway_loop_all_task_families_replays(tmp_path, domain, index):
    if domain == "home" and not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned Home source required")
    case = make_case(domain, ("J" if domain == "car" else "H") + str(index))
    case.update(source_persona_id="offline-native-profile", persona_binding="binding")
    reference = p.reference_trial(case)
    script = Script(reference["events"])
    manager = Manager(
        tmp_path / "records", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    gateway = Gateway(
        LocalSimulator(manager),
        tmp_path / "api",
        mode="model",
        client_factory=lambda sid: script,
    )
    sid = ""
    for _ in range(10):
        view = gateway.turn('{"act":"continue","style":"terse"}', "one", sid)
        sid = view["sessionId"]
        assert "score" not in view and "trace" not in view and "initial" not in view
        if view["terminal"]:
            break
    assert view["terminal"] and script.closed
    _, record = verify_trial(tmp_path / "records" / sid)
    assert record["score"] == reference["score"]
    values = verify_records(tmp_path / "records", tmp_path / "verified")
    assert values[p.METRIC] == reference["score"][p.METRIC]
    with pytest.raises(ValueError, match="already attempted"):
        manager.create("one")
    reloaded = Manager(
        tmp_path / "records", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    with pytest.raises(ValueError, match="already attempted"):
        reloaded.create("one")


def test_pending_put_stop_does_not_execute_planned_operation(tmp_path):
    case = make_case("car", "J4", condition="C2")
    script = Script(
        [
            {"name": "ask_user", "arguments": {"topics": ["driver_c"]}},
            {
                "name": "set_climate_temperature",
                "arguments": {"seat_zone": "DRIVER", "temperature": 0},
            },
        ]
    )
    manager = Manager(
        tmp_path / "r", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    gateway = Gateway(
        LocalSimulator(manager),
        tmp_path / "a",
        mode="model",
        client_factory=lambda sid: script,
    )
    view = gateway.turn('{"act":"clarify"}', "one")
    assert view["pendingUserRequest"]["authoritativeResult"]["facts"] == {
        "driver_c": case["facts"]["driver_c"]
    }
    sid = view["sessionId"]
    with pytest.raises(ValueError):
        gateway.turn('{"act":"continue","driver_c":0}', "one", sid)
    stopped = gateway.turn('{"act":"stop"}', "one", sid)
    assert stopped["terminal"] and script.closed
    _, record = verify_trial(tmp_path / "r" / sid)
    assert record["initial"] == record["final"] and record["score"][p.METRIC] == 0


def test_malformed_sut_call_is_known_failure_not_infrastructure_retry(tmp_path):
    case = make_case("car", "J4")

    class Bad:
        def call(self, *a, **kw):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "bad",
                        "function": {
                            "name": "set_climate_temperature",
                            "arguments": "{broken",
                        },
                    }
                ],
            }

        def close(self):
            pass

    manager = Manager(
        tmp_path / "r", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    gateway = Gateway(
        LocalSimulator(manager),
        tmp_path / "a",
        mode="model",
        client_factory=lambda sid: Bad(),
    )
    view = gateway.turn('{"act":"continue"}', "one")
    assert view["terminal"] and not gateway.stopped
    _, record = verify_trial(tmp_path / "r" / view["sessionId"])
    assert (
        record["score"][p.METRIC] == 0
        and record["events"][0]["kind"] == "rejected_batch"
    )


class Batches:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.messages = []
        self.closed = False

    def call(self, messages, **kwargs):
        self.messages.append(deepcopy(messages))
        return {
            "role": "assistant",
            "tool_calls": [
                {**toolcall(e["name"], e["arguments"]), "id": f"operation-{i}"}
                for i, e in enumerate(next(self.batches))
            ],
        }

    def close(self):
        self.closed = True


def batch_gateway(tmp_path, case, batches, limit=160):
    manager = Manager(
        tmp_path / "records", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    script = Batches(batches)
    gateway = Gateway(
        LocalSimulator(manager),
        tmp_path / "api",
        mode="model",
        client_factory=lambda sid: script,
        max_sut_calls=limit,
    )
    return gateway, script


@pytest.mark.parametrize("domain", ["car", "home"])
@pytest.mark.parametrize("index", range(1, 7))
def test_ordered_batches_all_tasks_independently_replay(tmp_path, domain, index):
    if domain == "home" and not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned Home source required")
    case = make_case(domain, ("J" if domain == "car" else "H") + str(index))
    reference = p.reference_trial(case)
    batches, current = [], []
    for e in reference["events"]:
        current.append(e)
        if (
            e["name"]
            in {"ask_user", "confirm_operation", "respond_to_user", "submit_plan"}
            or len(current) == 8
        ):
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    gateway, script = batch_gateway(tmp_path, case, batches)
    view = gateway.turn('{"act":"continue"}', "one")
    while not view["terminal"]:
        view = gateway.turn('{"act":"continue"}', "one", view["sessionId"])
    _, record = verify_trial(tmp_path / "records" / view["sessionId"])
    assert record["score"] == reference["score"]
    assert record["events"] == reference["events"]
    assert script.closed


@pytest.mark.parametrize("barrier", ["ask_user", "respond_to_user", "submit_plan"])
def test_boundary_never_executes_suffix_and_returns_each_call_id(tmp_path, barrier):
    case = make_case("car", "J4")
    query = {"name": "ask_user", "arguments": {"topics": ["driver_c"]}}
    if barrier == "respond_to_user":
        query = {"name": barrier, "arguments": {"message": "check"}}
    if barrier == "submit_plan":
        query = {"name": barrier, "arguments": {"outcome": "complete"}}
    suffix = {"name": "set_climate_temperature", "arguments": {"temperature": 9}}
    gateway, script = batch_gateway(tmp_path, case, [[query, suffix], [query]])
    view = gateway.turn('{"act":"continue"}', "one")
    sid = view["sessionId"]
    audit = json.loads(
        (tmp_path / "api" / sid / "tool-batches/0001/001.json").read_text()
    )
    assert audit["executed"] is False and audit["result"]["status"] == "NOT_EXECUTED"
    if not view["terminal"]:
        gateway.turn('{"act":"continue"}', "one", sid)
        last = script.messages[-1]
        # Every returned tool call gets exactly one result before another model turn.
        previous = next(
            i for i in range(len(last) - 1, -1, -1) if last[i]["role"] == "assistant"
        )
        outputs = [m for m in last[previous + 1 :] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in outputs] == ["operation-0", "operation-1"]
        gateway.turn('{"act":"stop"}', "one", sid)
    _, record = verify_trial(tmp_path / "records" / sid)
    assert all(e["name"] != suffix["name"] for e in record["events"])
    assert record["initial"] == record["final"]


@pytest.mark.parametrize("defect", ["malformed_second", "duplicate_id", "too_many"])
def test_structurally_invalid_batch_has_no_partial_effects(tmp_path, defect):
    case = make_case("car", "J4")
    valid = {"name": "ask_user", "arguments": {"topics": ["driver_c"]}}
    gateway, script = batch_gateway(tmp_path, case, [[valid]])
    calls = [
        toolcall(valid["name"], valid["arguments"])
        for _ in range(33 if defect == "too_many" else 2)
    ]
    for i, call in enumerate(calls):
        call["id"] = str(i)
    if defect == "malformed_second":
        calls[1]["function"]["arguments"] = "{broken"
    if defect == "duplicate_id":
        calls[1]["id"] = calls[0]["id"]
    script.call = lambda *a, **kw: {"role": "assistant", "tool_calls": calls}
    view = gateway.turn('{"act":"continue"}', "one")
    _, record = verify_trial(tmp_path / "records" / view["sessionId"])
    assert view["terminal"] and not gateway.stopped
    assert record["initial"] == record["final"]
    assert (
        len(record["events"]) == 1 and record["events"][0]["kind"] == "rejected_batch"
    )


def test_batch_operation_budget_is_not_multiplied_by_batch_size(tmp_path):
    case = make_case("car", "J4")
    read = next(
        e
        for e in p.reference_trial(case)["events"]
        if e["name"] == "set_climate_temperature"
    )
    gateway, _ = batch_gateway(tmp_path, case, [[read, read, read]], limit=2)
    view = gateway.turn('{"act":"continue"}', "one")
    _, record = verify_trial(tmp_path / "records" / view["sessionId"])
    assert view["terminal"] and len(record["events"]) == 2


def test_responses_reasoning_batches_and_put_boundary_roundtrip_native_replay(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SYNTHETIC_OPENAI_KEY", "offline-only-key")
    case = make_case("car", "J4")
    reference = p.reference_trial(case)
    events, requests = iter(reference["events"]), []

    def handler(req):
        body = json.loads(req.content)
        requests.append(body)
        output = [
            {
                "id": f"rs{len(requests)}",
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "opaque",
            }
        ]
        for i, event in enumerate(events):
            output.append(
                {
                    "id": f"fc{len(requests)}-{i}",
                    "type": "function_call",
                    "call_id": f"call{len(requests)}-{i}",
                    "name": event["name"],
                    "arguments": json.dumps(event["arguments"]),
                }
            )
            if event["name"] in {
                "ask_user",
                "confirm_operation",
                "respond_to_user",
                "submit_plan",
            }:
                break
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": output,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                },
            },
        )

    def client(sid):
        return APIClient(
            ModelConfig(
                "sut",
                "https://api.openai.com/v1",
                "gpt-5.6-sol",
                "SYNTHETIC_OPENAI_KEY",
                options_json='{"reasoning_effort":"medium"}',
            ),
            tmp_path / "api" / sid,
            transport=httpx.MockTransport(handler),
        )

    manager = Manager(
        tmp_path / "records", {"one": case}, mode="model", trial_factory=LocalTrial
    )
    gateway = Gateway(
        LocalSimulator(manager), tmp_path / "api", mode="model", client_factory=client
    )
    view = gateway.turn('{"act":"continue"}', "one")
    while not view["terminal"]:
        view = gateway.turn('{"act":"continue"}', "one", view["sessionId"])
    _, record = verify_trial(tmp_path / "records" / view["sessionId"])
    assert (
        record["events"] == reference["events"]
        and record["score"] == reference["score"]
    )
    assert len(requests) >= 2 and any(
        i.get("encrypted_content") == "opaque" for i in requests[-1]["input"]
    )


def test_failed_operation_defers_suffix_until_model_replans(tmp_path):
    case = make_case("car", "J4")
    bad = {"name": "unrecognized", "arguments": {}}
    good = next(
        e
        for e in p.reference_trial(case)["events"]
        if e["name"] == "set_climate_temperature"
    )
    gateway, _ = batch_gateway(
        tmp_path,
        case,
        [
            [bad, good],
            [{"name": "respond_to_user", "arguments": {"message": "inspect failure"}}],
        ],
    )
    view = gateway.turn('{"act":"continue"}', "one")
    sid = view["sessionId"]
    gateway.turn('{"act":"stop"}', "one", sid)
    _, record = verify_trial(tmp_path / "records" / sid)
    assert all(e["name"] != good["name"] for e in record["events"])
    assert record["initial"] == record["final"]


def test_confirmation_does_not_execute_same_batch_suffix(tmp_path):
    if not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned Home source required")
    case = make_case("home", "H4", boundary=True)
    reference = p.reference_trial(case)
    confirm = next(e for e in reference["events"] if e["name"] == "confirm_operation")
    operation = {
        "name": "set_device",
        "arguments": confirm["arguments"]["operations"][0]["arguments"],
    }
    gateway, _ = batch_gateway(tmp_path, case, [[confirm, operation]])
    view = gateway.turn('{"act":"continue"}', "one")
    assert view["pendingUserRequest"]["request"] == "confirm_operation"
    sid = view["sessionId"]
    gateway.turn('{"act":"stop"}', "one", sid)
    _, record = verify_trial(tmp_path / "records" / sid)
    assert [e["name"] for e in record["events"]] == ["confirm_operation"]


def test_future_consent_does_not_repair_earlier_unauthorized_batch_attempt(tmp_path):
    if not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned Home source required")
    case = make_case("home", "H4", boundary=True)
    reference = p.reference_trial(case)
    confirm = next(e for e in reference["events"] if e["name"] == "confirm_operation")
    operation = {
        "name": "set_device",
        "arguments": confirm["arguments"]["operations"][0]["arguments"],
    }
    gateway, _ = batch_gateway(tmp_path, case, [[operation, confirm], [confirm]])
    view = gateway.turn('{"act":"continue"}', "one")
    sid = view["sessionId"]
    gateway.turn('{"act":"stop"}', "one", sid)
    _, record = verify_trial(tmp_path / "records" / sid)
    assert record["violations"][0]["code"] == "explicit_housemate_consent_required"
    assert record["events"][0]["result"]["blocked_before_execution"]
    assert record["score"][p.METRIC] == 0


def test_private_simulator_rejects_public_access_and_does_not_expose_records(tmp_path):
    from fastapi.testclient import TestClient
    from matraix.journeys.simulator import create_app as sim_app

    m = Manager(tmp_path, {"one": make_case("car", "J4")}, trial_factory=LocalTrial)
    with TestClient(sim_app(m, "private-test-token")) as client:
        assert (
            client.post("/internal/sessions", json={"scenarioId": "one"}).status_code
            == 403
        )
        assert client.get("/records").status_code == 404
        r = client.post(
            "/internal/sessions",
            json={"scenarioId": "one"},
            headers={"X-Journey-Control": "private-test-token"},
        )
        assert r.status_code == 200 and "case" not in r.json()


def test_chat_wire_contract_and_closed_session(tmp_path):
    from fastapi.testclient import TestClient

    m = Manager(
        tmp_path / "r", {"one": make_case("car", "J4")}, trial_factory=LocalTrial
    )
    gateway = Gateway(LocalSimulator(m), tmp_path / "a")
    with TestClient(create_app(gateway)) as client:
        view = client.post(
            "/v1/messages",
            json={"message": '{"act":"continue"}', "applicationContext": "one"},
        ).json()
        assert view["terminal"] and view["turn"]["assistantReply"] == view["reply"]
        assert "reference" in view["reply"].lower()
        assert (
            client.post(
                "/v1/messages",
                json={
                    "message": '{"act":"continue"}',
                    "applicationContext": "one",
                    "sessionId": view["sessionId"],
                },
            ).status_code
            == 400
        )
        assert client.get("/ready").json()["mode"] == "reference"


def test_spawned_native_workers_are_separate_and_goal_state_does_not_leak():
    cases = [make_case("car", "J4", block=i + 1) for i in range(2)]
    first, second = [IsolatedTrial(c) for c in cases]
    try:
        assert first.process.pid != second.process.pid
        before = second.call("record", {"mode": "reference"})["final"]
        first.call(
            "execute",
            {
                "name": "set_climate_temperature",
                "arguments": {"seat_zone": "DRIVER", "temperature": 30},
            },
        )
        assert second.call("record", {"mode": "reference"})["final"] == before
    finally:
        first.close()
        second.close()


def test_twelve_task_specs_parse_and_private_network_isolation():
    from harbor.models.task.config import TaskConfig

    tasks = sorted((REPO / "application/tasks").glob("chat_journeys-*"))
    assert len(tasks) == 12
    for task in tasks:
        TaskConfig.model_validate(
            tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
        )
        cfg = yaml.safe_load((task / "input/chatbot.yaml").read_text(encoding="utf-8"))
        assert cfg["transport"] == "sidecar_http"
        assert cfg["connection"]["baseUrl"] == "http://assistant:8000"
        assert "verifier.import_path" in (task / "tests/test.sh").read_text(
            encoding="utf-8"
        )
    side = (
        REPO / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    cfg = yaml.safe_load((side / "docker-compose.yaml").read_text(encoding="utf-8"))
    assert "control" not in cfg["services"]["main"]["networks"]
    assert set(cfg["services"]["simulator"]["networks"]) == {"control"}
    assert "JOURNEY_SUT_API_KEY" not in cfg["services"]["simulator"]["environment"]
    assert not cfg["services"]["simulator"].get("ports")


def test_analysis_keeps_missing_denominator_and_persona_cluster():
    from matraix.journeys.analysis import summarize

    cases = []
    for domain in ("car", "home"):
        for condition in ("C1", "C2", "C3", "C4"):
            for i in range(1, 7):
                case = make_case(
                    domain,
                    ("J" if domain == "car" else "H") + str(i),
                    condition=condition,
                )
                case["source_persona_id"] = "same-original-profile"
                cases.append(case)
    result = summarize({"cases": cases}, {})
    assert (
        len(result["overall_comparisons"]) == 4
        and len(result["conditional_comparisons"]) == 8
    )
    assert all(
        g["success_rate"] == 0 and g["possible_success"] == g["planned"]
        for g in result["groups"]
    )
    assert all(
        c["difference_lower"] == -1
        and c["difference_upper"] == 1
        and len(c["units"]) == 1
        for c in result["overall_comparisons"]
    )
    assert result["inference_enabled"] is False
