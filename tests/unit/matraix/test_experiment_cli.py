"""CLI experiment create must wait for in-process Harbor jobs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from matraix import experiment_cli


def _create_args(**overrides) -> argparse.Namespace:
    values = {
        "task": "experiments/tasks/survey-healthtunes-positioning",
        "name": None,
        "per_arm": 8,
        "seed": 42,
        "mode": "auto",
        "axis": None,
        "persona_model": "openai/azure-persona",
        "agent_name": None,
        "cua_backend": None,
        "concurrent": 2,
        "format": "text",
        "repo_root": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_cmd_create_waits_for_each_arm_then_shuts_down(monkeypatch, capsys) -> None:
    waited: list[str] = []
    shutdowns: list[bool] = []

    class Harbor:
        _launches = {"job-a": object(), "job-b": object(), "job-c": object()}

        def shutdown(self) -> None:
            shutdowns.append(True)

    class Service:
        harbor = Harbor()

        def create_experiment(self, **_kwargs):
            return {
                "experimentId": "exp-healthtunes-1",
                "cells": [
                    {"cellId": "c0", "arm": "A", "jobName": "job-a"},
                    {"cellId": "c1", "arm": "B", "jobName": "job-b"},
                    {"cellId": "c2", "arm": "C", "jobName": "job-c"},
                ],
            }

        def get_experiment(self, experiment_id: str):
            return {"experimentId": experiment_id, "status": "completed", "cells": []}

    monkeypatch.setattr(experiment_cli, "_build_service", lambda _root: Service())
    monkeypatch.setattr(experiment_cli, "_repo_root", lambda _args: Path("/tmp"))
    monkeypatch.setattr(
        "matraix.job_run.wait_for_harbor_job",
        lambda _harbor, name, poll_s=2.0: waited.append(name)
        or {"launch": {"status": "completed"}},
    )

    experiment_cli._cmd_create(_create_args())
    assert waited == ["job-a", "job-b", "job-c"]
    assert shutdowns == [True]
    out = capsys.readouterr().out
    assert "exp-healthtunes-1" in out


def test_cmd_create_exits_when_an_arm_fails(monkeypatch) -> None:
    class Harbor:
        def shutdown(self) -> None:
            return None

    class Service:
        harbor = Harbor()

        def create_experiment(self, **_kwargs):
            return {
                "experimentId": "exp-1",
                "cells": [
                    {"cellId": "c0", "arm": "A", "jobName": "job-a"},
                    {"cellId": "c1", "arm": "B", "jobName": "job-b"},
                ],
            }

        def get_experiment(self, experiment_id: str):
            return {"experimentId": experiment_id}

    monkeypatch.setattr(experiment_cli, "_build_service", lambda _root: Service())
    monkeypatch.setattr(experiment_cli, "_repo_root", lambda _args: Path("/tmp"))

    def fake_wait(_harbor, name, poll_s=2.0):
        if name == "job-b":
            return {"launch": {"status": "failed", "error": "boom"}}
        return {"launch": {"status": "completed"}}

    monkeypatch.setattr("matraix.job_run.wait_for_harbor_job", fake_wait)

    with pytest.raises(SystemExit) as excinfo:
        experiment_cli._cmd_create(_create_args())
    assert excinfo.value.code == 1
