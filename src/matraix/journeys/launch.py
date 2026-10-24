"""One-command, bounded study coordinator using isolated HTTP sidecar processes.

This works on Python 3.13 Windows/Linux without requiring a Docker daemon. The
same server factories, protocol, pinned native workers and verifier power Harbor.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from importlib.metadata import version as package_version
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import time

import httpx

from .api import ModelConfig, load_secret
from .cohort import (
    DOMAINS,
    CONCURRENCY_VALUES,
    VERSION,
    code_contract,
    digest,
    load_plan,
    prepare,
    write_new,
)


def configure(path, *, need_credentials=True, key_file=None):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        set(raw) - {"sut", "put", "limits", "concurrency"}
        or type(raw.get("concurrency", 1)) is not int
        or raw.get("concurrency", 1) not in CONCURRENCY_VALUES
    ):
        raise ValueError("Configure one SUT, one PUT and concurrency 1, 2, 4 or 8")
    if (
        key_file
        and len({httpx.URL(raw[r]["base_url"]).host for r in ("sut", "put")}) != 1
    ):
        lines = [
            v.strip()
            for v in Path(key_file).read_text(encoding="utf-8-sig").splitlines()
            if v.strip()
        ]
        if len(lines) != 2 or lines[0] == lines[1]:
            raise ValueError(
                "Mixed-provider --key-file needs DeepSeek then OpenAI keys on separate lines; or configure separate role files"
            )
    configs = {}
    for role in ("sut", "put"):
        data = raw[role]
        if set(data) - {"base_url", "model", "timeout", "max_tokens", "options"}:
            raise ValueError(
                "Do not put credentials or undeclared parameters in JSON settings"
            )
        prefix = "JOURNEY_" + role.upper() + "_"
        config = ModelConfig(
            role,
            data["base_url"].rstrip("/"),
            data["model"],
            prefix + "API_KEY",
            data.get("timeout", 120),
            data.get("max_tokens", 4096),
            json.dumps(data.get("options", {}), allow_nan=False),
        )
        config.validate()
        os.environ.update(
            {
                prefix + "BASE_URL": config.base_url,
                prefix + "MODEL": config.model,
                prefix + "TIMEOUT": str(config.timeout),
                prefix + "MAX_TOKENS": str(config.max_tokens),
                prefix + "OPTIONS_JSON": config.options_json,
            }
        )
        if key_file:
            os.environ[prefix + "API_KEY_FILE"] = str(Path(key_file).resolve())
            os.environ.pop(prefix + "API_KEY", None)
        if need_credentials:
            load_secret(role)
        configs[role] = config
    limits = {
        "max_sut_calls_per_case": 160,
        "max_persona_turns": 64,
        "max_total_api_requests": 200000,
        "chat_timeout": 1200,
    }
    if set(raw.get("limits", {})) - set(limits):
        raise ValueError("Unknown resource limit")
    limits.update(raw.get("limits", {}))
    if any(type(v) is not int or v < 1 for v in limits.values()):
        raise ValueError("Positive finite integer limits required")
    if (
        limits["max_sut_calls_per_case"] > 160
        or limits["max_persona_turns"] > 64
        or limits["chat_timeout"] > 20000
    ):
        raise ValueError(
            "Episode interaction budgets must not exceed the registered protocol"
        )
    limits["concurrency"] = raw.get("concurrency", 1)
    return configs, limits


def validation_plan(repo, out, persona_id="0042"):
    repo = Path(repo).resolve()
    pool = repo / "persona/datasets/matraix-persona-dev-sample"
    selected = {
        (d, ("J" if d == "car" else "H") + str(i), "C2", False)
        for d in DOMAINS
        for i in range(1, 7)
    }
    selected.update(
        {
            ("car", "J5", "C1", True),
            ("home", "H2", "C1", True),
            ("home", "H4", "C1", True),
            ("home", "H6", "C1", True),
        }
    )
    plan = prepare(
        repo,
        dict.fromkeys(DOMAINS, pool),
        dict.fromkeys(DOMAINS, [persona_id]),
        out,
        purpose="validation",
        fixture=True,
        validation_cases=selected,
    )
    return {
        "planned_episodes": len(plan["cases"]),
        "evidence_type": "api_validation",
        "not_experiment_results": True,
        "model_calls": 0,
    }


def setup_native(directory):
    from .home.common import read_json, HERE

    directory = Path(directory).resolve()
    provenance = read_json(HERE / "vendor/provenance.json")
    if not directory.exists():
        subprocess.run(
            ["git", "clone", provenance["repository"], str(directory)],
            check=True,
            timeout=120,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "-C", str(directory), "checkout", "--detach", provenance["commit"]],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    revision = subprocess.check_output(
        ["git", "-C", str(directory), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != provenance["commit"]:
        raise ValueError(
            "Existing native checkout has another revision; never reset it"
        )
    os.environ["SIMUHOME_ROOT"] = str(directory)
    from .home.native import load_source

    load_source()
    return {
        "SIMUHOME_ROOT": str(directory),
        "native_commit": revision,
        "hashes_valid": True,
        "model_calls": 0,
    }


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def child_environment():
    # Never inherit arbitrary API credentials into a native simulator child.
    allowed = {
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
    )
    if os.getenv("SIMUHOME_ROOT"):
        env["SIMUHOME_ROOT"] = os.environ["SIMUHOME_ROOT"]
    return env


class LocalStack:
    def __init__(self, plan, out, configs, limits, mode):
        self.plan, self.out, self.configs, self.limits, self.mode = (
            Path(plan),
            Path(out),
            configs,
            limits,
            mode,
        )
        self.token = secrets.token_urlsafe(32)
        self.sim_port, self.chat_port = free_port(), free_port()
        self.processes = []
        self.logs = []
        self.roles = []
        self.sim_url = f"http://127.0.0.1:{self.sim_port}"
        self.chat_url = f"http://127.0.0.1:{self.chat_port}"

    def start(self, module, port, env, name):
        log = (self.out / f"{name}.log").open("wb")
        self.logs.append(log)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "matraix.journeys.serve",
                "--service",
                name,
                "--port",
                str(port),
            ],
            env=env,
            cwd=self.out,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.processes.append(process)
        self.roles.append(name)
        started = time.monotonic()
        while time.monotonic() - started < 60:
            if process.poll() is not None:
                raise RuntimeError(name + " failed to start; inspect its private log")
            try:
                r = httpx.get(
                    f"http://127.0.0.1:{port}/health", timeout=2, trust_env=False
                )
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise TimeoutError(name + " startup deadline exceeded")

    def __enter__(self):
        common = child_environment()
        common.update(
            JOURNEY_MODE=self.mode,
            JOURNEY_PLAN_PATH=str(self.plan),
            JOURNEY_CONTROL_TOKEN=self.token,
            JOURNEY_RECORDS=str(self.out / "records"),
            JOURNEY_MAX_WORKERS=str(self.limits.get("concurrency", 1)),
        )
        try:
            self.start("matraix.journeys.simulator", self.sim_port, common, "simulator")
            assistant = dict(common)
            assistant.update(
                JOURNEY_SIMULATOR_URL=self.sim_url,
                JOURNEY_API_RECORDS=str(self.out / "sut-api-records"),
                JOURNEY_REQUEST_LEDGER=str(self.out / "requests.sqlite3"),
                JOURNEY_REQUEST_LIMIT=str(self.limits["max_total_api_requests"]),
                JOURNEY_MAX_SUT_CALLS=str(self.limits["max_sut_calls_per_case"]),
            )
            for k, v in os.environ.items():
                if k.startswith("JOURNEY_SUT_") and not k.endswith("_FILE"):
                    assistant[k] = v
            self.start("matraix.journeys.chat", self.chat_port, assistant, "assistant")
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        # Stop new SUT calls before draining native workers. A timed-out caller
        # must not leave its server making another paid request in the background.
        headers = {"X-Journey-Control": self.token}
        native_peak = None
        try:
            native_peak = (
                httpx.get(self.sim_url + "/health", timeout=3, trust_env=False)
                .json()
                .get("peak_active_workers")
            )
        except (httpx.HTTPError, ValueError):
            pass
        try:
            httpx.post(
                self.chat_url + "/internal/drain",
                headers=headers,
                timeout=3,
                trust_env=False,
            )
        except httpx.HTTPError:
            pass
        from .ledger import summary

        deadline = time.monotonic() + self.configs["sut"].timeout + 150
        while time.monotonic() < deadline:
            try:
                busy = (
                    httpx.get(
                        self.chat_url + "/internal/status",
                        headers=headers,
                        timeout=3,
                        trust_env=False,
                    )
                    .json()
                    .get("active_turns", 0)
                )
            except (httpx.HTTPError, ValueError):
                busy = 0
            if (
                not summary(self.out / "requests.sqlite3")["inflight_or_unknown"]
                and not busy
            ):
                break
            time.sleep(0.2)
        try:
            httpx.post(
                self.sim_url + "/internal/drain",
                headers=headers,
                timeout=15,
                trust_env=False,
            )
        except httpx.HTTPError:
            pass
        for url in (self.chat_url, self.sim_url):
            try:
                httpx.post(
                    url + "/internal/shutdown",
                    headers=headers,
                    timeout=3,
                    trust_env=False,
                )
            except httpx.HTTPError:
                pass
        for p in reversed(self.processes):
            if p.poll() is None:
                try:
                    p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.terminate()
                    p.wait(timeout=5)
        for log in self.logs:
            log.close()
        lifecycle = self.out / "service_lifecycle.json"
        if not lifecycle.exists():
            write_new(
                lifecycle,
                {
                    "services": [
                        {"role": role, "pid": p.pid, "exit_code": p.poll()}
                        for role, p in zip(self.roles, self.processes)
                    ],
                    "live_children": sum(p.poll() is None for p in self.processes),
                    "native_peak_active_workers": native_peak,
                },
            )


@contextmanager
def request_accounting(path, limit):
    names = ("JOURNEY_REQUEST_LEDGER", "JOURNEY_REQUEST_LIMIT")
    previous = {k: os.environ.get(k) for k in names}
    os.environ.update(
        JOURNEY_REQUEST_LEDGER=str(path), JOURNEY_REQUEST_LIMIT=str(limit)
    )
    from .ledger import connect

    connect(path).close()  # Initialize WAL/control tables before any worker races.
    try:
        yield
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def execute(plan_path, settings, out, *, execute_authorized=False, key_file=None):
    if not execute_authorized:
        raise ValueError("Use --execute for a real, potentially paid API run")
    from .telemetry import MemorySampler

    with MemorySampler(out):
        return _execute(
            plan_path,
            settings,
            out,
            execute_authorized=execute_authorized,
            key_file=key_file,
        )


def _execute(plan_path, settings, out, *, execute_authorized=False, key_file=None):
    if not execute_authorized:
        raise ValueError("Use --execute for a real, potentially paid API run")
    started = time.monotonic()
    if sys.version_info < (3, 13):
        raise ValueError("Python 3.13+ is required before any model request")
    plan_path, out = Path(plan_path).resolve(), Path(out).resolve()
    plan = load_plan(plan_path)
    validation = plan["purpose"] == "validation"
    from .design import validate_matrix

    validate_matrix(plan)
    if not validation and (plan["fixture_only"] or plan["purpose"] == "offline"):
        raise ValueError("Reference fixtures are never measured experiment evidence")
    if plan["purpose"] == "formal" and not plan["formal_spec_frozen"]:
        raise ValueError("Freeze the prospective formal design before execution")
    if out.exists() or out.is_relative_to(plan_path):
        raise ValueError(
            "New study directory outside the bound plan required; no resume/retry"
        )
    configs, limits = configure(settings, key_file=key_file)
    if plan["purpose"] == "formal":
        for role in ("sut", "put"):
            if configs[role].public() != plan["freeze"][role + "_config"]:
                raise ValueError("Model configuration changed after formal freeze")
        if limits != plan["freeze"].get("limits"):
            raise ValueError("Interaction/request budgets changed after formal freeze")
    from .home.native import load_source

    load_source()  # Verify external native source before launching or paying.
    from .car.native import load_source as load_car

    load_car()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(plan_path, out / "plan")
    write_new(
        out / "environment.json",
        {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "source_contract": code_contract(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "backend": "isolated-local-http-sidecars",
            "concurrency": limits["concurrency"],
            "packages": {
                name: package_version(name)
                for name in (
                    "fastapi",
                    "uvicorn",
                    "httpx",
                    "pydantic",
                    "jsonschema",
                    "PyYAML",
                )
            },
        },
    )
    write_new(
        out / "settings.json",
        {
            "sut": configs["sut"].public(),
            "put": configs["put"].public(),
            "limits": limits,
        },
    )
    failure = None
    try:
        with request_accounting(
            out / "requests.sqlite3", limits["max_total_api_requests"]
        ):
            with LocalStack(
                out / "plan",
                out,
                configs,
                limits,
                "validation" if validation else "model",
            ) as stack:
                from .run import run_api

                run_api(
                    out / "plan",
                    stack.chat_url,
                    out / "actor",
                    execute=True,
                    validation=validation,
                    expected_sut=configs["sut"].public(),
                    max_turns=limits["max_persona_turns"],
                    chat_timeout=limits["chat_timeout"],
                    concurrency=limits["concurrency"],
                )
    except BaseException as exc:
        failure = type(exc).__name__
        write_new(
            out / "STOP.json",
            {
                "error_type": failure,
                "automatic_retry": False,
                "note": "Failed or incomplete requests are not retried; remaining cases stay planned/unattempted.",
            },
        )
    from .ledger import summary

    ledger = summary(out / "requests.sqlite3")
    from .verify import verify_trial, verify_records

    bindings = list((out / "records").glob("*/binding.json"))
    rows = {}
    replay_error = None
    try:
        for binding in bindings:
            b, row = verify_trial(binding.parent)
            if row is not None:
                rows[b["case"]["id"]] = row
        if bindings:
            verify_records(out / "records", out / "verifier")
    except Exception as exc:
        replay_error = type(exc).__name__
    if replay_error and failure is None:
        failure = "NativeReplayError"
    attempted = list((out / "actor").glob("*/attempt.json"))
    completion = {
        "status": "complete" if failure is None else "stopped",
        "protocol": VERSION,
        "purpose": plan["purpose"],
        "evidence_type": "api_validation" if validation else "model",
        "plan_sha256": digest(plan),
        "planned": len(plan["cases"]),
        "attempted": len(attempted),
        "native_attempted": len(bindings),
        "terminal_records": len(rows),
        "missing_or_unresolved": len(plan["cases"]) - len(rows),
        "unattempted": len(plan["cases"]) - len(attempted),
        "native_replay_error": replay_error,
        "ledger": ledger,
        "automatic_retry": False,
        "concurrency": limits["concurrency"],
        "execution_elapsed_seconds": time.monotonic() - started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    if ledger["inflight_or_unknown"] or len(rows) != len(plan["cases"]):
        completion["status"] = "stopped"
    write_new(out / "completion.json", completion)
    if not validation:
        from .analysis import summarize

        analysis = summarize(plan, rows)
        analysis.update(
            plan_sha256=digest(plan),
            attempted=len(attempted),
            unattempted=completion["unattempted"],
        )
        if plan["purpose"] == "formal" and completion["status"] == "complete":
            from .design import infer

            analysis.update(inference_enabled=True, inference=infer(analysis, plan))
            analysis["note"] = (
                "Frozen fixed-final inference; bootstrap coverage is approximate and does not establish sim-to-real validity."
            )
        write_new(out / "analysis/descriptive.json", analysis)
    else:
        write_new(
            out / "validation.json",
            {
                "not_experiment_results": True,
                "integration_complete": completion["status"] == "complete",
                "episodes": [
                    {
                        "case_id": c["id"],
                        "record_available": c["id"] in rows,
                        "replay_ok": replay_error is None and c["id"] in rows,
                    }
                    for c in plan["cases"]
                ],
            },
        )
    actor_run = out / "actor/run.json"
    if actor_run.exists():
        write_new(out / "run.json", json.loads(actor_run.read_text(encoding="utf-8")))
    from .report import write_report
    from .resources import report as resource_report

    resource_report(out)
    write_report(out)
    return completion
