"""Prospective native bindings and task-contract regressions; no model API."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import socket

import jsonschema
import pytest

from matraix.journeys.cohort import load_plan, make_case
from matraix.journeys.programmatic import Session, reference_trial, verify_record

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No real network/model/key access in native unit tests")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def test_official_task_discovery_and_eight_arm_schema():
    from matraix.experiment_cli import _prepare_paths

    _prepare_paths(REPO)
    from backend.service.experiment_service import ExperimentService
    from backend.service.harbor_job_service import HarborJobService
    from backend.service.persona_pool_service import PersonaPoolService

    harbor = HarborJobService.from_repo(repo_root=REPO)
    service = ExperimentService.from_repo(
        harbor=harbor, persona_pool=PersonaPoolService.from_repo(repo_root=REPO)
    )
    schema_path = REPO / "experiments/task-spec/schemas/experiment.schema.json"
    schema = json.loads(schema_path.read_text())
    from referencing import Registry, Resource

    documents = [json.loads(p.read_text()) for p in schema_path.parent.glob("*.json")]
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in documents
    )
    tasks = [row for row in service.list_experiment_tasks() if "journeys-" in str(row)]
    assert len(tasks) == 12
    for path in (REPO / "experiments/tasks").glob("journeys-*/experiment.json"):
        config = json.loads(path.read_text())
        jsonschema.Draft7Validator(schema, registry=registry).validate(config)
        from backend.service.experiment_design import expand_design

        design = expand_design(
            config["factors"], design_type="full_factorial", selected_factors=None
        )
        assert len(design["cells"]) == 8
        assert {cell["params"]["condition"] for cell in design["cells"]} == {
            "C1",
            "C2",
            "C3",
            "C4",
        }
    harbor.shutdown()


@pytest.mark.parametrize("edge", [False, True])
@pytest.mark.parametrize("value", [0, 20, 30, 40])
def test_h4_public_proposal_scoped_consent_and_actual_success(edge, value):
    s = Session(make_case("home", "H4", boundary=edge))
    info = s.execute(
        "ask_housemate", {"message": "What lighting proposal is acceptable?"}
    )
    assert info["terms"]["main_light_acceptable_percent"] == [0, 40]
    assert not info["authorization_granted"] and not s.backend.consent
    op = {"device_id": "living_light", "property": "light", "value": value}
    consent = s.execute(
        "confirm_operation",
        {
            "actor": "housemate",
            "operations": [{"tool": "set_device", "arguments": op}],
            "warning_code": "shared_lighting",
        },
    )
    assert consent["consent"] == "approved"
    assert s.execute("set_device", op)["status"] == "SUCCESS"
    s.execute("wait_until", {"minute": s.case["world"]["horizon"]})
    s.execute("submit_plan", {"outcome": "complete"})
    row = s.record("reference")
    # Ordinary preference may favor a different value, but the hard endpoint
    # must accept every publicly offered compromise; no hidden 30% target.
    from matraix.journeys.home.scoring import endpoint_ok

    assert endpoint_ok(s.case, row["final"], row["initial"])


@pytest.mark.parametrize("edge", [False, True])
def test_h4_denial_is_informative_and_never_grants_cross_scope_consent(edge):
    s = Session(make_case("home", "H4", boundary=edge))
    wrong = {"device_id": "living_desk", "property": "light", "value": 0}
    reply = s.execute(
        "confirm_operation",
        {
            "actor": "housemate",
            "operations": [{"tool": "set_device", "arguments": wrong}],
            "warning_code": "shared_lighting",
        },
    )
    assert reply["consent"] == "denied"
    assert reply["acceptable_alternative"]["main_light_acceptable_percent"] == [0, 40]
    assert not s.backend.consent
    if not edge:
        assert s.execute("set_device", wrong)["blocked_before_execution"]
    if edge:
        op = {"device_id": "living_light", "property": "light", "value": 20}
        assert s.execute("set_device", op)["blocked_before_execution"]


@pytest.mark.parametrize("task", ["H1", "H5"])
@pytest.mark.parametrize("edge", [False, True])
@pytest.mark.parametrize("condition", ["C1", "C3"])
def test_thermal_feasibility_without_changing_thresholds(task, edge, condition):
    if not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned SimuHome required")
    # Include every fixture index in the 50-person design; these are offline
    # witness controls, not model trajectories or performance observations.
    for block in range(1, 51):
        c = make_case("home", task, block, condition, edge)
        before = deepcopy(c)
        row = reference_trial(c)
        assert row["score"]["programmatic_task_success"] == 1, (
            task,
            block,
            condition,
            edge,
            row["score"],
        )
        assert c == before
        verify_record(c, row)


def test_official_job_builder_binds_native_arm_and_preserves_full_identity(
    tmp_path, monkeypatch
):
    from matraix.application_job import build_application_job_config
    from matraix.persona_generator import (
        generate_synthetic_personas,
        write_persona_dataset,
    )

    repo = tmp_path / "checkout"
    for relative in ("src/matraix/__init__.py", "persona/schema/dimensions.json"):
        dest = repo / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, dest)
    for relative in (
        "application/tasks/chat_journeys-car-j4",
        "environment/task-environments/application/chatbot-api-sidecar_journeys/build-assets",
    ):
        shutil.copytree(REPO / relative, repo / relative)
    shared = "environment/task-environments/application/chatbot-api-sidecar_journeys"
    shutil.copyfile(
        REPO / shared / "docker-compose.yaml", repo / shared / "docker-compose.yaml"
    )
    sampled = generate_synthetic_personas(
        count=1,
        seed=3,
        dimension_filters={
            "primary_language": ["Mandarin"],
            "age_bracket": ["25-34"],
            "demo_driver_status": ["Daily driver"],
        },
        force_pin=True,
    )
    raw = sampled.personas[:1]
    pool = repo / "persona/test-pool"
    write_persona_dataset(
        out_dir=pool,
        personas=raw,
        repo_root=repo,
        kind="generated-persona-dev-test",
        seed=42,
        smoke_persona_id=raw[0]["persona_id"],
    )
    for role in ("SUT", "PUT"):
        monkeypatch.setenv(f"JOURNEY_{role}_BASE_URL", "http://127.0.0.1:1")
        monkeypatch.setenv(f"JOURNEY_{role}_MODEL", "scripted-model")
        monkeypatch.setenv(f"JOURNEY_{role}_OPTIONS_JSON", "{}")
    spec = {
        "name": "exp-native-c0",
        "task": "application/tasks/chat_journeys-car-j4",
        "persona_pool": "persona/test-pool",
        "persona_ids": [raw[0]["persona_id"]],
        "seed": 42,
        "execution_mode": "force_docker",
        "trial_profile": "user_sim_chat",
        "agent": {"name": "persona-user-sim", "model_name": "scripted-model"},
        "runtime_params": {
            "MATRIX_PARAM_CONDITION": "C3",
            "MATRIX_PARAM_VARIANT": "boundary",
        },
    }
    job = build_application_job_config(spec, repo_root=repo)
    assert job["retry"]["max_retries"] == 0
    assert job["verifier"]["import_path"].endswith(":JourneyVerifier")
    agent = job["agents"][0]
    assert "name" not in agent and agent["import_path"].endswith(":JourneyPersonaAPI")
    plan = load_plan(agent["kwargs"]["plan_path"])
    assert len(plan["cases"]) == 1 and plan["purpose"] == "harbor"
    assert plan["cases"][0]["native_persona"]["dimensions"] == raw[0]["dimensions"]
    assert len(raw[0]["dimensions"]) == 1290
    assert plan["cases"][0]["cohort"] == "C3" and plan["cases"][0]["boundary"]
    from harbor.models.job.config import JobConfig

    JobConfig.model_validate({k: v for k, v in job.items() if k != "_job_meta"})
    with pytest.raises(ValueError, match="already prepared"):
        build_application_job_config(spec, repo_root=repo)


def test_native_pdf_renders_standard_analysis_without_new_inference():
    from matraix.experiment_cli import _prepare_paths

    _prepare_paths(REPO)
    from backend.service.report_pdf import build_experiment_report_pdf

    payload = build_experiment_report_pdf(
        manifest={"experimentId": "exp-test", "status": "completed", "cells": []},
        analysis={"comparisons": [], "correction": {"method": "none"}},
    )
    assert payload.startswith(b"%PDF-") and len(payload) > 1000


def test_failed_worker_pipe_does_not_mask_original_error_or_skip_reaping():
    from matraix.journeys.simulator import IsolatedTrial
    from types import SimpleNamespace

    events = []

    def broken_send(_):
        raise BrokenPipeError("worker already exited")

    alive = [True]

    def join(timeout):
        events.append(("join", timeout))
        alive[0] = False

    trial = IsolatedTrial.__new__(IsolatedTrial)
    trial.process = SimpleNamespace(is_alive=lambda: alive[0], join=join)
    trial.pipe = SimpleNamespace(
        send=broken_send, close=lambda: events.append("closed")
    )
    trial.close()
    assert events == [("join", 5), "closed"]


def test_unstarted_arm_is_dispatch_failure_not_a_fabricated_harbor_job(tmp_path):
    from matraix.experiment_cli import _prepare_paths

    _prepare_paths(REPO)
    from backend.service.experiment_service import ExperimentService
    from types import SimpleNamespace
    import threading
    import time

    harbor = SimpleNamespace(
        _guard=threading.Lock(),
        _launches={"exp-test-c0": SimpleNamespace(status="completed")},
        _experiment_dispatch_errors={},
        repo_root=tmp_path,
    )
    service = ExperimentService(
        repo_root=tmp_path, harbor=harbor, persona_pool=None, runs_dir=tmp_path / "runs"
    )

    def launch(**kwargs):
        if kwargs["job_name"] != "exp-test-c0":
            raise ValueError("test dispatch rejection")

    service._launch_arm = launch
    service._dispatch_arm_launches(
        [{"job_name": "exp-test-c0"}, {"job_name": "exp-test-c1"}],
        parallel_arms=False,
        n_concurrent_trials=1,
    )
    end = time.monotonic() + 5
    path = tmp_path / "runs/exp-test/dispatch-error.json"
    while not path.exists() and time.monotonic() < end:
        time.sleep(0.01)
    assert json.loads(path.read_text())["notStartedJobNames"] == ["exp-test-c1"]
    from matraix.job_run import wait_for_harbor_job

    row = wait_for_harbor_job(harbor, "exp-test-c1", timeout_s=1)
    assert row["dispatch"]["status"] == "not_started" and "launch" not in row
    assert not (tmp_path / "jobs").exists()


def test_native_two_role_usage_is_not_priced_from_put_tokens(tmp_path):
    from matraix.experiment_cli import _prepare_paths

    _prepare_paths(REPO)
    from backend.service.experiment_service import ExperimentService
    from types import SimpleNamespace

    job = tmp_path / "jobs/test"
    job.mkdir(parents=True)
    (job / "config.json").write_text(
        json.dumps(
            {"agents": [{"import_path": "matraix.journeys.agent:JourneyPersonaAPI"}]}
        )
    )
    (job / "result.json").write_text(json.dumps({"stats": {"cost_usd": 0}}))
    service = ExperimentService(
        repo_root=tmp_path,
        harbor=SimpleNamespace(jobs_dir=tmp_path / "jobs"),
        persona_pool=None,
    )
    assert service._cell_rollup("test")["costUsd"] is None


def test_standard_reader_keeps_objective_outcome_facets():
    from matraix.job_results import _signals_from_structured_output

    payload = {
        "contexts": [
            {
                "contextType": "task_outcome",
                "facets": [
                    {"key": "programmatic_task_success", "value": 0},
                    {"key": "outcome_status", "value": "feasible_partial"},
                    {"key": "goal_completion_ratio", "value": 0},
                    {"key": "feasible_partial_completion", "value": 1},
                ],
            }
        ]
    }
    values = _signals_from_structured_output(payload)
    assert values["programmatic_task_success"] == 0
    assert values["feasible_partial_completion"] == 1
    assert values["outcome_status"] == "feasible_partial"
