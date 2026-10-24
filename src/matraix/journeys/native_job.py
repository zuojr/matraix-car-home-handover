"""Prospective bindings for the official application/experiment Harbor launcher.

No execution or result generation happens here. Harbor owns jobs, trials,
lifecycles and verifier results. Each arm gets a private immutable build context.
"""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import re
import shutil

import yaml

from .cohort import VERSION, code_contract, digest, load_profiles, make_case, write_new

RUNTIME = "journey-harbor-v1"


def task_binding(task, repo_root):
    path = Path(repo_root) / task / "input/journey.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("runtime") != RUNTIME:
        raise ValueError("Unsupported journey task runtime")
    domain, number = value.get("domain"), value.get("task")
    if domain not in {"car", "home"} or number not in {
        ("J" if domain == "car" else "H") + str(i) for i in range(1, 7)
    }:
        raise ValueError("Invalid journey task binding")
    return value


def prepare_job(job, spec, *, repo_root):
    """Bind official selected personas and cell params before Harbor starts."""
    repo = Path(repo_root).resolve()
    binding = task_binding(spec["task"], repo)
    if binding is None:
        return job
    if job["environment"].get("type") != "docker":
        raise ValueError(
            "Journey sidecars require local Docker, not the host chat lane"
        )
    from .api import ModelConfig
    from .identity import runtime_contract

    configs = {r: ModelConfig.from_env(r).validate() for r in ("sut", "put")}
    if configs["put"].model != spec["agent"]["model_name"]:
        raise ValueError("persona_model must equal JOURNEY_PUT_MODEL (an API model ID)")
    params = spec.get("runtime_params") or {}
    condition = params.get("MATRIX_PARAM_CONDITION", "C1")
    variant = params.get("MATRIX_PARAM_VARIANT", "main")
    if variant not in {"main", "boundary"}:
        raise ValueError("Unknown journey variant")
    job_name = str(job["job_name"])
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_name):
        raise ValueError("Use a safe unique Harbor job name")
    root = repo / "configs/jobs/_generated/journeys" / job_name
    if root.exists():
        raise ValueError(
            "Journey job already prepared; no overwrite or automatic resume"
        )
    domain = binding["domain"]
    ids = job["_job_meta"]["selected_persona_ids"]
    profiles = load_profiles(repo, repo / spec["persona_pool"], ids, domain)
    # Stable identity ordering preserves the same fixtures across experiment arms.
    profiles.sort(key=lambda p: p["persona_id"])
    cases = []
    for block, profile in enumerate(profiles, 1):
        case = make_case(
            domain,
            binding["task"],
            block,
            condition,
            variant == "boundary",
            spec["seed"],
        )
        case.update(
            native_persona=deepcopy(profile), source_persona_id=profile["persona_id"]
        )
        case["persona_binding"] = digest(
            {"domain": domain, "profile": profile, "condition": condition}
        )
        cases.append(case)
    pool = repo / spec["persona_pool"]
    catalog = repo / "persona/schema/dimensions.json"
    plan = {
        "protocol": VERSION,
        "purpose": "harbor",
        "fixture_only": False,
        "seed": spec["seed"],
        "cases": cases,
        "planned_episodes": len(cases),
        "sources": {
            domain: {
                "pool": "inputs/" + domain,
                "manifest_sha256": hashlib.sha256(
                    (pool / "manifest.json").read_bytes()
                ).hexdigest(),
            }
        },
        "code_contract": code_contract(),
        "identity_contract": runtime_contract(catalog),
        "sut": "fixed baseline only",
        "formal_spec_frozen": False,
        "execution_authorized": False,
        "native_arm": {
            "runtime": RUNTIME,
            "task": spec["task"],
            "condition": condition,
            "variant": variant,
        },
        "native_models": {role: config.public() for role, config in configs.items()},
    }
    plan_path = root / "plan"
    dest = plan_path / "inputs" / domain
    dest.mkdir(parents=True)
    shutil.copyfile(pool / "manifest.json", dest / "manifest.json")
    for p in profiles:
        shutil.copyfile(repo / p["source_yaml"], dest / Path(p["source_yaml"]).name)
    (plan_path / "identity").mkdir()
    shutil.copyfile(catalog, plan_path / "identity/dimensions.json")
    write_new(plan_path / "plan.json", plan)
    write_new(
        plan_path / "manifest.json", {"protocol": VERSION, "plan_sha256": digest(plan)}
    )

    # One fail-stop request ledger across all arms of an official experiment.
    group = re.sub(r"-c\d+$", "", job_name)
    accounting = repo / "configs/jobs/_generated/journey-accounting" / group
    accounting.mkdir(parents=True, exist_ok=True)
    limit = int(os.environ.get("JOURNEY_REQUEST_LIMIT", "60000"))
    if not 1 <= limit <= 60000:
        raise ValueError("JOURNEY_REQUEST_LIMIT must be within 1..60000")
    from .ledger import summary

    if summary(accounting / "requests.sqlite3")["failed"]:
        raise ValueError(
            "Experiment ledger stopped; create a new experiment, never retry"
        )
    from .ledger import connect, is_stopped

    ledger = accounting / "requests.sqlite3"
    connect(ledger).close()
    if is_stopped(ledger):
        raise ValueError("Experiment ledger stopped; no further dispatch")
    if os.name == "posix":
        # The Docker worker's WAL files inherit the launcher's group. Keep the
        # shared ledger private to that group, while permitting host PUT writes.
        accounting.chmod(0o2770)
        ledger.chmod(0o660)

    shared = (
        repo / "environment/task-environments/application/chatbot-api-sidecar_journeys"
    )
    compose_rel = "application/_generated/journeys/" + job_name
    compose_dir = repo / "environment/task-environments" / compose_rel
    shutil.copytree(
        shared,
        compose_dir,
        ignore=shutil.ignore_patterns("runtime", "plan", "__pycache__"),
    )
    runtime = compose_dir / "runtime"
    runtime.mkdir()
    (runtime / "matraix").mkdir()
    shutil.copyfile(repo / "src/matraix/__init__.py", runtime / "matraix/__init__.py")
    shutil.copytree(
        Path(__file__).parent,
        runtime / "matraix/journeys",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".cache"),
    )
    for name in ("Dockerfile", "requirements.txt"):
        shutil.copyfile(shared / "build-assets" / name, runtime / name)
    write_new(runtime / "source-contract.json", code_contract())
    shutil.copytree(plan_path, compose_dir / "plan")
    compose_path = compose_dir / "docker-compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    assistant = compose["services"]["assistant"]
    assistant.setdefault("volumes", []).append(
        {"type": "bind", "source": accounting.as_posix(), "target": "/accounting"}
    )
    assistant["environment"].update(
        JOURNEY_REQUEST_LEDGER="/accounting/requests.sqlite3",
        JOURNEY_REQUEST_LIMIT=str(limit),
    )
    assistant["command"] = [
        "python",
        "-c",
        "import os; os.umask(0o002); os.execvp('uvicorn', ['uvicorn','matraix.journeys.chat:factory','--factory','--host','0.0.0.0','--port','8000'])",
    ]
    compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    task_path = root / "task"
    shutil.copytree(repo / spec["task"], task_path)
    toml = task_path / "task.toml"
    text = toml.read_text(encoding="utf-8").replace(
        'local_compose = "application/chatbot-api-sidecar_journeys"',
        f'local_compose = "{compose_rel}"',
    )
    # No secret values in recipes/tasks. Compose resolves the launcher's env.
    text += '\n[environment.env]\nJOURNEY_MODE = "model"\n'
    text += 'JOURNEY_CONTROL_TOKEN = "${JOURNEY_CONTROL_TOKEN}"\n'
    toml.write_text(text, encoding="utf-8")
    by_id = {c["source_persona_id"]: c for c in cases}
    for agent in job["agents"]:
        raw = yaml.safe_load(
            (repo / agent["kwargs"]["persona_path"]).read_text(encoding="utf-8")
        )
        case = by_id[raw["persona_id"]]
        agent.pop("name", None)
        agent["import_path"] = "matraix.journeys.agent:JourneyPersonaAPI"
        agent["kwargs"].update(
            plan_path=str(plan_path),
            case_id=case["id"],
            ledger_path=str(accounting / "requests.sqlite3"),
            request_limit=limit,
        )
    job.update(
        tasks=[{"path": str(task_path)}],
        n_attempts=1,
        retry={"max_retries": 0},
        verifier={"import_path": "matraix.journeys.harbor:JourneyVerifier"},
    )
    job["_job_meta"]["journey"] = {
        "runtime": RUNTIME,
        "plan_sha256": digest(plan),
        "condition": condition,
        "variant": variant,
        "contract": VERSION,
    }
    write_new(root / "binding.json", job["_job_meta"]["journey"])
    return job
