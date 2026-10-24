"""Local distributed Harbor coordinator result.json lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.service.local_distributed_harbor import LocalDistributedHarborCoordinator


def _coordinator(tmp_path: Path, *, command_runner) -> LocalDistributedHarborCoordinator:
    jobs_dir = tmp_path / "jobs"
    return LocalDistributedHarborCoordinator(
        repo_root=tmp_path,
        job_name="arm-3",
        job_config={
            "jobs_dir": str(jobs_dir),
            "n_concurrent_trials": 2,
            "n_attempts": 1,
            "tasks": [{"path": "experiments/tasks/survey-healthtunes-positioning"}],
            "agents": [
                {"name": "persona-json-survey", "kwargs": {"persona_id": "1"}},
                {"name": "persona-json-survey", "kwargs": {"persona_id": "2"}},
            ],
        },
        launch_env={},
        command_runner=command_runner,
        harbor_command=("echo", "harbor"),
    )


def test_initial_result_json_counts_unfinished_as_running(tmp_path: Path) -> None:
    coord = _coordinator(tmp_path, command_runner=lambda *a, **k: 0)
    coord.job_dir.mkdir(parents=True)
    coord.generated_dir.mkdir(parents=True)
    coord.manifests_dir.mkdir(parents=True)
    manifests = coord._materialize_trial_manifests()
    coord._write_job_result(manifests=manifests, retries=0, finished=False)
    payload = json.loads((coord.job_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["finished_at"] is None
    assert payload["n_total_trials"] == 2
    assert payload["stats"]["n_completed_trials"] == 0
    assert payload["stats"]["n_running_trials"] == 2
    assert payload["stats"]["n_pending_trials"] == 0


def test_atexit_finalize_clears_running_and_sets_finished_at(tmp_path: Path) -> None:
    coord = _coordinator(tmp_path, command_runner=lambda *a, **k: 0)
    coord.job_dir.mkdir(parents=True)
    coord.generated_dir.mkdir(parents=True)
    coord.manifests_dir.mkdir(parents=True)
    manifests = coord._materialize_trial_manifests()
    coord._manifests_for_finalize = manifests
    coord._write_job_result(manifests=manifests, retries=0, finished=False)

    coord._atexit_finalize()

    payload = json.loads((coord.job_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["finished_at"]
    assert payload["stats"]["n_running_trials"] == 0
    assert payload["stats"]["n_errored_trials"] == 2
    assert payload["stats"]["n_completed_trials"] == 2
    for manifest in manifests:
        trial = json.loads((manifest.trial_dir / "result.json").read_text(encoding="utf-8"))
        assert trial["exception_info"]["exception_type"] == "WorkerProcessError"


def test_run_finalizes_when_worker_raises(tmp_path: Path) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("worker exploded")

    coord = _coordinator(tmp_path, command_runner=boom)
    with pytest.raises(RuntimeError, match="worker exploded"):
        coord.run()

    payload = json.loads((coord.job_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["finished_at"]
    assert payload["stats"]["n_running_trials"] == 0
    assert payload["stats"]["n_errored_trials"] >= 1
