"""Run the real official 8-arm experiment with real Harbor/Docker, scripted APIs.

Writes fresh synthetic acceptance data only. Requires a clean disposable checkout.
Never load .env, key files, or model credentials. Missing Docker is a failure.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading


def _install_scripted_sidecar(repo, *, inject_failure=False):
    from matraix.journeys import native_job

    prepare = native_job.prepare_job

    def test_context(job, spec, *, repo_root):
        result = prepare(job, spec, repo_root=repo_root)
        # Only the model endpoint is replaced. Jobs, agent, native simulator,
        # verifier, task scoring, experiment scheduler and exports are real.
        path = (
            repo
            / "environment/task-environments/application/_generated/journeys"
            / job["job_name"]
        )
        shutil.copyfile(
            repo / "tests/helpers/journey_native_stub.py", path / "runtime/stub.py"
        )
        with (path / "runtime/Dockerfile").open("a") as f:
            f.write("\nCOPY stub.py .\n")
        import yaml

        config = path / "docker-compose.yaml"
        content = yaml.safe_load(config.read_text())
        content["services"]["assistant"]["command"] = ["python", "stub.py", "--sidecar"]
        if inject_failure:
            content["services"]["assistant"]["command"].append("--fail")
        config.write_text(yaml.safe_dump(content, sort_keys=False))
        return result

    native_job.prepare_job = test_context


def _cli_create(repo, pool, profiles, *, fail=False):
    """Exercise the real CLI subprocess and parse its ENTIRE stdout as JSON."""
    label = "failed-create" if fail else "create"
    with (pool.parent / f"{label}.stderr.log").open("w", encoding="utf-8") as logs:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--cli-child",
             pool.relative_to(repo).as_posix(), profiles[0]["persona_id"],
             "fail" if fail else "success"],
            cwd=repo, stdout=subprocess.PIPE, stderr=logs, text=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=1800,
        )
    (pool.parent / f"{label}.stdout.json").write_text(result.stdout, encoding="utf-8")
    assert result.returncode == (1 if fail else 0), label
    manifest = json.loads(result.stdout)  # No ANSI stripping or tail extraction.
    assert isinstance(manifest, dict) and manifest["experimentId"]
    assert (pool.parent / f"{label}.stderr.log").stat().st_size > 0
    return manifest


def main():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from matraix.launch_env import required_pythonpath_entries

    sys.path[:0] = required_pythonpath_entries(repo)
    os.environ["PYTHONPATH"] = os.pathsep.join(required_pythonpath_entries(repo))
    subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL)
    # Do not read existing secrets, including inherited API key variables.
    for key in list(os.environ):
        if "API_KEY" in key or key.startswith("JOURNEY_"):
            del os.environ[key]
    for role, port in (("SUT", 9011), ("PUT", 9012)):
        os.environ.update(
            {
                f"JOURNEY_{role}_BASE_URL": f"http://127.0.0.1:{port}",
                f"JOURNEY_{role}_MODEL": "scripted-journey-test",
                f"JOURNEY_{role}_API_KEY": "not-a-credential",
                f"JOURNEY_{role}_OPTIONS_JSON": "{}",
            }
        )
    os.environ.update(
        JOURNEY_CONTROL_TOKEN="scripted-acceptance-control",
        MATRIX_COMPUTE_FAMILY="local",
        MATRIX_EXECUTION_PLANE="harbor",
        JOURNEY_REQUEST_LIMIT="1000",
    )
    from matraix.persona_generator import (
        generate_synthetic_personas,
        write_persona_dataset,
    )

    pool = repo / "journey-runs/native-acceptance/personas"
    if pool.parent.exists():
        raise ValueError(
            "Use a fresh checkout/output; acceptance never resumes or overwrites"
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
    profiles = sampled.personas[:1]
    write_persona_dataset(
        out_dir=pool,
        personas=profiles,
        repo_root=repo,
        kind="generated-persona-dev-acceptance",
        seed=20261029,
        smoke_persona_id=profiles[0]["persona_id"],
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "acceptance_stub", repo / "tests/helpers/journey_native_stub.py"
    )
    stub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub)
    http = stub.server(9012)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    from backend.service.harbor_job_service import HarborJobService
    from backend.service.persona_pool_service import PersonaPoolService
    from backend.service.experiment_service import ExperimentService

    harbor = HarborJobService.from_repo(repo_root=repo)
    svc = ExperimentService.from_repo(
        harbor=harbor, persona_pool=PersonaPoolService.from_repo(repo_root=repo)
    )
    try:
        manifest = _cli_create(repo, pool, profiles)
        names = [c["jobName"] for c in manifest["cells"]]
        assert len(names) == 8
        assert manifest["status"] == "completed"
        exp_id = manifest["experimentId"]
        analysis = svc.get_experiment_analysis(exp_id)
        assert len(analysis["armSizes"]) == 8 and set(
            analysis["armSizes"].values()
        ) == {1}
        assert (
            sum(
                r["metricKey"] == "programmatic_task_success"
                for r in analysis["comparisons"]
            )
            == 7
        )
        from matraix.journeys.ledger import summary

        ledger = summary(
            repo
            / "configs/jobs/_generated/journey-accounting"
            / exp_id
            / "requests.sqlite3"
        )
        assert (
            ledger["failed"]
            == ledger["inflight_or_unknown"]
            == ledger["usage_unknown_requests"]
            == 0
        ), ledger
        assert ledger["requests"] == 40, ledger
        for name in names:
            job = repo / "jobs" / name
            assert (job / "result.json").is_file()
            trials = list(job.glob("*/verifier/structured_output.json"))
            assert len(trials) == 1
            row = json.loads(trials[0].read_text())
            values = {f["key"]: f["value"] for f in row["contexts"][0]["facets"]}
            assert values["programmatic_task_success"] == 1
            trial = json.loads((trials[0].parents[1] / "result.json").read_text())
            assert trial["agent_result"]["n_input_tokens"] == 34
            assert trial["agent_result"]["n_output_tokens"] == 18
            from matraix.job_results import collect_job_results

            standard = collect_job_results(job).to_dict()
            assert standard["appType"] == "chatbot"
            assert (
                standard["ledger"]["trials"][0]["signals"]["programmatic_task_success"]
                == 1
            )
            assert (
                standard["ledger"]["trials"][0]["signals"]["outcome_status"]
                == "complete"
            )
            assert standard["lens"]["source"] != "none"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "matraix.cli",
                    "results",
                    name,
                    "--format",
                    "json,csv",
                    "-o",
                    str(pool.parent / "exports" / name),
                ],
                check=True,
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "matraix.cli",
                "experiment",
                "analyze",
                exp_id,
                "--format",
                "json,csv,pdf",
                "-o",
                str(pool.parent / "exports"),
            ],
            check=True,
        )
        failed_manifest = _cli_create(repo, pool, profiles, fail=True)
        failed_names = [c["jobName"] for c in failed_manifest["cells"]]
        assert failed_manifest["status"] == "failed"
        failed_id = failed_manifest["experimentId"]
        failed_ledger = summary(
            repo
            / "configs/jobs/_generated/journey-accounting"
            / failed_id
            / "requests.sqlite3"
        )
        assert failed_ledger["requests"] == 2 and failed_ledger["failed"] == 1
        assert (
            failed_ledger["inflight_or_unknown"] == 0
            and failed_ledger["usage_unknown_requests"] == 1
        )
        failure_view = svc.get_experiment(failed_id)
        assert failure_view["status"] == "failed"
        assert sum(c["status"] == "not_started" for c in failure_view["cells"]) == 7
        assert all(not (repo / "jobs" / name).exists() for name in failed_names[1:])
        names += failed_names
        result = {
            "acceptance": "real-harbor-scripted-api",
            "experiment_id": exp_id,
            "arms": 8,
            "trials": 8,
            "ledger": ledger,
            "cli_json_stdout": "entire-success-and-failure-stdout-parsed",
            "logs_on_stderr": True,
            "paid_model_requests": 0,
            "historical_results_read": False,
            "injected_failure": {
                "experiment_id": failed_id,
                "not_started_arms": 7,
                "ledger": failed_ledger,
                "retried_requests": 0,
            },
        }
        (pool.parent / "ACCEPTANCE.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        harbor.shutdown()
        http.shutdown()
        http.server_close()
        thread.join(timeout=10)
        assert not thread.is_alive()
    containers = subprocess.check_output(
        ["docker", "ps", "--format", "{{.Names}}"], text=True
    )
    assert not any(name in containers for name in names), containers


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli-child":
        repo = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo / "src"))
        from matraix.launch_env import required_pythonpath_entries
        sys.path[:0] = required_pythonpath_entries(repo)
        _install_scripted_sidecar(repo, inject_failure=sys.argv[4] == "fail")
        from matraix.cli import main as cli_main
        cli_main([
            "experiment", "create", "experiments/tasks/journeys-car-j4",
            "--persona-pool", sys.argv[2], "--persona-ids", sys.argv[3],
            "--persona-model", "scripted-journey-test", "--seed", "20261029",
            "--mode", "force_docker", "--concurrent", "1",
            "--no-parallel-arms", "--format", "json",
        ])
    else:
        main()
