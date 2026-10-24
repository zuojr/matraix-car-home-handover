"""Native source pairing, portable plans and standard Harbor integration."""

from copy import deepcopy

import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

import pytest
import yaml

from matraix.journeys import cohort
from matraix.journeys.cli import materialize, resolve

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def native_pool():
    # Temporary fixtures use actual checked-in native dimension labels. They
    # never generate new research personas or call a sampler/model.
    cache = REPO / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="journey-fixture-", dir=cache) as folder:
        pool = Path(folder)
        raw = yaml.safe_load(
            (
                REPO / "persona/datasets/matraix-persona-dev-sample/persona_0042.yaml"
            ).read_text(encoding="utf-8")
        )
        raw.update(persona_id="test-original", fixture_only=True)
        path = pool / "persona_test-original.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        cohort.write_new(
            pool / "manifest.json",
            {
                "kind": "offline-fixture-only",
                "personas": [
                    {
                        "persona_id": raw["persona_id"],
                        "source": raw["source"],
                        "dimensions": raw["dimensions"],
                        "path": path.relative_to(REPO).as_posix(),
                    }
                ],
            },
        )
        yield pool


def prepared(pool, out):
    cohort.prepare(
        REPO,
        dict.fromkeys(cohort.DOMAINS, pool),
        dict.fromkeys(cohort.DOMAINS, ["test-original"]),
        out,
        purpose="offline",
        fixture=True,
    )
    return cohort.load_plan(out)


def test_full_available_native_attributes_paired_and_portable(native_pool, tmp_path):
    plan = prepared(native_pool, tmp_path / "plan")
    assert plan["planned_episodes"] == 96 and plan["execution_authorized"] is False
    raw = yaml.safe_load(
        (native_pool / "persona_test-original.yaml").read_text(encoding="utf-8")
    )
    for domain in cohort.DOMAINS:
        cases = [c for c in plan["cases"] if c["domain"] == domain]
        assert len(cases) == 48 and len({c["source_persona_id"] for c in cases}) == 1
        assert len({c["persona_binding"] for c in cases}) == 4
        assert {c["boundary"] for c in cases} == {True, False}
        assert {c["cohort"] for c in cases} == set(cohort.CONDITIONS)
        assert cohort.native_context(cases[0])["attributes"] == raw["dimensions"]
    shutil.copytree(tmp_path / "plan", tmp_path / "moved")
    assert cohort.load_plan(tmp_path / "moved") == plan


def test_fixture_cannot_enter_model_pipeline(native_pool, tmp_path):
    plan = prepared(native_pool, tmp_path / "plan")
    from matraix.journeys.run import run_api

    with pytest.raises(ValueError, match="real native"):
        run_api(
            tmp_path / "plan", "https://never.invalid", tmp_path / "run", execute=True
        )
    with pytest.raises(ValueError, match="Reference fixtures"):
        resolve(REPO, tmp_path / "plan", REPO / "journey-runs/never-written", "api-id")
    assert plan["fixture_only"] and not (tmp_path / "run").exists()


@pytest.mark.parametrize("kind", ["yaml", "plan", "manifest"])
def test_tampered_native_input_or_plan_is_rejected(native_pool, tmp_path, kind):
    prepared(native_pool, tmp_path / "plan")
    if kind == "yaml":
        path = next((tmp_path / "plan/inputs/car").glob("*.yaml"))
    elif kind == "manifest":
        path = tmp_path / "plan/inputs/car/manifest.json"
    else:
        path = tmp_path / "plan/plan.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    if kind == "plan":
        # JSON whitespace is canonicalized; changing semantic input is rejected.
        data = json.loads(path.read_text(encoding="utf-8"))
        data["seed"] += 1
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        cohort.load_plan(tmp_path / "plan")


def test_native_manifest_identity_mismatch_rejected(native_pool, tmp_path):
    path = native_pool / "persona_test-original.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["source"] = "not-the-manifest-source"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="disagreement"):
        prepared(native_pool, tmp_path / "plan")


def test_identical_source_content_is_parsed_once_per_load(
    native_pool, tmp_path, monkeypatch
):
    prepared(native_pool, tmp_path / "plan")
    original = cohort.yaml.safe_load
    calls = []

    def observed(text):
        calls.append(text)
        return original(text)

    monkeypatch.setattr(cohort.yaml, "safe_load", observed)
    cohort.load_plan(tmp_path / "plan")
    assert len(calls) == 1  # Same source bytes appear in all 96 paired cases.


def test_source_bytes_are_still_checked_after_first_parse(
    native_pool, tmp_path, monkeypatch
):
    prepared(native_pool, tmp_path / "plan")
    original_read = Path.read_bytes
    changed = []

    def observed(path):
        data = original_read(path)
        if path.suffix == ".yaml" and "inputs" in path.parts and not changed:
            path.write_bytes(data + b" ")
            changed.append(path)
        return data

    monkeypatch.setattr(Path, "read_bytes", observed)
    with pytest.raises(ValueError, match="Source YAML changed"):
        cohort.load_plan(tmp_path / "plan")
    assert len(changed) == 1


def test_cached_original_is_compared_with_every_case(native_pool, tmp_path):
    plan_path = tmp_path / "plan"
    plan = prepared(native_pool, plan_path)
    profile = plan["cases"][5]["native_persona"]["dimensions"]
    profile["primary_language"] = (
        "Mandarin" if profile.get("primary_language") != "Mandarin" else "English"
    )
    (plan_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    manifest = json.loads((plan_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["plan_sha256"] = cohort.digest(plan)
    (plan_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the hashed original"):
        cohort.load_plan(plan_path)


def test_materialized_sidecar_is_self_contained_and_harbor_can_copy_it(tmp_path):
    from harbor.environments.compose_materialize import (
        materialize_persona_with_local_compose,
    )

    repo = tmp_path / "checkout"
    side = (
        repo / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    side.mkdir(parents=True)
    original = (
        REPO / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    shutil.copytree(original / "build-assets", side / "build-assets")
    shutil.copyfile(original / "docker-compose.yaml", side / "docker-compose.yaml")
    (repo / "src/matraix").mkdir(parents=True)
    shutil.copyfile(REPO / "src/matraix/__init__.py", repo / "src/matraix/__init__.py")
    runtime = materialize(repo)
    assert runtime == materialize(repo)
    target = materialize_persona_with_local_compose(
        persona_dir=REPO
        / "environment/task-environments/application/shared-chat-persona",
        local_compose_dir=side,
        dest_dir=tmp_path / "harbor-environment",
    )
    cfg = yaml.safe_load((target / "docker-compose.yaml").read_text(encoding="utf-8"))
    assert (target / "Dockerfile").read_text(encoding="utf-8") == (
        REPO
        / "environment/task-environments/application/shared-chat-persona/Dockerfile"
    ).read_text(encoding="utf-8")
    for service in ("assistant", "simulator"):
        context = (target / cfg["services"][service]["build"]["context"]).resolve()
        assert context.is_relative_to(target.resolve())
        assert (context / "matraix/journeys/programmatic.py").exists()
        assert (context / "matraix/journeys/car/vendor/car-bench-source.zip").exists()
    assert not list((runtime / "matraix/journeys").rglob(".cache"))


@pytest.mark.asyncio
async def test_harbor_verifier_uses_private_service_and_standard_envelope(tmp_path):
    from matraix.journeys.harbor import JourneyVerifier
    from matraix.journeys.simulator import Manager
    from matraix.journeys.verify import verify_records

    root = tmp_path / "records"
    manager = Manager(root, {"one": cohort.make_case("car", "J4")})
    sid, _ = manager.create("one")
    manager.record(sid, reference=True, terminal=True)

    class Environment:
        async def service_exec(self, command, service, timeout_sec):
            assert service == "simulator" and "journeys.verify" in command
            verify_records(root, tmp_path / "service-verification")
            return SimpleNamespace(return_code=0)

        async def service_download_file(self, source, dest, service):
            assert service == "simulator"
            shutil.copyfile(tmp_path / "service-verification" / Path(source).name, dest)

    verifier = JourneyVerifier(
        task=None,
        trial_paths=SimpleNamespace(verifier_dir=tmp_path / "verifier"),
        environment=Environment(),
    )
    result = await verifier.verify()
    assert result.rewards["reward"] == 1
    payload = json.loads(
        (tmp_path / "verifier/structured_output.json").read_text(encoding="utf-8")
    )
    assert payload["artifactType"] == "matraix.trial_evaluation"


@pytest.mark.asyncio
async def test_standard_chat_request_is_single_attempt():
    from matraix.journeys.agent import request

    calls = []

    class Failed:
        async def exec(self, command, timeout_sec):
            calls.append(command)
            return SimpleNamespace(return_code=1, stdout="", stderr="HTTP 503")

    with pytest.raises(RuntimeError, match="no retry"):
        await request(
            Failed(), "POST", "/v1/messages", {"message": '{"act":"continue"}'}
        )
    assert len(calls) == 1


def test_resolved_harbor_jobs_do_not_cross_personas_and_cases(
    native_pool, tmp_path, monkeypatch
):
    from harbor.models.job.config import JobConfig
    from matraix.journeys import cli

    plan = prepared(native_pool, tmp_path / "plan")
    # Test job materialization only. No model execution, no real-source claim.
    plan = deepcopy(plan)
    plan.update(fixture_only=False, purpose="pilot")
    monkeypatch.setattr(cli, "load_plan", lambda path: plan)
    checkout = tmp_path / "repo"
    shutil.copytree(
        REPO / "application/tasks",
        checkout / "application/tasks",
        ignore=shutil.ignore_patterns(".cache", "__pycache__"),
    )
    side = (
        checkout
        / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    side.mkdir(parents=True)
    cli.resolve(
        checkout, tmp_path / "plan", checkout / "journey-runs/resolved", "mock-api-id"
    )
    paths = list((checkout / "journey-runs/resolved/recipes").glob("*.yaml"))
    assert len(paths) == 96
    cases = {c["id"] for c in plan["cases"]}
    for path in paths:
        job = JobConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        assert len(job.agents) == len(job.tasks) == 1
        assert job.retry.max_retries == 0 and job.n_attempts == 1
        assert job.agents[0].kwargs["case_id"] == path.stem
        assert path.stem in cases
        import tomllib

        task = tomllib.loads(
            (job.tasks[0].path / "task.toml").read_text(encoding="utf-8")
        )
        assert task["environment"]["env"]["JOURNEY_SCENARIO_ID"] == path.stem


@pytest.mark.asyncio
async def test_native_persona_harbor_api_actor_preserves_identity_and_standard_artifacts(
    native_pool, tmp_path, monkeypatch
):
    from matraix.journeys import agent
    from matraix.journeys.api import ModelConfig
    from matraix.journeys.programmatic import reference_trial
    from matraix.journeys.chat import Gateway
    from matraix.journeys.simulator import Manager
    from tests.unit.matraix.test_journeys_sidecar import (
        LocalTrial,
        LocalSimulator,
        Script,
    )
    from harbor.models.agent.context import AgentContext

    plan = prepared(native_pool, tmp_path / "plan")
    plan = deepcopy(plan)
    plan.update(fixture_only=False, purpose="pilot")
    case = next(
        c
        for c in plan["cases"]
        if c["domain"] == "car"
        and c["task"] == "J4"
        and c["cohort"] == "C2"
        and not c["boundary"]
    )
    monkeypatch.setattr(agent, "load_plan", lambda path: plan)
    monkeypatch.setattr(
        agent.ModelConfig,
        "from_env",
        lambda role: ModelConfig(
            role, "https://offline.invalid/v1", "mock-put", "NO_SECRET"
        ),
    )
    script = Script(reference_trial(case)["events"])
    gateway = Gateway(
        LocalSimulator(
            Manager(
                tmp_path / "records",
                {"one": case},
                mode="model",
                trial_factory=LocalTrial,
            )
        ),
        tmp_path / "sut",
        mode="model",
        client_factory=lambda sid: script,
    )
    views = []

    async def chat_request(environment, method, path, body=None):
        if path == "/ready":
            return {
                "mode": "model",
                "plan_sha256": cohort.digest(plan),
                "source_contract_sha256": cohort.digest(cohort.code_contract()),
                "sut_config": {"model": "mock-sut"},
            }
        view = gateway.turn(body["message"], "one", body["sessionId"])
        views.append(view)
        return view

    monkeypatch.setattr(agent, "request", chat_request)

    class PUT:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def call(self, messages):
            assert case["source_persona_id"] in messages[2]["content"]
            assert (
                "Verifying" in messages[1]["content"]
                or "Verifying" in messages[1]["content"]
            )
            self.calls += 1
            return {
                "role": "assistant",
                "content": '{"act":"continue","style":"terse"}',
            }

        def close(self):
            pass

    monkeypatch.setattr(agent, "APIClient", PUT)
    uploaded = {}

    class Environment:
        async def upload_file(self, local, path):
            uploaded[path] = Path(local).read_text(encoding="utf-8")

    persona = tmp_path / "plan/inputs/car/persona_test-original.yaml"
    actor = agent.JourneyPersonaAPI(
        logs_dir=tmp_path / "agent",
        persona_path=str(persona),
        plan_path=str(tmp_path / "plan"),
        case_id=case["id"],
        model_name="mock-put",
    )
    env = Environment()
    context = AgentContext()
    await actor.setup(env)
    await actor.run("Use the current task card", env, context)
    assert views[-1]["terminal"]
    assert (
        json.loads(uploaded["/app/output/application_result.json"])[
            "applicationContext"
        ]
        == case["id"]
    )
    assert "score" not in uploaded["/app/output/application_result.json"]
    assert (
        json.loads(uploaded["/app/output/user_feedback.json"])["status"]
        == "not_collected"
    )
    assert context.metadata["source_persona_id"] == "test-original"
