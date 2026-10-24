"""CLI experiment create must wait for in-process Harbor jobs."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import textwrap
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


@pytest.mark.parametrize("command", ["create", "list", "show", "analyze"])
def test_machine_stdout_is_one_json_including_children_and_threads(tmp_path, command):
    result = _noisy_cli_process(tmp_path, command)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)  # Entire stdout, no filtering or tail extraction.
    assert payload == ([{"experimentId": "exp-test"}] if command == "list"
                       else {"experimentId": "exp-test", "status": "completed"})
    for diagnostic in ("provider-list", "old-logger", "worker-print", "child-stdout",
                       "read-metadata", "native-fd-write"):
        assert diagnostic in result.stderr, result.stderr
    if command == "create":
        assert "shutdown-print" in result.stderr
        assert "child-shutdown" in result.stderr


@pytest.mark.parametrize("mode,exit_code,has_payload", [
    ("arm-failed", 1, True), ("launch-failed", 1, False),
    ("interrupt", 130, False),
])
def test_json_errors_still_drain_shutdown_and_keep_exit_status(
    tmp_path, mode, exit_code, has_payload
):
    result = _noisy_cli_process(tmp_path, "create", mode)
    assert result.returncode == exit_code, result.stderr
    if has_payload:
        assert json.loads(result.stdout)["status"] == "failed"
    else:
        assert result.stdout == ""
    if mode != "interrupt":
        assert "drained-jobs" in result.stderr
    assert "shutdown-print" in result.stderr
    assert "child-shutdown" in result.stderr


def _noisy_cli_process(tmp_path, command, mode="success", *, fmt="json", output=None):
    # A real child CLI process is necessary: redirect_stdout alone passes ordinary
    # print tests but leaks inherited Harbor/native fd output into stdout.
    script = tmp_path / "noisy_cli.py"
    script.write_text(textwrap.dedent(r"""
        import argparse, json, logging, os, subprocess, sys, threading
        from pathlib import Path
        from matraix import experiment_cli as cli
        command, mode = sys.argv[1:]
        original = sys.stdout
        logger = logging.getLogger("pre-existing-stdout-handler")
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.setLevel(logging.WARNING)
        def noise(stage):
            print("provider-list", stage)
            logger.warning("old-logger %s", stage)
            thread = threading.Thread(target=lambda: print("worker-print", stage))
            thread.start()
            thread.join()
            subprocess.run([sys.executable, "-c", "print('child-stdout')"], check=True)
            os.write(1, b"native-fd-write\n")
        class Harbor:
            _launches = {"job-test": object()}
            def shutdown(self):
                print("shutdown-print")
                subprocess.run([sys.executable, "-c", "print('child-shutdown')"], check=True)
        class Service:
            harbor = Harbor()
            def create_experiment(self, **kwargs):
                noise("create")
                if mode == "launch-failed":
                    raise ValueError("launch failed")
                if mode == "interrupt":
                    raise KeyboardInterrupt()
                return {"experimentId": "exp-test", "cells": [{"jobName": "job-test"}]}
            def get_experiment(self, exp_id):
                print("read-metadata")
                return {"experimentId": exp_id, "status": "failed" if mode == "arm-failed" else "completed"}
            def list_experiments(self):
                print("read-metadata")
                return [{"experimentId": "exp-test"}]
            def get_experiment_analysis(self, *a, **kw):
                return self.get_experiment("exp-test")
        def build(root):
            noise("build")
            return Service()
        def wait(*args):
            print("drained-jobs")
            return mode == "arm-failed"
        cli._build_service = build
        cli._repo_root = lambda args: Path.cwd()
        cli._wait_experiment_jobs = wait
        args = argparse.Namespace(
            task="test", name=None, per_arm=1, seed=42, mode="auto", axis=None,
            persona_model=None, agent_name=None, cua_backend=None, concurrent=1,
            format=os.environ["TEST_OUTPUT_FORMAT"], repo_root=None, experiment_command=command,
            experiment_id="exp-test", confidence=.95, fdr=False, slices=False,
            output=os.environ.get("TEST_OUTPUT_FILE"),
        )
        try:
            cli.run_experiment(args)
        except KeyboardInterrupt:
            sys.exit(130)
        finally:
            assert sys.stdout is original, "stdout was not restored"
    """), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(experiment_cli.__file__).resolve().parents[1])
    env["PYTHONIOENCODING"] = "utf-8"
    env["TEST_OUTPUT_FORMAT"] = fmt
    if output is not None:
        env["TEST_OUTPUT_FILE"] = str(output)
    return subprocess.run(
        [sys.executable, str(script), command, mode], env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )


def test_embedded_json_stdout_without_fileno():
    import io
    from contextlib import redirect_stdout, redirect_stderr

    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        with experiment_cli._diagnostics_on_stderr() as payload:
            print("diagnostic")
            payload.write('{"ok":true}')
        print("restored", file=sys.stderr)
    assert json.loads(stdout.getvalue()) == {"ok": True}
    assert stderr.getvalue() == "diagnostic\nrestored\n"



def test_analyze_csv_stdout_is_not_prefixed_by_logs(tmp_path):
    result = _noisy_cli_process(tmp_path, "analyze", fmt="csv")
    assert result.returncode == 0, result.stderr
    assert next(csv.reader(io.StringIO(result.stdout))) == experiment_cli._CSV_COLUMNS
    assert "provider-list" not in result.stdout
    assert "provider-list" in result.stderr


def test_json_file_export_keeps_stdout_empty(tmp_path):
    target = tmp_path / "analysis.json"
    result = _noisy_cli_process(tmp_path, "analyze", output=target)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert json.loads(target.read_text()) == {"experimentId": "exp-test", "status": "completed"}
    assert "wrote" in result.stderr and "provider-list" in result.stderr


@pytest.mark.parametrize("raise_error", [False, True])
def test_descriptor_and_child_stdout_restored_after_context(raise_error):
    code = textwrap.dedent("""
        import os, subprocess, sys
        from matraix.experiment_cli import _diagnostics_on_stderr
        try:
            with _diagnostics_on_stderr() as output:
                print("diagnostic")
                output.write("payload\\n")
                if sys.argv[1] == "True":
                    raise ValueError("expected")
        except ValueError:
            pass
        os.write(1, b"restored-fd\\n")
        subprocess.run([sys.executable, "-c", "print('restored-child')"], check=True)
    """)
    env = {**os.environ, "PYTHONPATH": str(Path(experiment_cli.__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-c", code, str(raise_error)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "payload\nrestored-fd\nrestored-child\n"
    assert result.stderr == "diagnostic\n"
